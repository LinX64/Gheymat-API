#!/usr/bin/env python3
"""Static channel publisher for the Gheymat app (its only data path).

Combines several sources in priority order (GHEYMAT_SOURCES, default "hansha,bonbast"; CONTRACT.md "Static
publisher sources"): every source is fetched, each code takes its value from the first source that supplies
one, and a source that fails or goes stale is skipped. Same wire shapes as Gheymat/CONTRACT.md; runs as a
one-shot script inside GitHub Actions and writes extensionless files that GitHub Pages serves at the same
paths the app requests:

  dist/health, dist/v1/latest, dist/v1/instruments, dist/v1/intraday/<code>, dist/index.html
  dist/v1/daily.json (all daily closes since 2012-10-09, filled by --history and --backfill from the archive page)
  dist/v1/history/<code> (full daily series per instrument), dist/v1/longhistory/<code> (coarse 1978-> seed)

dist/v1/latest additionally carries up to 8 computed cross-rate rows (Rate.computed=true) derived from
bonbast's separate /converter endpoint - CONTRACT.md "Computed cross-rates". See fetch_converter,
compute_cross_rates, fetch_computed_rates and merge_rates below; stateless per run, by design (no
persisted converter table), so a bad fetch just drops the 8 rows for that publish, never the other 37.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
HANSHA = "https://hansha.online"
SOURCES_ENV = "GHEYMAT_SOURCES"
DEFAULT_SOURCES = ("hansha", "bonbast")
MIN_DIRECT = 29  # publish floor on combined direct rates (unchanged from the bonbast-only publisher)
STALE_SOURCE_SECONDS = 30 * 60  # a source whose newest observation is older than this is skipped
FUTURE_SLACK_SECONDS = 5 * 60


class SourceError(RuntimeError):
    """A source failed as a whole (HTTP error, challenge page, bad body, stale feed); the run moves on."""


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
        raise SourceError("bonbast: challenge page instead of the homepage")
    m = TOKEN_RE.search(r.text)
    if not m:
        raise SourceError("bonbast: token not found")
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
            raise SourceError("bonbast: /json did not return JSON")
        if not isinstance(raw, dict):
            raise SourceError("bonbast: /json is not a JSON object")
        if "reset" not in raw:
            return raw
        time.sleep(2)
    raise SourceError("bonbast: token expired twice")


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
        if ins.get("computed"):
            continue  # direct-only here; computed cross-rates come from fetch_computed_rates/compute_cross_rates
        key = ins.get("bonbast_key")
        if not key:
            continue  # hansha-only instrument (CONTRACT.md "Static publisher sources")
        rate = {
            "code": ins["code"], "kind": ins["kind"], "unit": ins["unit"], "quote": ins["quote"],
            "buy": None, "sell": None, "price": None,
            "en": ins["en"], "fa": ins["fa"], "flag": ins["flag"], "computed": False,
            "buyRaw": None, "sellRaw": None,
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


def normalize_ts(value) -> str | None:
    """A source timestamp as CONTRACT.md's `%Y-%m-%dT%H:%M:%SZ` UTC, clamped to now if it is in the future;
    None when it is missing or unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt > now + timedelta(seconds=FUTURE_SLACK_SECONDS):
        return None
    return min(dt.astimezone(timezone.utc), now).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_seconds(stamp: str) -> float:
    dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def positive(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n > 0 else None


def fetch_hansha(session: requests.Session) -> list:
    r = session.get(f"{HANSHA}/latest", headers={"user-agent": UA, "accept": "application/json"}, timeout=20)
    r.raise_for_status()
    try:
        rows = r.json()
    except ValueError:
        raise SourceError("hansha: /latest did not return JSON")
    if not isinstance(rows, list):
        raise SourceError("hansha: /latest is not a JSON array")
    return rows


def build_hansha_snapshot(rows: list, instruments: list[dict]) -> dict:
    """Map hansha /latest rows onto our instrument table (CONTRACT.md "Static publisher sources").

    `ab` is our code and `ps[0]` the newest point. Hansha has no `ounce` and prices `btc` in toman while ours
    quotes usd, so usd-quoted instruments are never taken from here. Names and glyphs always come from our
    table, never hansha's `en`/`fa`/`av`. fetchedAt is the oldest observation used, sourceModified the newest."""
    by_ab = {row["ab"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("ab"), str)}
    rates, stamps = [], []
    for ins in instruments:
        if ins.get("computed") or ins["quote"] != "toman":
            continue
        row = by_ab.get(ins["code"])
        ps = row.get("ps") if isinstance(row, dict) else None
        point = ps[0] if isinstance(ps, list) and ps and isinstance(ps[0], dict) else None
        stamp = normalize_ts(point.get("ts")) if point else None
        if stamp is None:
            continue  # no point, or no trustworthy observation time for it
        rate = {
            "code": ins["code"], "kind": ins["kind"], "unit": ins["unit"], "quote": ins["quote"],
            "buy": None, "sell": None, "price": None,
            "en": ins["en"], "fa": ins["fa"], "flag": ins["flag"], "computed": False,
            "buyRaw": None, "sellRaw": None,
        }
        if ins["kind"] in ("currency", "coin"):
            buy, sell = positive(point.get("bp")), positive(point.get("sp"))
            if buy is None or sell is None:
                continue
            rate["buy"], rate["sell"] = int(buy), int(sell)
        else:
            price = positive(point.get("sp"))
            if price is None:
                continue
            rate["price"] = float(int(price))
        rates.append(rate)
        stamps.append(stamp)
    if stamps:  # a row frozen far behind the feed counts as missing (the next source fills it), so one stale
        newest = max(stamps)  # row never drags the whole snapshot's fetchedAt back
        keep = [i for i, s in enumerate(stamps) if age_seconds(s) - age_seconds(newest) <= STALE_SOURCE_SECONDS]
        rates, stamps = [rates[i] for i in keep], [stamps[i] for i in keep]
    return {
        "seq": int(time.time()),
        "fetchedAt": min(stamps) if stamps else utc_now_iso(),
        "sourceModified": max(stamps) if stamps else None,
        "source": "hansha",
        "flags": ["static"],
        "rates": rates,
    }


def source_order(raw: str | None = None) -> list[str]:
    """GHEYMAT_SOURCES as a de-duplicated list of known source names; the default when empty or unknown."""
    raw = os.environ.get(SOURCES_ENV, "") if raw is None else raw
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    known = [n for n in dict.fromkeys(names) if n in DEFAULT_SOURCES]
    return known or list(DEFAULT_SOURCES)


def fetch_source(name: str, session: requests.Session, instruments: list[dict]) -> dict:
    if name == "hansha":
        snap = build_hansha_snapshot(fetch_hansha(session), instruments)
        if not snap["rates"]:
            raise SourceError("hansha: no usable rows")
        age = age_seconds(snap["sourceModified"])
        if age > STALE_SOURCE_SECONDS:
            raise SourceError(f"hansha: newest point is {int(age // 60)} min old")
        return snap
    if name == "bonbast":
        return build_snapshot(fetch_raw(session), instruments)
    raise SourceError(f"unknown source {name}")


def collect_sources(session: requests.Session, instruments: list[dict], order: list[str],
                    fetch=fetch_source) -> list[dict]:
    """One snapshot per source that worked, in priority order; a failed or stale source is logged and skipped."""
    results = []
    for name in order:
        try:
            snap = fetch(name, session, instruments)
        except (SourceError, requests.RequestException, ValueError) as e:
            print(f"source {name}: skipped ({type(e).__name__}: {e})", file=sys.stderr)
            continue
        print(f"source {name}: {len(snap['rates'])} rates, observed {snap['fetchedAt']}")
        results.append(snap)
    return results


def combine_sources(results: list[dict], instruments: list[dict]) -> tuple[dict, dict[str, int]]:
    """Per-instrument fill: each code from the first snapshot (priority order) that carries it.

    Returns the combined snapshot and per-source counts. `source` is the source that supplied the most rates
    (ties go to the higher priority), `sourceModified` is its stamp, and `fetchedAt` is the OLDEST observation
    among the sources used, so the app never shows a republished value as fresher than it is."""
    chosen: dict[str, tuple[dict, str]] = {}
    for snap in results:
        for r in snap["rates"]:
            chosen.setdefault(r["code"], (r, snap["source"]))
    counts: dict[str, int] = {}
    for _, src in chosen.values():
        counts[src] = counts.get(src, 0) + 1
    order = [i["code"] for i in instruments if not i.get("computed")]
    rates = [chosen[c][0] for c in order if c in chosen]
    used = [s for s in results if counts.get(s["source"])]
    if not used:
        return {"seq": int(time.time()), "fetchedAt": utc_now_iso(), "sourceModified": None,
                "source": "none", "flags": ["static"], "rates": []}, {}
    primary = max(used, key=lambda s: counts[s["source"]])
    snapshot = {
        "seq": int(time.time()),
        "fetchedAt": min(s["fetchedAt"] for s in used),
        "sourceModified": primary["sourceModified"],
        "source": primary["source"],
        "flags": ["static"],
        "rates": rates,
    }
    return snapshot, {s["source"]: counts[s["source"]] for s in used}


def rates_fingerprint(rates: list[dict]) -> str:
    """Short hash of the published values only (never timestamps), whichever source supplied them."""
    values = {r["code"]: [r.get("buy"), r.get("sell"), r.get("price")] for r in rates}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]


