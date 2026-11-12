import importlib.util
import math
import pathlib
import random
import sys
from datetime import date, timedelta

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gheymat_blend as gb
import gheymat_forecast as fc
import gheymat_signals as gs

END = date(2026, 11, 8)
TODAY = date(2026, 11, 9)
NOW = "2026-11-09T06:00:00Z"
YEARS = 12


def obs_walk(seed, start, end, sigma=0.004, base=100.0):
    rng = random.Random(seed)
    out, v, d = [], base, start
    while d <= end:
        v *= math.exp(rng.gauss(0.0, sigma))
        out.append((d, v))
        d += timedelta(days=1)
    return out


def prices(seed, obs, coef, sigma=0.008, vol_coef=0.0):
    rng = random.Random(seed)
    lag = gs.MIN_LAG_DAYS["usd"]
    start = END - timedelta(days=YEARS * 365)
    price, d, points = 50000.0, start, []
    while d <= END:
        if d.weekday() != fc.FRIDAY:
            f = gs.weekly_change(obs, d - timedelta(days=1), lag) or 0.0
            s = sigma * (1 + vol_coef * abs(f))
            price *= math.exp(rng.gauss(0.0, s) + coef * f)
            points.append({"date": d.isoformat(), "price": round(price, 2)})
        d += timedelta(days=1)
    return points


def ctx_for(obs, key="usd", news=None):
    return gb.Context({key: obs}, TODAY, news)


def obs_for():
    return obs_walk(11, END - timedelta(days=YEARS * 365 + 60), END)


def test_signal_that_helps_passes_and_populates_signals():
    obs = obs_for()
    points = prices(5, obs, coef=0.003)
    doc, reason = fc.build_forecast("usd", points, TODAY, NOW, signal_ctx=ctx_for(obs))
    assert reason is None
    assert doc["method"] == "filtered-quantile-v1+usd"
    assert len(doc["signals"]) == 1
    sig = doc["signals"][0]
    assert sig["key"] == "usd" and sig["trend"] in ("up", "down", "flat")
    assert isinstance(sig["change"], float) and round(sig["change"], 1) == sig["change"]
    assert sig["reason"]["en"].startswith("US dollar index ") and sig["reason"]["en"].endswith("% this week")
    assert sig["reason"]["fa"]
    assert gb.INTERVAL_SCORE_MARGIN > 0
    assert doc["backtestWeeks"] >= fc.MIN_BACKTEST_WEEKS
    assert fc.COVERAGE_ALL[0] <= doc["coverage"] <= fc.COVERAGE_ALL[1]
    assert 0 < doc["low"] <= doc["likely"] <= doc["high"]


def test_variant_metrics_beat_baseline_on_the_gate():
    obs = obs_for()
    points = prices(5, obs, coef=0.003)
    series = fc.Series(fc.clean_series(points))
    returns = series.horizon_returns()
    best = gb.best_variant("usd", series, returns, ctx_for(obs))
    assert best["name"] == "drift-by-usd-move"
    m = best["metrics"]
    assert m["reasons"] == []
    assert m["improvement"] >= gb.INTERVAL_SCORE_MARGIN
    assert m["medianErr"] <= m["baselineMedianErr"]
    assert m["alignedWeeks"] >= fc.MIN_BACKTEST_WEEKS


def test_noise_signal_stays_out_and_doc_matches_baseline():
    obs = obs_for()
    points = prices(5, obs, coef=0.0)
    base, r1 = fc.build_forecast("usd", points, TODAY, NOW)
    doc, r2 = fc.build_forecast("usd", points, TODAY, NOW, signal_ctx=ctx_for(obs))
    assert r1 is None and r2 is None
    assert doc == base
    assert doc["signals"] == [] and doc["method"] == fc.METHOD


def test_too_little_history_stays_out():
    obs = obs_for()
    short = [o for o in obs if o[0] >= END - timedelta(days=60)]
    points = prices(5, obs, coef=0.003)
    base, _ = fc.build_forecast("usd", points, TODAY, NOW)
    doc, _ = fc.build_forecast("usd", points, TODAY, NOW, signal_ctx=ctx_for(short))
    assert doc == base


def test_news_without_enough_archive_is_skipped():
    obs = obs_for()
    news = [{"date": (END - timedelta(days=i)).isoformat(), "up": 5, "down": 1, "none": 1, "total": 7} for i in range(30)]
    ctx = gb.Context({"usd": obs}, TODAY, news)
    assert ctx.has("news") is False
    series = fc.Series(fc.clean_series(prices(5, obs, coef=0.0)))
    best = gb.best_variant("usd", series, series.horizon_returns(), ctx)
    assert best["report"]["vol-scale-by-news-shock"]["reasons"] == ["no-signal"]
    assert best["name"] == "baseline"


def test_signal_join_ignores_observations_newer_than_basis_minus_lag():
    obs = obs_for()
    ctx = ctx_for(obs)
    lag = ctx.lags["usd"]
    basis = date(2024, 5, 14)
    before = ctx.feature("usd", basis)
    cutoff = basis - timedelta(days=lag)
    spiked = [(d, v * 9.0 if d > cutoff else v) for d, v in obs]
    after = ctx_for(spiked).feature("usd", basis)
    assert before is not None and before == after
    known = gs.value_known_at(spiked, basis, lag)
    assert known[0] <= cutoff


