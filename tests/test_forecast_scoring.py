import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import gheymat_forecast as fc  # noqa: E402
import forecast_report  # noqa: E402


def make_series(n=900):
    d0 = date(2020, 1, 1)
    p = 100.0
    pts = []
    for i in range(n):
        p *= math.exp(0.01 * math.sin(i * 1.7) + 0.002 * math.cos(i * 0.3))
        pts.append({"date": (d0 + timedelta(days=i)).isoformat(), "price": p})
    return fc.Series(fc.clean_series(pts))


def test_interval_score():
    assert fc.interval_score(1, 2, 1.5, 0.2) == 1
    assert math.isclose(fc.interval_score(1, 2, 0.5, 0.2), 1 + 10 * 0.5)
    assert math.isclose(fc.interval_score(1, 2, 3, 0.2), 1 + 10 * 1)


def test_pinball():
    assert math.isclose(fc.pinball(0.9, 1, 2), 0.9)
    assert math.isclose(fc.pinball(0.9, 2, 1), 0.1)
    assert fc.pinball(0.5, 3, 3) == 0


def test_summarize_empty_and_values():
    assert fc.summarize([])["n"] == 0
    weeks = [{"inside": True, "intervalScore": 1.0, "err": 0.1, "naiveErr": 0.2},
             {"inside": False, "intervalScore": 3.0, "err": 0.3, "naiveErr": 0.2}]
    s = fc.summarize(weeks)
    assert s == {"coverage": 0.5, "meanIntervalScore": 2.0, "medianErr": 0.2, "medianNaiveErr": 0.2, "n": 2}


def test_backtest_default_unchanged_and_scored():
    series = make_series()
    rets = series.horizon_returns()
    a = fc.backtest(series, rets, "fhs")
    b = fc.backtest(series, rets, "fhs", band_fn=None)
    assert a == b and len(a) > 50
    w = a[-1]
    assert w["intervalScore"] >= (w["high"] - w["low"]) / w["basis"] - 1e-12
    assert w["pinball"] >= 0


def test_band_fn_injected_matches_default():
    series = make_series()
    rets = series.horizon_returns()
    base = fc.backtest(series, rets, "fhs")
    same = fc.backtest(series, rets, "fhs", band_fn=lambda d, s: fc.band_at(rets, d, s, "fhs"))
    assert base == same
    wide = fc.backtest(series, rets, "fhs", band_fn=lambda d, s: (lambda b: None if b is None else tuple(3 * x for x in b))(fc.band_at(rets, d, s, "fhs")))
    assert len(wide) == len(base) and fc.coverage(wide) >= fc.coverage(base)
    none = fc.backtest(series, rets, "fhs", band_fn=lambda d, s: None)
    assert none == []


def test_report_columns():
    pts = [{"date": (date(2020, 1, 1) + timedelta(days=i)).isoformat(), "price": 100 + math.sin(i) * 3 + i * 0.01} for i in range(900)]
    d = forecast_report.diagnose(pts, date(2022, 6, 20))
    assert d["score"] is not None and d["errVsNaive"] is not None
