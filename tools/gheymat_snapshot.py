#!/usr/bin/env python3
"""Static fallback publisher for the Gheymat app.

Mirrors Gheymat/server/gheymat_server/bonbast_client.py (same bonbast protocol, same wire shapes as
Gheymat/CONTRACT.md) but runs as a one-shot script inside GitHub Actions and writes extensionless files
that GitHub Pages serves at the same paths the app requests:

  dist/health, dist/v1/latest, dist/v1/instruments, dist/v1/intraday/<code>, dist/index.html
  dist/v1/daily.json (all daily closes since 2012-10-09, filled by --history and --backfill from the archive page)
  dist/v1/history/<code> (full daily series per instrument), dist/v1/longhistory/<code> (coarse 1978-> seed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gheymat_seal import Sealer, load_published  # noqa: E402

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



ARCHIVE_START = "2012-10-09"
COIN_NAMES = {"azadi": "azadi", "emami": "emami", "\u00bd azadi": "half", "\u00bc azadi": "quarter", "gerami": "gerami"}
BLOCK_RUN = 4


def _cells(fragment: str) -> list[str]:
    import html as _html
    return [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td.*?</td>", fragment, flags=re.S)]


def parse_archive(page: str) -> tuple[str | None, dict[str, tuple[int | None, int | None]]]:
    """Return (date shown on the page, {code: (buy, sell)}) from a bonbast /archive page."""
    shown = re.search(r"\d{4}-\d{2}-\d{2}", page)
    values: dict[str, tuple[int | None, int | None]] = {}
    for table in re.findall(r"<table.*?</table>", page, flags=re.S):
        rows = [_cells(tr) for tr in re.findall(r"<tr.*?</tr>", table, flags=re.S)]
        rows = [r for r in rows if r]
        if not rows:
            continue
        header = [c.lower() for c in rows[0]]
        if header[:1] == ["code"]:
            for r in rows[1:]:
                if len(r) >= 4:
                    values[r[0].lower()] = (to_int(r[3]), to_int(r[2]))
        elif header[:1] == ["gold coins"]:
            for r in rows[1:]:
                if len(r) >= 3:
                    code = COIN_NAMES.get(r[0].lower())
                    if code:
                        values[code] = (to_int(r[2]), to_int(r[1]))
    return (shown.group(0) if shown else None), values


def fetch_archive(session: requests.Session, date: str) -> tuple[str | None, dict]:
    r = session.post(f"{BASE}/archive", headers=headers(), cookies=COOKIES, timeout=30, data={"date": date})
    r.raise_for_status()
    if "/cdn-cgi/challenge-platform" in r.text and "<table" not in r.text:
        raise SystemExit("bonbast: challenge page on /archive")
    return parse_archive(r.text)


ARCHIVE_GUARD_DAYS = 1000


def load_daily(out: Path) -> dict:
    """The archive state: the plain v1/daily.json while it is still published, else the sealed copy at its opaque path."""
    daily = load_published(out, "v1/daily.json", SEALER)
    if isinstance(daily, dict) and isinstance(daily.get("codes"), dict) and isinstance(daily.get("start"), str):
        return daily
    return {"start": ARCHIVE_START, "codes": {}}


def archive_shrank(out: Path, daily: dict) -> tuple[int, int] | None:
    """(previous, current) when the previously published health reported a large archive and this run loaded under half of it."""
    previous = load_published(out, "health", SEALER)
    before = previous.get("archiveDays") if isinstance(previous, dict) else None
    if isinstance(before, bool) or not isinstance(before, int) or before < ARCHIVE_GUARD_DAYS:
        return None
    now = len(known_dates(daily))
    return (before, now) if now < before // 2 else None


def save_daily(out: Path, daily: dict) -> None:
    write(out / "v1" / "daily.json", daily)


def known_dates(daily: dict) -> set[str]:
    dates: set[str] = set()
    for series in daily["codes"].values():
        dates.update(series.keys())
    return dates


def merge_day(daily: dict, date: str, values: dict[str, tuple[int | None, int | None]]) -> None:
    for code, (buy, sell) in values.items():
        if buy is None and sell is None:
            continue
        daily["codes"].setdefault(code, {})[date] = [buy, sell]


def fill_days(session: requests.Session, daily: dict, dates: list[str], pace: float, fetcher=None) -> int:
    """Fetch the given archive dates in order; stop on a suspected soft-block (BLOCK_RUN identical payloads)."""
    fetcher = fetcher or (lambda d: fetch_archive(session, d))
    fetched = 0
    previous = None
    identical_run = 0
    pending: list[tuple[str, dict]] = []
    for date in dates:
        try:
            shown, values = fetcher(date)
        except (requests.RequestException, SystemExit) as e:
            print(f"archive {date}: {e}", file=sys.stderr)
            break
        if shown != date or len(values) < 20:
            print(f"archive {date}: page shows {shown}, {len(values)} values; stopping", file=sys.stderr)
            break
        if previous is not None and values == previous:
            identical_run += 1
        else:
            identical_run = 0
        previous = values
        pending.append((date, values))
        if identical_run >= BLOCK_RUN:
            print(f"archive: {BLOCK_RUN + 1} identical payloads ending {date}; suspected soft-block, discarding them", file=sys.stderr)
            pending = pending[: -(BLOCK_RUN + 1)]
            break
        time.sleep(max(0.0, pace + random.uniform(-0.4, 0.6)))
    for date, values in pending:
        merge_day(daily, date, values)
        fetched += 1
    return fetched


def recent_missing_dates(daily: dict, days: int) -> list[str]:
    have = known_dates(daily)
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(1, days + 1):
        d = (today - timedelta(days=i)).isoformat()
        if d not in have:
            out.append(d)
    return out


def backfill_dates(daily: dict, count: int) -> list[str]:
    have = known_dates(daily)
    today = datetime.now(timezone.utc).date()
    earliest = min(have) if have else today.isoformat()
    cursor = datetime.strptime(earliest, "%Y-%m-%d").date() - timedelta(days=1)
    floor = datetime.strptime(daily.get("start", ARCHIVE_START), "%Y-%m-%d").date()
    out = []
    while len(out) < count and cursor >= floor:
        d = cursor.isoformat()
        if d not in have:
            out.append(d)
        cursor -= timedelta(days=1)
    return out


def write_history_files(out: Path, daily: dict) -> int:
    written = 0
    for code, series in daily["codes"].items():
        points = []
        for date in sorted(series):
            buy, sell = series[date]
            price = sell if sell is not None else buy
            if price:
                points.append({"date": date, "price": float(price), "buy": buy, "sell": sell})
        if points:
            write(out / "v1" / "history" / code, {"code": code, "days": len(points), "points": points})
            written += 1
    return written


def write_long_history(out: Path, archive_file: Path) -> int:
    """Coarse pre-2012 seed (hansha 'all' series kept in archive/all.json, USD back to 1978)."""
    if not archive_file.exists():
        return 0
    try:
        data = json.loads(archive_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return 0
    written = 0
    for item in data:
        code = item.get("ab")
        pts = []
        for p in item.get("ps", []):
            price = p.get("sp") or p.get("bp")
            if code and price and p.get("ts"):
                pts.append({"date": p["ts"][:10], "price": float(price)})
        pts.sort(key=lambda x: x["date"])
        if len(pts) >= 10:
            write(out / "v1" / "longhistory" / code, {"code": code, "days": len(pts), "points": pts, "source": "coarse-archive"})
            written += 1
    return written


INDEX_HTML = """<!doctype html><meta charset="utf-8"><title>Gheymat static API</title>
<p>Static fallback API for the Gheymat app. Endpoints: <a href="health">health</a>,
<a href="v1/latest">v1/latest</a>, <a href="v1/instruments">v1/instruments</a>, <code>v1/history/&lt;code&gt;</code>,
<code>v1/intraday/&lt;code&gt;</code>, <code>v1/longhistory/&lt;code&gt;</code>.</p>
"""

INTRADAY_DAYS = 7


def append_intraday(out: Path, snapshot: dict) -> int:
    """Append this run's sample to v1/intraday/<code> (last INTRADAY_DAYS days, oldest first). Returns files written."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INTRADAY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    for r in snapshot["rates"]:
        path = out / "v1" / "intraday" / r["code"]
        previous = load_published(out, f"v1/intraday/{r['code']}", SEALER)
        points = previous.get("points", []) if isinstance(previous, dict) else []
        if not isinstance(points, list):
            points = []
        sample = {"ts": snapshot["fetchedAt"], "buy": r["buy"], "sell": r["sell"], "price": r["price"]}
        if points and points[-1].get("ts") == sample["ts"]:
            continue
        points = [p for p in points if isinstance(p, dict) and p.get("ts", "") >= cutoff]
        points.append(sample)
        write(path, {"code": r["code"], "days": INTRADAY_DAYS, "points": points})
        written += 1
    return written