def parse_converter_table(obj) -> dict | None:
    """Defensive float-coerce a bonbast /converter body into {UPPERCASE code: units per 1 EUR}, or None
    when `obj` isn't a JSON object. Mirrors Gheymat/server/gheymat_server/converter_client._coerce_table."""
    if not isinstance(obj, dict):
        return None
    table: dict[str, float] = {}
    for k, v in obj.items():
        try:
            table[str(k).upper()] = float(v)
        except (TypeError, ValueError):
            continue
    return table


def fetch_converter(session: requests.Session) -> dict | None:
    """POST /converter: bonbast's separate 174-currency EUR-pivoted forex table, used for the 8 computed
    cross-rate instruments (CONTRACT.md "Computed cross-rates"). Unlike /json this needs no `param` token
    and no cookies - mirrors converter_client.py's exact request shape (base headers + accept +
    x-requested-with, no content-type since there is no body). Never raises: a failed/blocked/non-JSON
    fetch here must stay non-fatal to the whole publish run, unlike fetch_raw's token handling."""
    h = headers()
    h["x-requested-with"] = "XMLHttpRequest"
    h["accept"] = "application/json, text/javascript, */*; q=0.01"
    try:
        r = session.post(f"{BASE}/converter", headers=h, timeout=20)
        r.raise_for_status()
        raw = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"converter: {e}", file=sys.stderr)
        return None
    table = parse_converter_table(raw)
    if table is None:
        print("converter: /converter did not return a JSON object", file=sys.stderr)
        return None
    return table


