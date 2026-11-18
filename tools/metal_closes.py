from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

NAME = "metal_closes"
CODES = ("gram", "mithqal", "ounce", "emami", "azadi", "half", "quarter", "gerami")
KINDS = ("gold", "coin")
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _price(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def tehran_day(now: datetime) -> str:
    return now.astimezone(TEHRAN).date().isoformat()


def live_values(rates) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rates if isinstance(rates, list) else []:
        if not isinstance(r, dict) or r.get("code") not in CODES or r.get("kind") not in KINDS:
            continue
        if r["kind"] == "coin":
            buy, sell = r.get("buy"), r.get("sell")
            if _price(sell) or _price(buy):
                out[r["code"]] = {"buy": int(round(buy)) if _price(buy) else None,
                                  "sell": int(round(sell)) if _price(sell) else None}
        elif _price(r.get("price")):
            out[r["code"]] = {"price": float(r["price"])}
    return out


def point(day: str, value: dict) -> dict | None:
    if "price" in value:
        return {"date": day, "price": value["price"]} if _price(value["price"]) else None
    buy, sell = value.get("buy"), value.get("sell")
    price = sell if _price(sell) else buy
    if not _price(price):
        return None
    return {"date": day, "price": float(price), "buy": buy, "sell": sell}


def record_today(store, state_dir, rates, now: datetime, log=print) -> None:
    values = live_values(rates)
    if not values:
        return
    day = tehran_day(now)
    existing = {r["date"]: r for r in store.load(state_dir, NAME, log)}
    codes = dict((existing.get(day) or {}).get("codes") or {})
    codes.update(values)
    store.append(state_dir, NAME, {"date": day, "codes": codes}, log)


def closed_points(records, today: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {c: [] for c in CODES}
    for rec in sorted((r for r in records if r.get("date", "") < today), key=lambda r: r["date"]):
        for code, value in (rec.get("codes") or {}).items():
            if code in out and isinstance(value, dict):
                p = point(rec["date"], value)
                if p is not None:
                    out[code].append(p)
    return out


def run(state_dir, rates, now: datetime, load_doc, write_doc, log=print, store=None, known=()) -> int:
    if not state_dir:
        return 0
    try:
        if store is None:
            import archive_store as store
        import crypto_history
        record_today(store, state_dir, rates, now, log)
        today = tehran_day(now)
        written = 0
        for code, points in closed_points(store.load(state_dir, NAME, log), today).items():
            if not points or code in known:
                continue
            logical = f"v1/history/{code}"
            old = load_doc(logical)
            old_points = old.get("points") if isinstance(old, dict) else None
            merged = crypto_history.merge_points(old_points, points)
            if old_points == merged:
                continue
            write_doc(logical, {"code": code, "days": len(merged), "points": merged})
            written += 1
        return written
    except Exception as e:
        log(f"history: gold and coin closes skipped: {type(e).__name__}")
        return 0