SEALER = None
PLAIN_ALSO = True


def write(path: Path, obj) -> None:
    """Write obj at its plain path (while the app still reads plain files) and, when keys are present, sealed at the opaque path.

    Once plain files are off, a plain copy carried over from an earlier publish is removed so it cannot shadow
    the sealed state that load_published reads back on the next run."""
    if PLAIN_ALSO or SEALER is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    elif path.exists():
        path.unlink()
    if SEALER is not None:
        root = _dist_root(path)
        logical = path.relative_to(root).as_posix()
        sealed = root / SEALER.opaque_path(logical)
        sealed.parent.mkdir(parents=True, exist_ok=True)
        sealed.write_text(json.dumps(SEALER.seal(logical, obj), separators=(",", ":")), encoding="utf-8")


_DIST_ROOT: Path | None = None


def _dist_root(path: Path) -> Path:
    if _DIST_ROOT is not None:
        return _DIST_ROOT
    for parent in path.parents:
        if parent.name == "v1":
            return parent.parent
    return path.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--history", action="store_true", help="fill missing recent days from the archive and rewrite v1/history/*")
    ap.add_argument("--backfill", type=int, default=0, help="also fetch N older archive days (chunked backfill to 2012-10-09)")
    ap.add_argument("--pace", type=float, default=2.5, help="seconds between archive requests")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    out = Path(args.out)
    global SEALER, PLAIN_ALSO, _DIST_ROOT
    _DIST_ROOT = out
    SEALER = Sealer.from_env()
    PLAIN_ALSO = os.environ.get("GHEYMAT_PLAIN", "1") == "1"
    print("sealed channel:", "on" if SEALER else "off (no keys)", "| plain files:", "on" if PLAIN_ALSO or SEALER is None else "off")
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
    daily = load_daily(out)
    shrank = archive_shrank(out, daily)
    if shrank is not None:
        print(f"archive state shrank from {shrank[0]} to {shrank[1]} days; refusing to publish", file=sys.stderr)
        return 3
    write(out / "v1" / "latest", snapshot)
    write(out / "v1" / "instruments", instruments)
    (out / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    print(f"latest: {len(snapshot['rates'])} rates, usd {snapshot['rates'][0].get('buy')}/{snapshot['rates'][0].get('sell')}, fp {fingerprint}")
    print(f"intraday: {append_intraday(out, snapshot)} files updated")
    if args.history or args.backfill:
        dates = recent_missing_dates(daily, 7) if args.history else []
        if args.backfill:
            dates += backfill_dates(daily, args.backfill)
        dates = list(dict.fromkeys(dates))
        fetched = fill_days(session, daily, dates, args.pace)
        save_daily(out, daily)
        files = write_history_files(out, daily)
        long_files = write_long_history(out, HERE.parent / "archive" / "all.json")
        have = known_dates(daily)
        print(f"history: fetched {fetched} archive days, {files} history files, {long_files} long-history files, "
              f"coverage {min(have) if have else '-'} .. {max(have) if have else '-'} ({len(have)} days)")
    write(out / "health", {
        "ok": True, "lastFetchAt": snapshot["fetchedAt"], "ageSeconds": 0.0, "consecutiveFailures": 0,
        "proxyPool": {"size": 0, "healthy": 0, "inUse": None, "enabled": False, "paidConfigured": False},
        "seq": snapshot["seq"], "source": "bonbast", "mode": "static", "fingerprint": fingerprint,
        "archiveDays": len(known_dates(daily)),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
