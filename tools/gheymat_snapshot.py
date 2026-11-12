#!/usr/bin/env python3
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
from gheymat_seal import Sealer, load_published
import gheymat_ai
import gheymat_news
import live_guard

BASE = "https://bonbast.com"
UA = ("Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Mobile Safari/537.36")
COOKIES = {"cookieconsent_status": "true", "st_bb": "0"}
TOKEN_RE = re.compile(r'param\s*[=:]\s*"([^"]+)"')
HERE = Path(__file__).resolve().parent
HANSHA = "https://hansha.online"
SOURCES_ENV = "GHEYMAT_SOURCES"
DEFAULT_SOURCES = ("hansha", "bonbast")
MIN_DIRECT = 29
STALE_SOURCE_SECONDS = 30 * 60
FUTURE_SLACK_SECONDS = 5 * 60


class SourceError(RuntimeError):
    pass


class SourceBlocked(SourceError):

    def __init__(self, kind: str, retry_after: int | None = None):
        super().__init__("live source blocked")
        self.kind = kind
        self.retry_after = retry_after


def _classify(r) -> None:
    outcome, kind, retry_after = live_guard.classify_response(
        r.status_code, r.text[:2000], r.headers.get("Retry-After"))
    if outcome == "blocked":
        raise SourceBlocked(kind, retry_after)
    if outcome == "failed":
        raise SourceError("live source failed")


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
    _classify(r)
    m = TOKEN_RE.search(r.text)
    if not m:
        raise SourceBlocked("token")
    return m.group(1)


def fetch_raw(session: requests.Session) -> dict:
    for attempt in range(2):
        token = get_token(session)
        r = session.post(f"{BASE}/json", headers=headers(True), cookies=COOKIES,
                         data={"param": token}, timeout=20)
        _classify(r)
        try:
            raw = r.json()
        except ValueError:
            raise SourceBlocked("format")
        if not isinstance(raw, dict):
            raise SourceBlocked("format")
        if "reset" not in raw:
            return raw
        time.sleep(2)
    raise SourceBlocked("token")


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
            continue
        key = ins.get("bonbast_key")
        if not key:
            continue
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


def hansha_mark(rows: list) -> str | None:
    stamps = []
    for row in rows:
        ps = row.get("ps") if isinstance(row, dict) else None
        if isinstance(ps, list) and ps and isinstance(ps[0], dict):
            stamp = normalize_ts(ps[0].get("ts"))
            if stamp:
                stamps.append(stamp)
    return max(stamps) if stamps else None


def build_hansha_snapshot(rows: list, instruments: list[dict]) -> dict:
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
            continue
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
            rate["buy"], rate["sell"] = round(buy * ins["unit"]), round(sell * ins["unit"])
        else:
            price = positive(point.get("sp"))
            if price is None:
                continue
            rate["price"] = float(round(price * ins["unit"]))
        rates.append(rate)
        stamps.append(stamp)
    if stamps:
        newest = max(stamps)
        keep = [i for i, s in enumerate(stamps) if age_seconds(s) - age_seconds(newest) <= STALE_SOURCE_SECONDS]
        rates, stamps = [rates[i] for i in keep], [stamps[i] for i in keep]
    return {
        "seq": int(time.time()),
        "fetchedAt": min(stamps) if stamps else utc_now_iso(),
        "sourceModified": max(stamps) if stamps else None,
        "source": "hansha",
        "flags": ["static"],
        "rates": rates,
        "observed": {r["code"]: s for r, s in zip(rates, stamps)},
    }


def source_order(raw: str | None = None) -> list[str]:
    raw = os.environ.get(SOURCES_ENV, "") if raw is None else raw
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    known = [n for n in dict.fromkeys(names) if n in DEFAULT_SOURCES]
    return known or list(DEFAULT_SOURCES)


ORDER_ENV = "GHEYMAT_ORDER"
LIVE_FIRST_FROM_ENV = "GHEYMAT_LIVE_FIRST_FROM"
LIVE_NAME = "bonbast"
PRIMARY_NAME = "hansha"
ORDER_MODES = ("default", "live-first", "primary-only")


