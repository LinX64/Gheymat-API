from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import archive_store
import forecast_confidence
import forecast_track
import gheymat_blend
import gheymat_forecast as fc
import gheymat_news
import gheymat_signals
import news_archive
import signal_shadow

TEHRAN = timezone(timedelta(hours=3, minutes=30))
BUDGET_SECONDS = 120.0
BRIEF_NEWS_CARDS = 3
CARD_PRIORITY = ("usd", "eur", "gram", "emami", "gbp", "aed", "try", "usdt", "btc")
SHARP_MOVE = 0.03
WEEK_ENTRIES = 7
USD_SENTENCES = {
    "record": ("The dollar closed at a record high.", "دلار در بالاترین قیمت پایانی خود بسته شد."),
    "rose": ("The dollar rose sharply this week.", "دلار این هفته به‌شدت بالا رفت."),
    "fell": ("The dollar fell sharply this week.", "دلار این هفته به‌شدت پایین آمد."),
}
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


def last_change(points: list[dict]) -> float:
    if len(points) < 2 or not points[-2]["price"]:
        return 0.0
    return abs(points[-1]["price"] - points[-2]["price"]) / points[-2]["price"]


def card_order(codes: list[str], changes: dict) -> list[str]:
    fixed = [c for c in CARD_PRIORITY if c in codes]
    rest = sorted((c for c in codes if c not in CARD_PRIORITY), key=lambda c: (-changes.get(c, 0.0), c))
    return fixed + rest


def usd_move(points: list[dict]) -> str | None:
    if len(points) < 2:
        return None
    prices = [p["price"] for p in points]
    last = prices[-1]
    if last > max(prices[:-1]):
        return "record"
    if len(prices) > WEEK_ENTRIES:
        earlier = prices[-1 - WEEK_ENTRIES]
        if last >= earlier * (1 + SHARP_MOVE):
            return "rose"
        if last <= earlier * (1 - SHARP_MOVE):
            return "fell"
    return None


def publish(daily: dict, write_doc, load_doc, now: datetime | None = None,
            budget_seconds: float = BUDGET_SECONDS, clock=time.monotonic, news_ids=(), signal_ctx=None,
            archive_root=None, log=print, live_prices=None, env=None) -> dict:
    now = now or datetime.now(timezone.utc)
    started = clock()
    today = default_today(now)
    generated_at = iso(now)
    published, rebuilt, resealed, withheld, changes = [], 0, 0, {}, {}
    accepted = gheymat_blend.expected_methods(signal_ctx)
    track_state = forecast_track.open_state(archive_root, log, env)
    for code in sorted(daily.get("codes", {})):
        if clock() - started > budget_seconds:
            withheld[code] = "budget"
            continue
        points = points_from_series(daily["codes"][code])
        if not points:
            continue
        changes[code] = last_change(points)
        logical = f"v1/ai/forecast/{code}"
        previous = load_doc(logical)
        last = points[-1]
        fresh = fc.basis_is_fresh(fc.date.fromisoformat(last["date"]), today)
        if (fresh and isinstance(previous, dict) and previous.get("method") in accepted
                and previous.get("basis") == {"date": last["date"], "price": last["price"]}):
            live = (live_prices or {}).get(code)
            confidence = forecast_confidence.safe_confidence(previous, live, previous, log)
            reused = previous
            if confidence is not None and confidence != previous.get("confidence"):
                reused = {**previous, "confidence": confidence}
            write_doc(logical, reused)
            forecast_track.record_forecast(track_state, reused, log)
            published.append(code)
            resealed += 1
            continue
        doc, reason = fc.build_forecast(code, points, today, generated_at, history_close=last, signal_ctx=signal_ctx)
        if doc is None:
            withheld[code] = reason
            continue
        doc["track"] = forecast_track.build_track(track_state, code, points, previous, log)
        confidence = forecast_confidence.safe_confidence(doc, (live_prices or {}).get(code), previous, log)
        doc["confidence"] = confidence if confidence is not None else {"level": "normal", "reasons": []}
        write_doc(logical, doc)
        forecast_track.record_forecast(track_state, doc, log)
        published.append(code)
        rebuilt += 1
    forecast_track.flush(track_state, log)
    en, fa = brief_text(len(published))
    move = usd_move(points_from_series(daily.get("codes", {}).get("usd", {})))
    if move:
        en, fa = f"{USD_SENTENCES[move][0]} {en}", f"{USD_SENTENCES[move][1]} {fa}"
    previous_brief = load_doc("v1/ai/brief")
    cards = [{"kind": "forecast", "code": c} for c in card_order(published, changes)] + [{"kind": "news", "id": i} for i in list(news_ids)[:BRIEF_NEWS_CARDS]]
    brief = {"generatedAt": generated_at, "en": en, "fa": fa, "cards": cards, "forecastCodes": published}
    if isinstance(previous_brief, dict) and all(previous_brief.get(k) == brief[k] for k in ("en", "fa", "cards", "forecastCodes")):
        brief = previous_brief
    write_doc("v1/ai/brief", brief)
    return {"published": published, "rebuilt": rebuilt, "resealed": resealed, "withheld": withheld}


