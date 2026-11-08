import importlib.util
import math
import pathlib
import random
from datetime import date, timedelta

import pytest

SPEC = importlib.util.spec_from_file_location(
    "gheymat_forecast", pathlib.Path(__file__).resolve().parents[1] / "tools" / "gheymat_forecast.py")
fc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fc)

END = date(2026, 11, 8)
TODAY = date(2026, 11, 9)
NOW = "2026-11-09T06:00:00Z"


def walk(seed=7, years=12, sigma=0.008, end=END, vol=None):
    rng = random.Random(seed)
    start = end - timedelta(days=years * 365)
    price = 50000.0
    points = []
    d = start
    while d <= end:
        if d.weekday() != fc.FRIDAY:
            s = vol(d) if vol else sigma
            price *= math.exp(rng.gauss(0.0, s))
            points.append({"date": d.isoformat(), "price": round(price, 2)})
        d += timedelta(days=1)
    return points


def test_random_walk_is_calibrated_and_sane():
    doc, reason = fc.build_forecast("usd", walk(), TODAY, NOW)
    assert reason is None
    assert abs(doc["coverage"] - fc.BAND) <= 0.03
    assert 0 < doc["low"] <= doc["likely"] <= doc["high"]
    assert doc["backtestWeeks"] >= fc.MIN_BACKTEST_WEEKS
    assert doc["target"] == (date.fromisoformat(doc["basis"]["date"]) + timedelta(days=7)).isoformat()
    assert doc["band"] == 0.8 and doc["horizonDays"] == 7 and doc["method"] == "empirical-quantile-v1"
    assert doc["track"] == [] and doc["signals"] == [] and doc["unusual"] is False
    assert doc["generatedAt"] == NOW


def test_band_ignores_future_data():
    points = walk()
    basis = date(2022, 6, 1)
    while basis.weekday() == fc.FRIDAY:
        basis += timedelta(days=1)
    before = fc.Series(fc.clean_series(points))
    band_before = fc.band_at(before.horizon_returns(), basis)
    cut = basis.isoformat()
    perturbed = [p if p["date"] <= cut else {"date": p["date"], "price": p["price"] * 3.7} for p in points]
    after = fc.Series(fc.clean_series(perturbed))
    band_after = fc.band_at(after.horizon_returns(), basis)
    assert band_before is not None
    assert band_before == band_after


def test_backtest_weeks_ignore_future_data():
    points = walk()
    cut = date(2022, 6, 1)
    weeks = fc.backtest(fc.Series(fc.clean_series(points)), fc.Series(fc.clean_series(points)).horizon_returns())
    perturbed = [p if p["date"] <= cut.isoformat() else {"date": p["date"], "price": p["price"] * 0.4}
                 for p in points]
    s2 = fc.Series(fc.clean_series(perturbed))
    weeks2 = fc.backtest(s2, s2.horizon_returns())
    early = [w for w in weeks if w["basisDate"] + timedelta(days=7) <= cut]
    early2 = [w for w in weeks2 if w["basisDate"] + timedelta(days=7) <= cut]
    assert early and early == early2


def test_short_history_publishes_nothing():
    doc, reason = fc.build_forecast("gram", walk(years=2), TODAY, NOW)
    assert doc is None and reason == "history"


def test_stale_basis_publishes_nothing():
    doc, reason = fc.build_forecast("usd", walk(), TODAY + timedelta(days=5), NOW)
    assert doc is None and reason in ("basis-stale", "recent-gap")


def test_recent_gap_publishes_nothing():
    points = [p for p in walk() if not ("2026-10-01" <= p["date"] <= "2026-10-12")]
    doc, reason = fc.build_forecast("usd", points, TODAY, NOW)
    assert doc is None and reason == "recent-gap"


def test_basis_must_match_published_history_close():
    points = walk()
    last = points[-1]
    ok, reason = fc.build_forecast("usd", points, TODAY, NOW, history_close=last)
    assert reason is None and ok["basis"] == {"date": last["date"], "price": last["price"]}
    doc, reason = fc.build_forecast("usd", points, TODAY, NOW,
                                    history_close={"date": last["date"], "price": last["price"] + 100})
    assert doc is None and reason == "basis-mismatch"


def test_volatility_shift_fails_calibration():
    shift = END - timedelta(days=420)
    points = walk(vol=lambda d: 0.03 if d >= shift else 0.004)
    doc, reason = fc.build_forecast("usd", points, TODAY, NOW)
    assert doc is None and reason in ("calibration", "calibration-recent")


def test_unusual_week_is_flagged_without_changing_numbers():
    points = walk()
    for p in points[-3:]:
        p["price"] = round(p["price"] * 1.25, 2)
    doc, reason = fc.build_forecast("usd", points, TODAY, NOW)
    assert reason is None and doc["unusual"] is True
    assert doc["basis"]["price"] == points[-1]["price"]


def test_skill_rule_falls_back_to_no_change():
    assert fc.apply_skill(101.0, 100.0, mape=1.9, naive_mape=2.1) == 101.0
    assert fc.apply_skill(101.0, 100.0, mape=2.1, naive_mape=2.1) == 100.0
    assert fc.apply_skill(101.0, 100.0, mape=2.5, naive_mape=2.1) == 100.0


def test_quantile_interpolates():
    assert fc.quantile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert fc.quantile([5.0], 0.9) == 5.0
    with pytest.raises(ValueError):
        fc.quantile([], 0.5)


def test_clean_series_drops_bad_points_and_duplicates():
    pts = [{"date": "2026-01-02", "price": 10}, {"date": "2026-01-01", "price": 9},
           {"date": "2026-01-02", "price": 11}, {"date": "2026-01-03", "price": 0},
           {"date": "2026-01-04", "price": None}, {"date": "2026-01-05", "price": float("nan")}]
    assert fc.clean_series(pts) == [(date(2026, 1, 1), 9.0), (date(2026, 1, 2), 11.0)]


def test_previous_trading_day_skips_friday():
    assert fc.previous_trading_day(date(2026, 11, 7)) == date(2026, 11, 5)
    assert fc.previous_trading_day(date(2026, 11, 9)) == date(2026, 11, 8)