def _explicit_sources() -> bool:
    return bool(os.environ.get(SOURCES_ENV, "").strip())


def effective_mode(now: float) -> str:
    mode = os.environ.get(ORDER_ENV, "").strip().lower()
    if mode not in ORDER_MODES:
        mode = "default"
    if mode == "default":
        raw = os.environ.get(LIVE_FIRST_FROM_ENV, "").strip()
        if raw:
            try:
                start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if now >= start.timestamp():
                    mode = "live-first"
            except (ValueError, OverflowError):
                pass
    return mode


def live_first_active(now: float) -> bool:
    return not _explicit_sources() and effective_mode(now) == "live-first"


def plan_sources(now: float, state: dict, primary_short: bool = False) -> list[str]:
    order = source_order()
    if not _explicit_sources():
        mode = effective_mode(now)
        if mode == "live-first":
            order = [LIVE_NAME, PRIMARY_NAME]
        elif mode == "primary-only":
            order = [PRIMARY_NAME]
    if not live_first_active(now):
        state = live_guard.new_state()
    return live_guard.effective_order(order, LIVE_NAME, state, now, primary_short)


_LIVE_STATE: dict = live_guard.new_state()
_LIVE_RUN: dict = {"outcome": None, "kind": None}


def _note_block(kind: str, retry_after, now: float | None = None) -> None:
    global _LIVE_STATE
    _LIVE_STATE = live_guard.record_block(
        _LIVE_STATE, time.time() if now is None else now, kind, retry_after)


def _note_clean() -> None:
    global _LIVE_STATE
    _LIVE_STATE = live_guard.record_clean(_LIVE_STATE, time.time())


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
    results = []
    for index, name in enumerate(order, start=1):
        try:
            snap = fetch(name, session, instruments)
        except (SourceError, requests.RequestException, ValueError) as e:
            if name == LIVE_NAME:
                if isinstance(e, SourceBlocked):
                    _note_block(e.kind, e.retry_after)
                    _LIVE_RUN.update(outcome="blocked", kind=e.kind)
                else:
                    _LIVE_RUN.update(outcome="failed",
                                     kind="timeout" if isinstance(e, requests.Timeout) else None)
            detail = str(e)
            for other_index, other in enumerate(order, start=1):
                detail = detail.replace(other, f"source {other_index}")
            print(f"source {index}: skipped ({type(e).__name__}: {detail})", file=sys.stderr)
            continue
        print(f"source {index}: {len(snap['rates'])} rates, observed {snap['fetchedAt']}")
        results.append(snap)
    return results


def combine_sources(results: list[dict], instruments: list[dict],
                    live_first: bool = False) -> tuple[dict, dict[str, int], dict[str, str]]:
    chosen: dict[str, tuple[dict, str, str]] = {}
    for snap in results:
        observed = snap.get("observed", {})
        for r in snap["rates"]:
            chosen.setdefault(r["code"], (r, snap["source"], observed.get(r["code"], snap["fetchedAt"])))
    counts: dict[str, int] = {}
    for _, src, _ in chosen.values():
        counts[src] = counts.get(src, 0) + 1
    order = [i["code"] for i in instruments if not i.get("computed")]
    rates = [chosen[c][0] for c in order if c in chosen]
    used = [s for s in results if counts.get(s["source"])]
    if not used:
        return {"seq": int(time.time()), "fetchedAt": utc_now_iso(), "sourceModified": None,
                "source": "none", "flags": ["static"], "rates": []}, {}, {}
    primary = max(used, key=lambda s: counts[s["source"]])
    fetched_at = min(s["fetchedAt"] for s in used)
    if live_first:
        core = {i["code"] for i in instruments if i.get("bonbast_key") and not i.get("computed")}
        core_stamps = [chosen[c][2] for c in order if c in chosen and c in core]
        if core_stamps:
            fetched_at = min(core_stamps)
    snapshot = {
        "seq": int(time.time()),
        "fetchedAt": fetched_at,
        "sourceModified": primary["sourceModified"],
        "source": primary["source"],
        "flags": ["static"],
        "rates": rates,
    }
    return snapshot, {s["source"]: counts[s["source"]] for s in used}, {c: chosen[c][2] for c in order if c in chosen}


