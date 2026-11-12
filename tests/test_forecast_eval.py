import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import gheymat_forecast as fc
import forecast_eval as fe


def make_points(n=1100, seed=7, vol=0.01):
    rng = random.Random(seed)
    d0 = date(2020, 1, 1)
    p = 100.0
    pts = []
    for i in range(n):
        p *= math.exp(rng.gauss(0, vol))
        pts.append({"date": (d0 + timedelta(days=i)).isoformat(), "price": p})
    return pts


def make_daily(codes=("a", "b")):
    out = {}
    for i, c in enumerate(codes):
        out[c] = {p["date"]: (None, p["price"]) for p in make_points(seed=i + 1)}
    return {"codes": out}


def test_evaluate_keys_and_ranges():
    for method in fc.METHODS:
        r = fe.evaluate(make_points(), method)
        assert set(r) >= {"method", "weeks", "coverage", "coverageRecent", "intervalScore", "mape", "naiveMape", "skill"}
        assert {"recent_skill", "recent_weeks", "miss_below", "miss_above"} <= set(r)
        assert 0 <= r["coverage"] <= 1 and 0 <= r["coverageRecent"] <= 1
        assert r["weeks"] >= fc.MIN_BACKTEST_WEEKS


def test_evaluate_none_on_short_history():
    assert fe.evaluate(make_points(n=200), "fhs") is None
    assert fe.evaluate([], "eq") is None


def test_no_lookahead_three_cuts():
    pts = make_points()
    for method in fc.METHODS:
        for cut in (date(2022, 6, 1), date(2022, 12, 15), date(2022, 9, 1)):
            assert fe.check_no_lookahead(pts, method, cut)


def test_no_lookahead_detects_future_leak(monkeypatch):
    pts = make_points()
    original = fc.backtest
    returns = fc.Series(fc.clean_series(pts)).horizon_returns()

    for method in fc.METHODS:
        def leaky(series, rets, m=method, band_fn=None, _method=method):
            return original(
                series, rets, m,
                band_fn=lambda b, s: fc.band_at(returns, b + timedelta(days=fc.HORIZON_DAYS), s, _method),
            )

        monkeypatch.setattr(fc, "backtest", leaky)
        for cut in (date(2022, 6, 1), date(2022, 9, 1)):
            assert fe.check_no_lookahead(pts, method, cut) is False
        monkeypatch.setattr(fc, "backtest", original)


def test_compare_picks_lower_aligned_score(monkeypatch):
    pts = make_points()
    monkeypatch.setattr(fc, "COVERAGE_ALL", (0.0, 1.0))
    out = fe.compare(pts)
    assert out["best"] in fc.METHODS
    weeks = {m: fc.backtest(fc.Series(fc.clean_series(pts)), fc.Series(fc.clean_series(pts)).horizon_returns(), m)
             for m in fc.METHODS}
    shared = set.intersection(*({w["basisDate"] for w in ws} for ws in weeks.values()))
    mean = {m: sum(w["intervalScore"] for w in ws if w["basisDate"] in shared) / len(shared) for m, ws in weeks.items()}
    assert out["best"] == min(mean, key=mean.get)


def test_compare_none_when_no_method_in_band(monkeypatch):
    monkeypatch.setattr(fc, "COVERAGE_ALL", (2.0, 3.0))
    out = fe.compare(make_points())
    assert out["best"] is None
    assert set(out["results"]) == set(fc.METHODS)


def test_compare_none_when_recent_coverage_out_of_band(monkeypatch):
    monkeypatch.setattr(fc, "COVERAGE_ALL", (0.0, 1.0))
    monkeypatch.setattr(fc, "COVERAGE_RECENT", (2.0, 3.0))
    out = fe.compare(make_points())
    assert out["best"] is None
    assert set(out["results"]) == set(fc.METHODS)


def test_report_lines():
    lines = fe.report(make_daily())
    assert any(line.startswith("a best") for line in lines)
    assert lines[-1].startswith("totals ")
    assert len(fe.report(make_daily(), codes=["b"])) < len(lines)


def test_main_json_and_missing_file(tmp_path, capsys):
    f = tmp_path / "daily.json"
    f.write_text(json.dumps(make_daily()))
    assert fe.main(["--daily", str(f), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["codes"]) == {"a", "b"} and set(data["totals"]) == set(fc.METHODS)
    assert fe.main(["--daily", str(f)]) == 0
    assert fe.main(["--daily", str(tmp_path / "nope.json")]) == 2
    assert capsys.readouterr().err.strip() == "FileNotFoundError"


def _wk(err, naive, actual=100.0, low=90.0, high=110.0):
    return {"err": err, "naiveErr": naive, "actual": actual, "intervalScore": 0.0, "low": low, "high": high,
            "inside": low <= actual <= high}


def test_recent_skill_better_recently_worse_overall():
    old = [_wk(0.10, 0.05)] * 100
    new = [_wk(0.01, 0.05)] * 52
    weeks = old + new
    rs, n = fe.recent_skill(weeks)
    assert n == 52 and math.isclose(rs, 0.8)
    assert fe._metrics(weeks, "fhs")["skill"] < 0


def test_recent_skill_worse_recently_better_overall():
    weeks = [_wk(0.01, 0.05)] * 100 + [_wk(0.10, 0.05)] * 52
    rs, n = fe.recent_skill(weeks)
    assert n == 52 and math.isclose(rs, -1.0)
    assert fe._metrics(weeks, "fhs")["skill"] > 0


def test_recent_skill_none_when_short_or_zero_naive():
    rs, n = fe.recent_skill([_wk(0.01, 0.05)] * 51)
    assert rs is None and n == 51
    rs, n = fe.recent_skill([_wk(0.01, 0.0)] * 60)
    assert rs is None and n == 52


def test_tail_misses_all_below_mixed_and_empty():
    assert fe.tail_misses([]) == (None, None)
    assert fe.tail_misses([_wk(0, 0, actual=80.0)] * 4) == (1.0, 0.0)
    weeks = [_wk(0, 0, actual=80.0), _wk(0, 0, actual=120.0), _wk(0, 0, actual=130.0), _wk(0, 0)]
    assert fe.tail_misses(weeks) == (0.25, 0.5)


def test_tail_misses_sum_with_coverage():
    weeks = [_wk(0, 0, actual=a) for a in (80, 95, 105, 120, 130, 100, 70)]
    below, above = fe.tail_misses(weeks)
    assert math.isclose(below + above, 1 - fc.coverage(weeks))
    r = fe.evaluate(make_points(), "fhs")
    assert math.isclose(r["miss_below"] + r["miss_above"], 1 - r["coverage"], abs_tol=1e-12)