def compute_cross_rates(table: dict, eur_buy, eur_sell, instruments: list[dict]) -> list[dict]:
    """One rate per `computed` instrument: buy/sell = round(unit * eur.{buy,sell} * conv["EUR"]/conv[key]).

    Returns [] whenever the result would be untrustworthy: EUR's own direct quote is missing this run, or
    the pivot check fails (bonbast re-based /converter - conv["EUR"] must be exactly 1.0). A single
    instrument's own converter key being absent or non-positive only skips that one row, never the other 7.
    """
    if eur_buy is None or eur_sell is None:
        return []
    if table.get("EUR") != 1.0:
        print('converter: pivot check failed (EUR != 1.0); dropping computed rows', file=sys.stderr)
        return []
    pivot = table["EUR"]
    rates = []
    for ins in instruments:
        if not ins.get("computed"):
            continue
        rate = table.get(ins["bonbast_key"])
        if rate is None or not math.isfinite(rate) or rate <= 0:
            continue
        k = pivot / rate
        buy_raw = ins["unit"] * eur_buy * k
        sell_raw = ins["unit"] * eur_sell * k
        if not (math.isfinite(buy_raw) and math.isfinite(sell_raw)):
            continue
        rates.append({
            "code": ins["code"], "kind": ins["kind"], "unit": ins["unit"], "quote": ins["quote"],
            "buy": round(buy_raw), "sell": round(sell_raw), "price": None,
            "en": ins["en"], "fa": ins["fa"], "flag": ins["flag"], "computed": True,
            "buyRaw": buy_raw, "sellRaw": sell_raw,
        })
    return rates