def test_variant_bands_do_not_depend_on_future_signal_or_prices():
    obs = obs_for()
    points = prices(5, obs, coef=0.003)
    basis = date(2023, 3, 1)
    while basis.weekday() == fc.FRIDAY:
        basis += timedelta(days=1)
    spec = next(v for v in gb.VARIANTS if v["signal"] == "usd")

    def band(points_, obs_):
        series = fc.Series(fc.clean_series(points_))
        ev = gb._Evaluator(spec, ctx_for(obs_), series.horizon_returns(), "fhs", {})
        return ev.band(basis, series.sigma_at(basis))[0]

    cut = basis.isoformat()
    pert_points = [p if p["date"] <= cut else {"date": p["date"], "price": p["price"] * 3.1} for p in points]
    pert_obs = [(d, v if d <= basis else v * 4.0) for d, v in obs]
    assert band(points, obs) is not None
    assert band(points, obs) == band(pert_points, pert_obs)


def test_gate_rejections():
    base = {"coverage": 0.8, "coverageRecent": 0.8, "meanIntervalScore": 0.05, "medianErr": 0.01, "n": 200}
    good = dict(base, meanIntervalScore=0.04, medianErr=0.0099)
    ok, m = gb.gate(base, good, 200)
    assert ok and m["reasons"] == []
    assert gb.gate(base, good, 50)[1]["reasons"] == ["weeks"]
    assert "margin" in gb.gate(base, dict(good, meanIntervalScore=0.0499), 200)[1]["reasons"]
    assert "median-error" in gb.gate(base, dict(good, medianErr=0.011), 200)[1]["reasons"]
    assert "calibration" in gb.gate(base, dict(good, coverage=0.9), 200)[1]["reasons"]
    assert "calibration-recent" in gb.gate(base, dict(good, coverageRecent=0.6), 200)[1]["reasons"]
    assert "no-score" in gb.gate(base, dict(good, meanIntervalScore=None), 200)[1]["reasons"]


def test_signal_entry_text():
    spec = next(v for v in gb.VARIANTS if v["signal"] == "oil")
    e = gb.signal_entry(spec, 2.44)
    assert e == {"key": "oil", "trend": "up", "change": 2.4,
                 "reason": {"en": "Brent +2.4% this week", "fa": "برنت این هفته ۲٫۴٪ افزایش یافت"}}
    assert gb.signal_entry(spec, -0.2)["trend"] == "flat"
    assert gb.signal_entry(spec, -3.0)["trend"] == "down"


def test_expected_methods_and_no_context_default():
    assert gb.expected_methods(None) == {fc.METHOD}
    obs = obs_for()
    assert gb.expected_methods(ctx_for(obs)) == {fc.METHOD, fc.METHOD + "+usd"}


def test_vol_fit_widens_only_when_shocks_are_wilder():
    rng = random.Random(3)
    xs = [rng.uniform(-5, 5) for _ in range(800)]
    wild = [rng.gauss(0, 1 + 2 * (abs(x) > 3.75)) for x in xs]
    calm = [rng.gauss(0, 1) for _ in xs]
    idx = list(range(len(xs)))
    fit = gb._fit_vol({"x": xs, "y": wild}, idx)
    assert fit is not None and 1.0 < fit[1] <= gb.MAX_SCALE
    quiet = gb._fit_vol({"x": xs, "y": calm}, idx)
    assert quiet is None or quiet[1] < 1.15
    assert gb._fit_vol({"x": xs[:50], "y": wild[:50]}, list(range(50))) is None


def marked_news(n, cfg="c1", start=date(2026, 1, 1)):
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "cfg": cfg, "shadowUp": 5, "shadowDown": 1}
        for i in range(n)
    ]


def test_unmarked_news_records_never_enable_signal():
    news = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "up": 5, "down": 1} for i in range(400)]
    ctx = gb.Context({}, TODAY, news)
    assert ctx.has("news") is False
    assert ctx.feature("news", TODAY) is None


def test_marked_news_below_threshold_does_not_enable_signal():
    ctx = gb.Context({}, TODAY, marked_news(fc.MIN_BACKTEST_WEEKS))
    assert ctx.has("news") is False


def test_enough_marked_news_enables_signal():
    ctx = gb.Context({}, TODAY, marked_news(fc.MIN_BACKTEST_WEEKS + 1))
    assert ctx.has("news") is True


def test_cfg_change_restarts_marked_count():
    news = marked_news(fc.MIN_BACKTEST_WEEKS + 10, "c1")
    later = date(2026, 1, 1) + timedelta(days=len(news))
    news += marked_news(5, "c2", later)
    assert gb.Context({}, TODAY, news).has("news") is False


def test_news_feature_none_before_first_marked_day_plus_lookback():
    news = marked_news(fc.MIN_BACKTEST_WEEKS + 5)
    ctx = gb.Context({}, TODAY, news)
    first = date.fromisoformat(ctx.news_first)
    lookback = timedelta(days=gb.NEWS_LOOKBACK_DAYS)
    assert ctx.feature("news", first + lookback - timedelta(days=1)) is None
    assert ctx.feature("news", first + lookback + timedelta(days=3)) is not None
