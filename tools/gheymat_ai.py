"""Pro AI feed step of the publisher (Gheymat CONTRACT.md "AI feed"): forecast documents and the brief."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import gheymat_forecast as fc

TEHRAN = timezone(timedelta(hours=3, minutes=30))
BUDGET_SECONDS = 120.0
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def tehran_today(now: datetime):
    return now.astimezone(TEHRAN).date()


def iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def points_from_series(series: dict) -> list[dict]:
    points = []
    for day in sorted(series):
        buy, sell = series[day]
        price = sell if sell is not None else buy
        if price:
            points.append({"date": day, "price": float(price)})
    return points


def brief_text(count: int) -> tuple[str, str]:
    en = f"Next-week estimates are ready for {count} currencies."
    fa = f"برآورد هفته بعد برای {count} ارز آماده است.".translate(FA_DIGITS)
    return en, fa


def publish(daily: dict, write_doc, load_doc, now: datetime | None = None,
            budget_seconds: float = BUDGET_SECONDS, clock=time.monotonic) -> dict:
    now = now or datetime.now(timezone.utc)
    started = clock()
    today = tehran_today(now)
    generated_at = iso(now)
    published, rebuilt, resealed, withheld = [], 0, 0, {}
    for code in sorted(daily.get("codes", {})):
        if clock() - started > budget_seconds:
            withheld[code] = "budget"
            continue
        points = points_from_series(daily["codes"][code])
        if not points:
            continue
        logical = f"v1/ai/forecast/{code}"
        previous = load_doc(logical)
        last = points[-1]
        fresh = fc.basis_is_fresh(fc.date.fromisoformat(last["date"]), today)
        if (fresh and isinstance(previous, dict) and previous.get("method") == fc.METHOD
                and previous.get("basis") == {"date": last["date"], "price": last["price"]}):
            write_doc(logical, previous)
            published.append(code)
            resealed += 1
            continue
        doc, reason = fc.build_forecast(code, points, today, generated_at, history_close=last)
        if doc is None:
            withheld[code] = reason
            continue
        write_doc(logical, doc)
        published.append(code)
        rebuilt += 1
    en, fa = brief_text(len(published))
    previous_brief = load_doc("v1/ai/brief")
    cards = [{"kind": "forecast", "code": c} for c in published]
    brief = {"generatedAt": generated_at, "en": en, "fa": fa, "cards": cards, "forecastCodes": published}
    if isinstance(previous_brief, dict) and all(previous_brief.get(k) == brief[k] for k in ("en", "fa", "cards", "forecastCodes")):
        brief = previous_brief
    write_doc("v1/ai/brief", brief)
    return {"published": published, "rebuilt": rebuilt, "resealed": resealed, "withheld": withheld}


def run_step(daily: dict, write_doc, load_doc, now: datetime | None = None, log=print) -> dict | None:
    try:
        summary = publish(daily, write_doc, load_doc, now)
    except Exception as e:
        log(f"ai: step failed, prices unaffected: {type(e).__name__}: {e}")
        return None
    log(f"ai: {len(summary['published'])} forecasts ({summary['rebuilt']} rebuilt, {summary['resealed']} re-sealed), "
        f"{len(summary['withheld'])} withheld")
    return summary