def fetch_computed_rates(session: requests.Session, direct_rates: list[dict], instruments: list[dict],
                          fetcher=None) -> list[dict]:
    """Thin orchestrator: skip the /converter call entirely when this run's own EUR quote can't be used to
    pivot it, else fetch+compute. `fetcher` is an injection seam for tests (same convention as
    fill_days(..., fetcher=...)); defaults to fetch_converter."""
    eur = next((r for r in direct_rates if r["code"] == "eur"), None)
    if eur is None or eur["buy"] is None or eur["sell"] is None:
        return []
    table = (fetcher or fetch_converter)(session)
    if table is None:
        return []
    return compute_cross_rates(table, eur["buy"], eur["sell"], instruments)


def merge_rates(direct_rates: list[dict], computed_rates: list[dict], instruments: list[dict]) -> list[dict]:
    """Append computed_rates onto direct_rates and reorder to instruments.json's own order (parity with
    the Gheymat server's merge_computed_rates); a no-op when there are no computed rows this run."""
    if not computed_rates:
        return direct_rates
    by_code = {r["code"]: r for r in direct_rates + computed_rates}
    return [by_code[i["code"]] for i in instruments if i["code"] in by_code]


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


INDEX_HTML = """<!doctype html><meta charset="utf-8"><title>Gheymat</title>
<p>Data for the Gheymat iPhone app, served only over its encrypted, signed channel.</p>
<p><a href="privacy.html">Privacy Policy</a> · <a href="support.html">Support</a></p>
"""

