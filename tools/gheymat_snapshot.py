#!/usr/bin/env python3
"""Static fallback publisher for the Gheymat app.

Mirrors Gheymat/server/gheymat_server/bonbast_client.py (same bonbast protocol, same wire shapes as
Gheymat/CONTRACT.md) but runs as a one-shot script inside GitHub Actions and writes extensionless files
that GitHub Pages serves at the same paths the app requests:

  dist/health, dist/v1/latest, dist/v1/instruments, dist/v1/history/<code>, dist/v1/intraday/<code>, dist/index.html
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://bonbast.com"
UA = ("Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Mobile Safari/537.36")
COOKIES = {"cookieconsent_status": "true", "st_bb": "0"}
TOKEN_RE = re.compile(r'param\s*[=:]\s*"([^"]+)"')
HERE = Path(__file__).resolve().parent


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def headers(xhr: bool = False) -> dict:
    h = {
        "user-agent": UA,
        "accept-language": "en-US,en;q=0.9",
        "referer": f"{BASE}/",
        "origin": BASE,
    }
    if xhr:
        h["x-requested-with"] = "XMLHttpRequest"
        h["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        h["accept"] = "application/json, text/javascript, */*; q=0.01"
    return h


def get_token(session: requests.Session) -> str:
    r = session.get(f"{BASE}/", headers=headers(), cookies=COOKIES, timeout=20)
    r.raise_for_status()
    if "/cdn-cgi/challenge-platform" in r.text or "Just a moment" in r.text:
        raise SystemExit("bonbast: challenge page instead of the homepage")
    m = TOKEN_RE.search(r.text)
    if not m:
        raise SystemExit("bonbast: token not found")
    return m.group(1)


def fetch_raw(session: requests.Session) -> dict:
    for attempt in range(2):
        token = get_token(session)
        r = session.post(f"{BASE}/json", headers=headers(True), cookies=COOKIES,
                         data={"param": token}, timeout=20)
        r.raise_for_status()
        try:
            raw = r.json()
        except ValueError:
            raise SystemExit("bonbast: /json did not return JSON")
        if "reset" not in raw:
            return raw
        time.sleep(2)
    raise SystemExit("bonbast: token expired twice")


def load_instruments() -> list[dict]:
    return json.loads((HERE / "instruments.json").read_text(encoding="utf-8"))


def to_int(v) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n or None


def build_snapshot(raw: dict, instruments: list[dict]) -> dict:
    rates = []
    for ins in instruments:
        key = ins["bonbast_key"]
        rate = {
            "code": ins["code"], "kind": ins["kind"], "unit": ins["unit"], "quote": ins["quote"],
            "buy": None, "sell": None, "price": None,
            "en": ins["en"], "fa": ins["fa"], "flag": ins["flag"],
        }
        if ins["kind"] == "currency":
            sell, buy = to_int(raw.get(f"{key}1")), to_int(raw.get(f"{key}2"))
            if sell is None and buy is None:
                continue
            rate["sell"], rate["buy"] = sell, buy
        elif ins["kind"] == "coin":
            sell, buy = to_int(raw.get(key)), to_int(raw.get(f"{key}2"))
            if sell is None and buy is None:
                continue
            rate["sell"], rate["buy"] = sell, buy
        else:
            try:
                price = float(raw.get(key))
            except (TypeError, ValueError):
                continue
            if not price:
                continue
            rate["price"] = price
        rates.append(rate)
    return {
        "seq": int(time.time()),
        "fetchedAt": utc_now_iso(),
        "sourceModified": raw.get("last_modified"),
        "source": "bonbast",
        "flags": ["static"],
        "rates": rates,
    }



def fetch_history(session: requests.Session, key: str, days: int) -> list[dict]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    r = session.post(f"{BASE}/graph", headers=headers(), cookies=COOKIES, timeout=30,
                     data={"currency": key, "stdate": start.isoformat(), "endate": end.isoformat()})
    r.raise_for_status()
    sel = re.search(r'<option value="([^"]+)" selected', r.text)
    if sel and sel.group(1) != key:
        return []
    m_data = re.search(r"data:\s*\[([^\]]*)\]", r.text)
    m_labels = re.search(r"labels:\s*\[([^\]]*)\]", r.text)
    if not m_data or not m_labels:
        return []
    prices = [p.strip() for p in m_data.group(1).split(",") if p.strip()]
    labels = re.findall(r"\d{4}-\d{2}-\d{2}", m_labels.group(1))
    points = []
    for date, price in zip(labels, prices):
        try:
            points.append({"date": date, "price": float(price)})
        except ValueError:
            continue
    return points


INDEX_HTML = """<!doctype html><meta charset="utf-8"><title>Gheymat static API</title>
<p>Static fallback API for the Gheymat app. Endpoints: <a href="health">health</a>,
<a href="v1/latest">v1/latest</a>, <a href="v1/instruments">v1/instruments</a>, <code>v1/history/&lt;code&gt;</code>.</p>
"""


INTRADAY_DAYS = 7


def append_intraday(out: Path, snapshot: dict) -> int:
    """Append this run's sample to v1/intraday/<code> (last INTRADAY_DAYS days, oldest first). Returns files written."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INTRADAY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    for r in snapshot["rates"]:
        path = out / "v1" / "intraday" / r["code"]
        points = []
        if path.exists():
            try:
                points = json.loads(path.read_text(encoding="utf-8")).get("points", [])
            except (ValueError, OSError):
                points = []
        sample = {"ts": snapshot["fetchedAt"], "buy": r["buy"], "sell": r["sell"], "price": r["price"]}
        if points and points[-1].get("ts") == sample["ts"]:
            continue
        points = [p for p in points if isinstance(p, dict) and p.get("ts", "") >= cutoff]
        points.append(sample)
        write(path, {"code": r["code"], "days": INTRADAY_DAYS, "points": points})
        written += 1
    return written


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--history", action="store_true", help="also refresh v1/history/<code> for currencies")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    out = Path(args.out)
    instruments = load_instruments()
    session = requests.Session()
    raw = fetch_raw(session)
    snapshot = build_snapshot(raw, instruments)
    if len(snapshot["rates"]) < 29:
        print(f"only {len(snapshot['rates'])} rates parsed; refusing to publish", file=sys.stderr)
        return 2
    fingerprint = hashlib.sha256(json.dumps(
        {k: v for k, v in raw.items() if k[-1] in "12" or k in ("gol18", "mithqal", "ounce", "bitcoin")},
        sort_keys=True).encode()).hexdigest()[:12]
    write(out / "v1" / "latest", snapshot)
    write(out / "v1" / "instruments", instruments)
    (out / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    write(out / "health", {
        "ok": True, "lastFetchAt": snapshot["fetchedAt"], "ageSeconds": 0.0, "consecutiveFailures": 0,
        "proxyPool": {"size": 0, "healthy": 0, "inUse": None, "enabled": False, "paidConfigured": False},
        "seq": snapshot["seq"], "source": "bonbast", "mode": "static", "fingerprint": fingerprint,
    })
    print(f"latest: {len(snapshot['rates'])} rates, usd {snapshot['rates'][0].get('buy')}/{snapshot['rates'][0].get('sell')}, fp {fingerprint}")
    print(f"intraday: {append_intraday(out, snapshot)} files updated")
    if args.history:
        done = 0
        for ins in instruments:
            if ins["kind"] != "currency":
                continue
            try:
                points = fetch_history(session, ins["bonbast_key"], args.days)
            except requests.RequestException as e:
                print(f"history {ins['code']}: {e}", file=sys.stderr)
                points = []
            if points:
                write(out / "v1" / "history" / ins["code"], {"code": ins["code"], "days": args.days, "points": points})
                done += 1
            time.sleep(1.0)
        print(f"history: {done} currencies written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