DIVERGE_CODES = 5
DIVERGE_PCT = 0.03
REPLACE_PCT = 0.05


def _sell_of(r: dict):
    v = r.get("sell")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _shared_usable(r: dict | None) -> bool:
    return r is not None and _sell_of(r) is not None and isinstance(r.get("buy"), (int, float)) \
        and not isinstance(r.get("buy"), bool)


def check_divergence(live: dict, primary: dict) -> tuple[dict | None, int]:
    mine = {r["code"]: r for r in primary["rates"]}
    far, replace = 0, set()
    for r in live["rates"]:
        other = mine.get(r["code"])
        if not (_shared_usable(r) and _shared_usable(other)):
            continue
        diff = abs(_sell_of(r) - _sell_of(other)) / _sell_of(other)
        if diff >= DIVERGE_PCT:
            far += 1
        if diff > REPLACE_PCT:
            replace.add(r["code"])
    if far >= DIVERGE_CODES:
        return None, 0
    if not replace:
        return live, 0
    trimmed = dict(live, rates=[r for r in live["rates"] if r["code"] not in replace])
    if "observed" in live:
        trimmed["observed"] = {c: v for c, v in live["observed"].items() if c not in replace}
    return trimmed, len(replace)


def count_apart(live: dict, primary: dict) -> int:
    mine = {r["code"]: r for r in primary["rates"]}
    far = 0
    for r in live["rates"]:
        other = mine.get(r["code"])
        if _shared_usable(r) and _shared_usable(other) \
                and abs(_sell_of(r) - _sell_of(other)) / _sell_of(other) >= DIVERGE_PCT:
            far += 1
    return far


def core_fingerprint(primary: dict, instruments: list[dict]) -> str:
    core = {i["code"] for i in instruments if i.get("bonbast_key") and not i.get("computed")}
    return rates_fingerprint([r for r in primary["rates"] if r["code"] in core])


def apply_live_first_guards(results: list[dict], now: float,
                            instruments: list[dict] | None = None) -> tuple[list[dict], int]:
    global _LIVE_STATE
    live = next((s for s in results if s["source"] == LIVE_NAME), None)
    primary = next((s for s in results if s["source"] == PRIMARY_NAME), None)
    if live is None or primary is None:
        return results, 0
    checked, replaced = check_divergence(live, primary)
    if checked is None:
        _note_block("diverge", None, now)
        _LIVE_RUN.update(outcome="blocked", kind="diverge")
        return [s for s in results if s is not live], 0
    frozen, _LIVE_STATE = live_guard.frozen_check(
        _LIVE_STATE, rates_fingerprint(live["rates"]),
        core_fingerprint(primary, instruments if instruments is not None else load_instruments()), now)
    if frozen:
        _note_block("frozen", None, now)
        _LIVE_RUN.update(outcome="blocked", kind="frozen")
        return [s for s in results if s is not live], 0
    if replaced:
        print(f"live: {replaced} row{'s' if replaced != 1 else ''} replaced", file=sys.stderr)
    return [checked if s is live else s for s in results], replaced


def rates_fingerprint(rates: list[dict]) -> str:
    values = {r["code"]: [r.get("buy"), r.get("sell"), r.get("price")] for r in rates}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]


def parse_converter_table(obj) -> dict | None:
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
    h = headers()
    h["x-requested-with"] = "XMLHttpRequest"
    h["accept"] = "application/json, text/javascript, */*; q=0.01"
    try:
        r = session.post(f"{BASE}/converter", headers=h, timeout=20)
        _classify(r)
        raw = r.json()
    except SourceBlocked as e:
        _note_block(e.kind, e.retry_after)
        print("converter: blocked", file=sys.stderr)
        return None
    except (requests.RequestException, ValueError, SourceError) as e:
        print(f"converter: {type(e).__name__}", file=sys.stderr)
        return None
    table = parse_converter_table(raw)
    if table is None:
        print("converter: /converter did not return a JSON object", file=sys.stderr)
        return None
    return table