PRIVACY_HTML = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Gheymat Privacy Policy</title>
<style>body{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;color:#111}
h1{font-size:28px}h2{font-size:18px;margin-top:28px}p,li{color:#333}footer{margin-top:48px;color:#777;font-size:13px}</style>
<h1>Gheymat Privacy Policy</h1>
<p>Last updated: 2026-11-07</p>
<p>Gheymat is an iOS app that shows Iranian free-market currency, gold and crypto prices. This policy covers the
Gheymat app only.</p>
<h2>Data we collect</h2>
<p><strong>None.</strong> Gheymat has no user accounts, no sign-in, no analytics SDK, no advertising SDK, and no
crash-reporting SDK. The app does not know who you are and cannot identify you.</p>
<h2>Data stored on your device</h2>
<p>Your favourites, your chosen list/grid layout, your appearance setting, and a local cache of the latest prices
are stored only in the app's local storage on your device. This data never leaves your device and is not visible
to us.</p>
<h2>Network requests</h2>
<p>The app fetches currency, gold and crypto prices from Gheymat's own data feed. These requests carry no
account identifier, advertising identifier, or other data that identifies you. Standard network metadata (such
as your IP address) is visible to the hosting infrastructure the way it is for any web request, and is not
logged or retained by us in a way that is linked to you.</p>
<h2>Price data source</h2>
<p>Prices are sourced from public Iranian market pages: hansha.online first, with bonbast.com filling anything it
does not carry and taking over when it is unavailable. Gheymat is an independent app and is not affiliated with,
endorsed by, or operated by either site.</p>
<h2>Children</h2>
<p>Gheymat is not directed at children and does not knowingly collect data from anyone, including children,
because it does not collect data from anyone.</p>
<h2>Changes</h2>
<p>If this policy changes, the date above will change. Material changes will be reflected in the app's release
notes.</p>
<h2>Contact</h2>
<p>Questions about this policy: <a href="mailto:mohsen.rezaniaa75@gmail.com">mohsen.rezaniaa75@gmail.com</a></p>
<footer><a href="index.html">Gheymat static API</a> · <a href="support.html">Support</a></footer>
"""

SUPPORT_HTML = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Gheymat Support</title>
<style>body{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;color:#111}
h1{font-size:28px}h2{font-size:18px;margin-top:28px}p,li{color:#333}footer{margin-top:48px;color:#777;font-size:13px}</style>
<h1>Gheymat Support</h1>
<h2>Contact</h2>
<p>For help, feedback or bug reports: <a href="mailto:mohsen.rezaniaa75@gmail.com">mohsen.rezaniaa75@gmail.com</a></p>
<h2>Prices look stale or wrong</h2>
<p>Gheymat shows a freshness indicator at the top of the Prices screen. The upstream market data updates on its
own schedule and is not always live by the second; the app shows exactly when it last updated. If it has been
stuck for a long time, pull down on the Prices screen to refresh, or check your internet connection.</p>
<h2>Is this financial advice?</h2>
<p>No. Gheymat shows market prices and a simple trend line computed from recent history. Nothing in the app is
financial advice, and the trend estimate is not a prediction you should rely on for financial decisions.</p>
<h2>Why can't I see 40 years of history for gold or coins?</h2>
<p>Daily history going back to 2012 is available for currencies. Gold, coins and crypto currently only have the
history the app itself has collected since you started using it; older daily history for those is on our
roadmap.</p>
<footer><a href="index.html">Gheymat static API</a> · <a href="privacy.html">Privacy Policy</a></footer>
"""

INTRADAY_DAYS = 7


def append_intraday(out: Path, snapshot: dict) -> int:
    """Append this run's sample to v1/intraday/<code> (last INTRADAY_DAYS days, oldest first). Returns files written."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INTRADAY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    for r in snapshot["rates"]:
        if r.get("computed"):
            continue  # CONTRACT.md: no server-side ticks are kept for computed codes
        path = out / "v1" / "intraday" / r["code"]
        previous = load_published(out, f"v1/intraday/{r['code']}", SEALER)
        points = previous.get("points", []) if isinstance(previous, dict) else []
        if not isinstance(points, list):
            points = []
        sample = {"ts": snapshot["fetchedAt"], "buy": r["buy"], "sell": r["sell"], "price": r["price"]}
        if points and str(points[-1].get("ts", "")) >= sample["ts"]:
            continue  # an unchanged (or older, after a source switch) observation adds no point
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
    order = source_order()
    print("sources:", " > ".join(order))
    snapshot, counts = combine_sources(collect_sources(session, instruments, order), instruments)
    if len(snapshot["rates"]) < MIN_DIRECT:
        print(f"only {len(snapshot['rates'])} rates from all sources; refusing to publish", file=sys.stderr)
        return 2
    fingerprint = rates_fingerprint(snapshot["rates"])
    daily = load_daily(out)
    shrank = archive_shrank(out, daily)
    if shrank is not None:
        print(f"archive state shrank from {shrank[0]} to {shrank[1]} days; refusing to publish", file=sys.stderr)
        return 3
    try:
        computed_rates = fetch_computed_rates(session, snapshot["rates"], instruments)
    except (ValueError, OverflowError, ArithmeticError) as e:
        print(f"converter: unexpected error computing cross-rates: {e}", file=sys.stderr)
        computed_rates = []
    snapshot["rates"] = merge_rates(snapshot["rates"], computed_rates, instruments)
    write(out / "v1" / "latest", snapshot)
    write(out / "v1" / "instruments", instruments)
    (out / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (out / "privacy.html").write_text(PRIVACY_HTML, encoding="utf-8")
    (out / "support.html").write_text(SUPPORT_HTML, encoding="utf-8")
    print(f"latest: {len(snapshot['rates'])} rates ({', '.join(f'{k} {v}' for k, v in counts.items())}), "
          f"usd {snapshot['rates'][0].get('buy')}/{snapshot['rates'][0].get('sell')}, observed {snapshot['fetchedAt']}, "
          f"fp {fingerprint}")
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
        "ok": True, "lastFetchAt": snapshot["fetchedAt"],
        "ageSeconds": round(max(0.0, age_seconds(snapshot["fetchedAt"])), 1), "consecutiveFailures": 0,
        "proxyPool": {"size": 0, "healthy": 0, "inUse": None, "enabled": False, "paidConfigured": False},
        "seq": snapshot["seq"], "source": snapshot["source"], "sources": counts, "mode": "static",
        "fingerprint": fingerprint,
        "archiveDays": len(known_dates(daily)),
        "converter": {"fetchedAt": utc_now_iso() if computed_rates else None,
                      "ageSeconds": 0.0 if computed_rates else None, "stale": not bool(computed_rates)},
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
