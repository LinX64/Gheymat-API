from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

PAIRS = {"btc": "XBTUSD", "eth": "ETHUSD", "xrp": "XRPUSD", "bch": "BCHUSD", "ltc": "LTCUSD", "usdt": "USDTUSD"}
OKX_IDS = {"bnb": "BNB-USDT"}
DAY, WEEK = 1440, 10080
OKX_PAGES = 10
FRESH_DAYS = 1


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def parse_kraken(payload) -> list[tuple[str, float]]:
    try:
        if payload.get("error"):
            return []
        rows = next(v for k, v in payload["result"].items() if k != "last")
        out = [(_date(r[0]), float(r[4])) for r in rows]
    except (AttributeError, KeyError, StopIteration, TypeError, ValueError, IndexError, OverflowError, OSError):
        return []
    return [p for p in out if p[1] > 0]


def parse_okx(payload) -> list[tuple[str, float]]:
    try:
        rows = payload["data"]
        out = [(_date(int(r[0]) / 1000), float(r[4])) for r in rows if str(r[8]) == "1"]
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, OSError):
        return []
    return [p for p in out if p[1] > 0]


def usd_close(daily: dict, date: str):
    pair = daily.get("codes", {}).get("usd", {}).get(date)
    if not pair:
        return None
    buy, sell = pair
    return sell if sell is not None else buy


def to_points(rows, quote: str, daily: dict, today: str) -> list[dict]:
    points = {}
    for date, close in rows:
        if date >= today:
            continue
        if quote == "usd":
            price = round(close, 2)
        else:
            rate = usd_close(daily, date)
            if not rate:
                continue
            price = float(round(close * rate))
        points[date] = {"date": date, "price": price, "buy": None, "sell": None}
    return [points[d] for d in sorted(points)]


def weekly_points(rows, quote: str, daily: dict, before: str) -> list[dict]:
    dated = [((datetime.fromisoformat(d).date() + timedelta(days=6)).isoformat(), c) for d, c in rows]
    pts = to_points(dated, quote, daily, "9999-12-31")
    return [{"date": p["date"], "price": p["price"]} for p in pts if p["date"] < before]


def merge_points(existing, new) -> list[dict]:
    merged = {p["date"]: p for p in new}
    merged.update({p["date"]: p for p in existing or [] if isinstance(p, dict) and "date" in p})
    return [merged[d] for d in sorted(merged)]


def _get(session, url, params):
    try:
        r = session.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def fetch_kraken(session, pair: str, interval: int, pace: float):
    time.sleep(pace)
    return parse_kraken(_get(session, "https://api.kraken.com/0/public/OHLC", {"pair": pair, "interval": interval}))


def fetch_okx(session, inst: str, pace: float):
    rows, after = [], None
    for _ in range(OKX_PAGES):
        time.sleep(pace)
        params = {"instId": inst, "bar": "1Dutc", "limit": 100}
        if after:
            params["after"] = after
        payload = _get(session, "https://www.okx.com/api/v5/market/history-candles", params)
        try:
            data = payload["data"]
            after = data[-1][0]
        except (KeyError, TypeError, IndexError):
            break
        rows += parse_okx(payload)
        if len(data) < 100:
            break
    return rows


def is_fresh(existing, today: str) -> bool:
    try:
        last = max(p["date"] for p in existing["points"])
    except (KeyError, TypeError, ValueError):
        return False
    return last >= (datetime.fromisoformat(today).date() - timedelta(days=FRESH_DAYS)).isoformat()


def run(session, instruments, daily, load, write, today: str | None = None, pace: float = 0.5) -> int:
    today = today or datetime.now(timezone.utc).date().isoformat()
    written = 0
    for inst in instruments:
        code, quote = inst["code"], inst["quote"]
        if inst.get("kind") != "crypto" or (code not in PAIRS and code not in OKX_IDS):
            continue
        old = load(f"v1/history/{code}")
        if is_fresh(old, today):
            continue
        weekly = []
        if code in PAIRS:
            days = fetch_kraken(session, PAIRS[code], DAY, pace)
            weekly = fetch_kraken(session, PAIRS[code], WEEK, pace)
        else:
            days = fetch_okx(session, OKX_IDS[code], pace)
        points = to_points(days, quote, daily, today)
        if not points:
            continue
        points = merge_points((old or {}).get("points"), points)
        write(f"v1/history/{code}", {"code": code, "days": len(points), "points": points})
        long_old = load(f"v1/longhistory/{code}")
        coarse = weekly_points(weekly, quote, daily, points[0]["date"])
        coarse = merge_points((long_old or {}).get("points"), coarse)
        if coarse:
            write(f"v1/longhistory/{code}", {"code": code, "days": len(coarse), "points": coarse, "source": "coarse-archive"})
        written += 1
    return written