def compute_cross_rates(table: dict, eur_buy, eur_sell, instruments: list[dict]) -> list[dict]:
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
    eur = next((r for r in direct_rates if r["code"] == "eur"), None)
    if eur is None or eur["buy"] is None or eur["sell"] is None:
        return []
    table = (fetcher or fetch_converter)(session)
    if table is None:
        return []
    return compute_cross_rates(table, eur["buy"], eur["sell"], instruments)


def merge_rates(direct_rates: list[dict], computed_rates: list[dict], instruments: list[dict]) -> list[dict]:
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
    daily = load_published(out, "v1/daily.json", SEALER)
    if isinstance(daily, dict) and isinstance(daily.get("codes"), dict) and isinstance(daily.get("start"), str):
        return daily
    return {"start": ARCHIVE_START, "codes": {}}


def archive_shrank(out: Path, daily: dict) -> tuple[int, int] | None:
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
    fetcher = fetcher or (lambda d: fetch_archive(session, d))
    fetched = 0
    previous = None
    identical_run = 0
    pending: list[tuple[str, dict]] = []
    for date in dates:
        try:
            shown, values = fetcher(date)
        except (requests.RequestException, SystemExit) as e:
            print(f"archive {date}: {type(e).__name__}", file=sys.stderr)
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


def write_long_history(out: Path, archive_file: Path, units: dict[str, int] | None = None) -> int:
    if not archive_file.exists():
        return 0
    try:
        data = json.loads(archive_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return 0
    units = units or {}
    written = 0
    for item in data:
        code = item.get("ab")
        unit = units.get(code, 1)
        pts = []
        for p in item.get("ps", []):
            price = p.get("sp") or p.get("bp")
            if code and price and p.get("ts"):
                pts.append({"date": p["ts"][:10], "price": float(price) * unit})
        pts.sort(key=lambda x: x["date"])
        if len(pts) >= 10:
            write(out / "v1" / "longhistory" / code, {"code": code, "days": len(pts), "points": pts, "source": "coarse-archive"})
            written += 1
    return written


PRIVACY_HTML = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Gheymat Privacy Policy</title>
<style>body{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;color:#111}
h1{font-size:28px}h2{font-size:18px;margin-top:28px}p,li{color:#333}footer{margin-top:48px;color:#777;font-size:13px}</style>
<h1>Gheymat Privacy Policy</h1>
<p>Last updated: 2026-11-08</p>
<p>Gheymat is an app for iPhone, Apple Watch and Android that shows Iranian free-market currency, gold and crypto
prices. This policy covers the Gheymat app on every platform, including its widgets.</p>
<h2>Data we collect</h2>
<p><strong>None.</strong> Gheymat has no user accounts, no sign-in, no analytics SDK, no advertising SDK, and no
crash-reporting SDK. The app does not know who you are and cannot identify you.</p>
<h2>Data stored on your device</h2>
<p>Your favourites, your chosen list/grid layout, your appearance and price-unit settings, your price alerts, and a
local cache of the latest prices are stored only in the app's local storage on your device. Home-screen widgets and
the Apple Watch app read the same on-device data. This data never leaves your device and is not visible to us.</p>
<h2>Notifications and permissions</h2>
<p>Price alerts are checked on your device and shown as local notifications; your alerts are never sent anywhere.
On Android the app asks for the notifications permission only when you create your first alert, and uses internet
access only to fetch prices.</p>
<h2>Network requests</h2>
<p>The app fetches currency, gold and crypto prices from Gheymat's own data feed. These requests carry no
account identifier, advertising identifier, or other data that identifies you. Standard network metadata (such
as your IP address) is visible to the hosting infrastructure the way it is for any web request, and is not
logged or retained by us in a way that is linked to you.</p>
<h2>Price data source</h2>
<p>Prices come from public Iranian market data. Gheymat is an independent app and is not affiliated with, endorsed
by, or operated by any market or exchange.</p>
<h2>Children</h2>
<p>Gheymat is not directed at children and does not knowingly collect data from anyone, including children,
because it does not collect data from anyone.</p>
<h2>Changes</h2>
<p>If this policy changes, the date above will change. Material changes will be reflected in the app's release
notes.</p>
<h2>Contact</h2>
<p>Questions about this policy: <a href="mailto:mohsen.rezaniaa75@gmail.com">mohsen.rezaniaa75@gmail.com</a></p>
<footer><a href="support.html">Support</a></footer>
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
<p>Daily history going back to 2018 is available for currencies. Gold, coins and crypto currently only have the
history the app itself has collected since you started using it; older daily history for those is on our
roadmap.</p>
<footer><a href="privacy.html">Privacy Policy</a></footer>
"""

INTRADAY_DAYS = 7
INTRADAY_REPAIRS = HERE / "intraday_repairs.json"


def _level(point) -> float | None:
    if not isinstance(point, dict):
        return None
    v = point.get("sell") or point.get("price") or point.get("buy")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def _utc_stamp(value) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{value!r} is not an ISO timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_repairs(path: Path | None = None) -> list[dict]:
    path = path or INTRADAY_REPAIRS
    try:
        if not path.exists():
            return []
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("not a JSON list")
        repairs = []
        for entry in entries:
            codes, factor = entry["codes"], entry.get("belowFactor")
            if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
                raise ValueError("codes must be a list of strings")
            if factor is not None and (isinstance(factor, bool) or not isinstance(factor, (int, float))
                                       or not factor > 0):
                raise ValueError("belowFactor must be a positive number")
            repairs.append({"codes": set(codes), "from": _utc_stamp(entry["from"]), "to": _utc_stamp(entry["to"]),
                            "belowFactor": factor})
        return repairs
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as e:
        print(f"intraday repairs: {path.name} ignored ({type(e).__name__}: {e})", file=sys.stderr)
        return []


def drop_repaired_points(code: str, points: list, reference: float | None, repairs: list[dict]) -> list:
    if not repairs:
        return points

    def repaired(p) -> bool:
        if not isinstance(p, dict):
            return False
        ts, level = str(p.get("ts", "")), _level(p)
        for e in repairs:
            if code not in e["codes"] or not e["from"] <= ts < e["to"]:
                continue
            if e["belowFactor"] is None:
                return True
            if level is not None and reference is not None and level * e["belowFactor"] < reference:
                return True
        return False
    return [p for p in points if not repaired(p)]


INTRADAY_MIN_GAP = 150


def _gap_seconds(newer: str, older) -> float | None:
    try:
        a = datetime.strptime(newer, "%Y-%m-%dT%H:%M:%SZ")
        b = datetime.strptime(str(older), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return (a - b).total_seconds()


def append_intraday(out: Path, snapshot: dict, observed: dict[str, str] | None = None,
                    live_stamp: str | None = None) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INTRADAY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repairs = [e for e in load_repairs() if e["to"] > cutoff]
    observed = observed or {}
    written = 0
    for r in snapshot["rates"]:
        if r.get("computed"):
            continue
        path = out / "v1" / "intraday" / r["code"]
        previous = load_published(out, f"v1/intraday/{r['code']}", SEALER)
        points = previous.get("points", []) if isinstance(previous, dict) else []
        if not isinstance(points, list):
            points = []
        sample = {"ts": observed.get(r["code"], snapshot["fetchedAt"]),
                  "buy": r["buy"], "sell": r["sell"], "price": r["price"]}
        kept = drop_repaired_points(r["code"], points, _level(sample), repairs)
        repaired, points = len(kept) != len(points), kept
        fresh = not points or str(points[-1].get("ts", "")) < sample["ts"]
        if fresh and points and live_stamp is not None and sample["ts"] == live_stamp:
            gap = _gap_seconds(sample["ts"], points[-1].get("ts", ""))
            fresh = gap is None or gap >= INTRADAY_MIN_GAP
        if not fresh and not repaired:
            continue
        points = [p for p in points if isinstance(p, dict) and p.get("ts", "") >= cutoff]
        if fresh:
            points.append(sample)
        write(path, {"code": r["code"], "days": INTRADAY_DAYS, "points": points})
        written += 1
    return written


SEALER = None
PLAIN_ALSO = True


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write(path: Path, obj) -> None:
    if PLAIN_ALSO or SEALER is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    elif path.exists():
        path.unlink()
    if SEALER is not None:
        root = _dist_root(path)
        logical = path.relative_to(root).as_posix()
        sealed = root / SEALER.opaque_path(logical)
        sealed.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(sealed, json.dumps(SEALER.seal(logical, obj), separators=(",", ":")))


_DIST_ROOT: Path | None = None


def _dist_root(path: Path) -> Path:
    if _DIST_ROOT is not None:
        return _DIST_ROOT
    for parent in path.parents:
        if parent.name == "v1":
            return parent.parent
    return path.parent


def news_only(out: Path) -> int:
    global SEALER, PLAIN_ALSO, _DIST_ROOT
    _DIST_ROOT = out
    SEALER = Sealer.from_env()
    PLAIN_ALSO = os.environ.get("GHEYMAT_PLAIN", "1") == "1"
    if SEALER is None:
        print("news: no sealing keys; nothing to refresh", file=sys.stderr)
        return 4
    before = gheymat_news.last_check(load_published(out, gheymat_news.LOGICAL, SEALER))
    try:
        gheymat_news.publish(lambda logical, obj: write(out / logical, obj),
                             lambda logical: load_published(out, logical, SEALER), archive_root=out)
        after = gheymat_news.last_check(load_published(out, gheymat_news.LOGICAL, SEALER))
    except Exception as e:
        print(f"news: refresh failed ({type(e).__name__})", file=sys.stderr)
        return 5
    print("news: refreshed" if after is not None and (before is None or after > before) else "news: unchanged")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--history", action="store_true", help="fill missing recent days from the archive and rewrite v1/history/*")
    ap.add_argument("--backfill", type=int, default=0, help="also fetch N older archive days (chunked backfill to 2012-10-09)")
    ap.add_argument("--pace", type=float, default=2.5, help="seconds between archive requests")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--ai", action="store_true", help="also publish the Pro AI documents (v1/ai/*); never blocks prices")
    ap.add_argument("--mark", action="store_true", help="print the primary source's newest observation time and exit")
    ap.add_argument("--defer-news", action="store_true", help="re-seal the published news without refreshing it")
    ap.add_argument("--news-only", action="store_true", help="refresh only the news document in --out and exit")
    args = ap.parse_args()
    if args.mark:
        mark = hansha_mark(fetch_hansha(requests.Session()))
        if mark is None:
            return 1
        print(mark)
        return 0
    if args.news_only:
        return news_only(Path(args.out))
    global _LIVE_STATE
    state_path = os.environ.get("GHEYMAT_LIVE_STATE")
    _LIVE_STATE = live_guard.load_state(state_path, time.time())
    try:
        return _publish(args)
    finally:
        live_guard.save_state(state_path, _LIVE_STATE)


def collect_planned(session, instruments: list[dict], now: float, quiet: bool) -> tuple[list[dict], bool]:
    live_first = live_first_active(now)
    _LIVE_RUN.update(outcome=None, kind=None)
    order = plan_sources(now, _LIVE_STATE)
    results = collect_sources(session, instruments, order)
    if quiet and LIVE_NAME not in order:
        probe, _, _ = combine_sources(results, instruments)
        if len(probe["rates"]) < MIN_DIRECT:
            wider = plan_sources(now, _LIVE_STATE, primary_short=True)
            extra = [n for n in wider if n not in order]
            if extra:
                results = results + collect_sources(session, instruments, extra)
                rank = {n: i for i, n in enumerate(wider)}
                results.sort(key=lambda s: rank.get(s["source"], len(rank)))
    return results, live_first


def _publish(args) -> int:
    out = Path(args.out)
    global SEALER, PLAIN_ALSO, _DIST_ROOT
    _DIST_ROOT = out
    SEALER = Sealer.from_env()
    PLAIN_ALSO = os.environ.get("GHEYMAT_PLAIN", "1") == "1"
    print("sealed channel:", "on" if SEALER else "off (no keys)", "| plain files:", "on" if PLAIN_ALSO or SEALER is None else "off")
    instruments = load_instruments()
    session = requests.Session()
    now = time.time()
    quiet = live_first_active(now) and live_guard.is_quiet(_LIVE_STATE, now)
    results, live_first = collect_planned(session, instruments, now, quiet)
    if live_first:
        results, _ = apply_live_first_guards(results, now, instruments)
    else:
        pair = {x["source"]: x for x in results}
        if LIVE_NAME in pair and PRIMARY_NAME in pair:
            print(f"live: {count_apart(pair[LIVE_NAME], pair[PRIMARY_NAME])} codes "
                  f"{round(DIVERGE_PCT * 100)}% apart", file=sys.stderr)
    live_snap = next((s for s in results if s["source"] == LIVE_NAME), None)
    if live_snap is not None:
        _note_clean()
        print(live_guard.status_line("ok", fp=rates_fingerprint(live_snap["rates"])))
    elif _LIVE_RUN["outcome"] is not None:
        print(live_guard.status_line(_LIVE_RUN["outcome"], _LIVE_RUN["kind"]))
    elif quiet:
        print(live_guard.status_line("quiet"))
    snapshot, counts, observed = combine_sources(results, instruments, live_first=live_first)
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
        computed_rates = [] if quiet else fetch_computed_rates(session, snapshot["rates"], instruments)
    except (ValueError, OverflowError, ArithmeticError) as e:
        print(f"converter: unexpected error computing cross-rates: {e}", file=sys.stderr)
        computed_rates = []
    snapshot["rates"] = merge_rates(snapshot["rates"], computed_rates, instruments)
    write(out / "v1" / "latest", snapshot)
    write(out / "v1" / "instruments", instruments)
    (out / "privacy.html").write_text(PRIVACY_HTML, encoding="utf-8")
    (out / "support.html").write_text(SUPPORT_HTML, encoding="utf-8")
    print(f"latest: {len(snapshot['rates'])} rates ({' + '.join(str(v) for v in counts.values())} + {len(computed_rates)} computed), "
          f"observed {snapshot['fetchedAt']}, "
          f"fp {fingerprint}")
    print(f"intraday: {append_intraday(out, snapshot, observed, live_snap["fetchedAt"] if (live_first and live_snap) else None)} files updated")
    if args.history or args.backfill:
        dates = recent_missing_dates(daily, 7) if args.history else []
        if args.backfill and not quiet:
            dates += backfill_dates(daily, args.backfill)
        dates = [] if quiet else list(dict.fromkeys(dates))
        fetched = fill_days(session, daily, dates, args.pace)
        save_daily(out, daily)
        files = write_history_files(out, daily)
        long_files = write_long_history(out, HERE.parent / "archive" / "all.json",
                                        {i["code"]: i["unit"] for i in instruments})
        have = known_dates(daily)
        print(f"history: fetched {fetched} archive days, {files} history files, {long_files} long-history files, "
              f"coverage {min(have) if have else '-'} .. {max(have) if have else '-'} ({len(have)} days)")
    if args.ai:
        gheymat_ai.run_step(daily, lambda logical, obj: write(out / logical, obj),
                            lambda logical: load_published(out, logical, SEALER),
                            signals_http=requests.Session(), archive_root=out,
                            refresh_news=not args.defer_news)
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
