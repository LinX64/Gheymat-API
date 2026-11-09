"""Pro AI feed step of the publisher (Gheymat CONTRACT.md "AI feed"): news, forecast documents and the brief."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import gheymat_forecast as fc
import gheymat_news

TEHRAN = timezone(timedelta(hours=3, minutes=30))
BUDGET_SECONDS = 120.0
BRIEF_NEWS_CARDS = 3
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def tehran_today(now: datetime):
    return now.astimezone(TEHRAN).date()


def default_today(now: datetime | None = None):
    return tehran_today(now or datetime.now(timezone.utc))


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
            budget_seconds: float = BUDGET_SECONDS, clock=time.monotonic, news_ids=()) -> dict:
    now = now or datetime.now(timezone.utc)
    started = clock()
    today = default_today(now)
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
    cards = [{"kind": "forecast", "code": c} for c in published] + [{"kind": "news", "id": i} for i in list(news_ids)[:BRIEF_NEWS_CARDS]]
    brief = {"generatedAt": generated_at, "en": en, "fa": fa, "cards": cards, "forecastCodes": published}
    if isinstance(previous_brief, dict) and all(previous_brief.get(k) == brief[k] for k in ("en", "fa", "cards", "forecastCodes")):
        brief = previous_brief
    write_doc("v1/ai/brief", brief)
    return {"published": published, "rebuilt": rebuilt, "resealed": resealed, "withheld": withheld}


def run_news(write_doc, load_doc, now: datetime | None = None, log=print, env=None, http=None) -> list[str]:
    try:
        news = gheymat_news.publish(write_doc, load_doc, now, env=env, http=http, log=log)
    except Exception as e:
        log(f"ai: news step failed, forecasts unaffected: {type(e).__name__}")
        return []
    if not news:
        return []
    if news["skipped"]:
        log(f"ai: news {len(news['ids'])} items re-sealed")
    else:
        log(f"ai: news {len(news['ids'])} items ({news['new']} new, {news['dropped']} dropped, "
            f"{news['in']} in / {news['out']} out tokens)")
    return news["ids"]


def run_step(daily: dict, write_doc, load_doc, now: datetime | None = None, log=print, env=None, http=None) -> dict | None:
    news_ids = run_news(write_doc, load_doc, now, log, env, http)
    try:
        summary = publish(daily, write_doc, load_doc, now, news_ids=news_ids)
    except Exception as e:
        log(f"ai: step failed, prices unaffected: {type(e).__name__}: {e}")
        return None
    log(f"ai: {len(summary['published'])} forecasts ({summary['rebuilt']} rebuilt, {summary['resealed']} re-sealed), "
        f"{len(summary['withheld'])} withheld")
    return summary