def signal_context(http, archive_root, now: datetime | None = None, log=print):
    try:
        today = default_today(now)
        series = gheymat_signals.load_signals(http, today, log)
        records = archive_store.load(archive_root, news_archive.NAME, log) if archive_root is not None else []
        ctx = gheymat_blend.Context(series, today, records)
    except Exception as e:
        log(f"ai: signals unavailable, baseline only: {type(e).__name__}")
        return None
    return ctx if (ctx.obs or ctx.news) else None


def run_news(write_doc, load_doc, now: datetime | None = None, log=print, env=None, http=None, archive_root=None,
             refresh_news: bool = True) -> list[str]:
    try:
        news = gheymat_news.publish(write_doc, load_doc, now, env=env, http=http, log=log, archive_root=archive_root,
                                     refresh=refresh_news)
    except Exception as e:
        log(f"ai: news step failed, forecasts unaffected: {type(e).__name__}")
        try:
            kept = gheymat_news.reseal(write_doc, load_doc(gheymat_news.LOGICAL), now or datetime.now(timezone.utc))
        except Exception:
            kept = None
        return kept["ids"] if kept else []
    if not news:
        return []
    if news["skipped"]:
        log(f"ai: news {len(news['ids'])} items re-sealed")
    else:
        log(f"ai: news {len(news['ids'])} items ({news['new']} new, {news['dropped']} dropped, "
            f"{news['in']} in / {news['out']} out tokens)")
    return news.get("top") or news["ids"]


SIGNALS_ENABLED = False


def shadow_signals(daily, signals_http, archive_root, now, log, env) -> None:
    flags = env if env is not None else os.environ
    if SIGNALS_ENABLED or signals_http is None or flags.get("GHEYMAT_SIGNAL_SHADOW") != "1":
        return
    try:
        ctx = signal_context(signals_http, archive_root, now, log)
        if ctx is not None:
            log(signal_shadow.line(signal_shadow.score(daily, ctx)))
    except Exception as e:
        log(f"ai: signal shadow skipped: {type(e).__name__}")


def run_step(daily: dict, write_doc, load_doc, now: datetime | None = None, log=print, env=None, http=None,
             signals_http=None, archive_root=None, refresh_news: bool = True, live_prices=None) -> dict | None:
    news_ids = run_news(write_doc, load_doc, now, log, env, http, archive_root, refresh_news)
    state_dir = (os.environ if env is None else env).get("GHEYMAT_STATE_DIR") or None
    try:
        import news_days
        news_days.update(write_doc, load_doc, state_dir, load_doc(gheymat_news.LOGICAL),
                         now or datetime.now(timezone.utc), log)
    except Exception as e:
        log(f"ai: news archive skipped: {type(e).__name__}")
    signal_ctx = signal_context(signals_http, archive_root, now, log) if SIGNALS_ENABLED and signals_http is not None else None
    try:
        summary = publish(daily, write_doc, load_doc, now, news_ids=news_ids, signal_ctx=signal_ctx,
                          archive_root=state_dir, log=log, live_prices=live_prices, env=env)
    except Exception as e:
        log(f"ai: step failed, prices unaffected: {type(e).__name__}")
        return None
    shadow_signals(daily, signals_http, archive_root, now, log, env)
    log(f"ai: {len(summary['published'])} forecasts ({summary['rebuilt']} rebuilt, {summary['resealed']} re-sealed), "
        f"{len(summary['withheld'])} withheld")
    return summary
