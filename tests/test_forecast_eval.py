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


def _closes(n, start=date(2020, 1, 1)):
    return [(start + timedelta(days=i), 100.0 + i * 0.01) for i in range(n)]


def _series_with_sigma(sigma):
    s = fc.Series(_closes(len(sigma)))
    s.sigma = list(sigma)
    return s


def test_regime_bin_boundaries():
    assert fe.regime_bin(0.0) == "low"
    assert fe.regime_bin(0.33333) == "low"
    assert fe.regime_bin(1 / 3) == "mid"
    assert fe.regime_bin(0.5) == "mid"
    assert fe.regime_bin(0.6666) == "mid"
    assert fe.regime_bin(2 / 3) == "high"
    assert fe.regime_bin(1.0) == "high"


def test_sigma_percentile_ranks_against_trailing_only():
    n = 400
    up = _series_with_sigma([(i + 1) * 1e-4 for i in range(n)])
    down = _series_with_sigma([(n - i) * 1e-4 for i in range(n)])
    flat = _series_with_sigma([1e-3] * n)
    day = up.dates[300]
    assert fe.sigma_percentile(up, day) == 1.0
    assert fe.sigma_percentile(down, day) == 0.0
    assert fe.sigma_percentile(flat, day) == 0.5


def test_sigma_percentile_ignores_future_values():
    base = [(i % 7 + 1) * 1e-4 for i in range(400)]
    altered = base[:301] + [9.0] * 99
    day = fc.Series(_closes(400)).dates[300]
    assert fe.sigma_percentile(_series_with_sigma(base), day) == fe.sigma_percentile(_series_with_sigma(altered), day)
    truncated = _series_with_sigma(base[:301])
    assert fe.sigma_percentile(truncated, day) == fe.sigma_percentile(_series_with_sigma(base), day)


def test_sigma_percentile_respects_lookback_and_minimum():
    n = 1500
    sigma = [1.0 if i < 305 else 0.001 for i in range(n)]
    sigma[1400] = 0.002
    s = _series_with_sigma(sigma)
    assert fe.sigma_percentile(s, s.dates[1400]) == 1.0
    short = _series_with_sigma([1e-3] * 400)
    assert fe.sigma_percentile(short, short.dates[fc.MIN_RETURNS_FOR_BAND - 1]) is None
    assert fe.sigma_percentile(short, short.dates[fc.MIN_RETURNS_FOR_BAND]) is not None


def test_regime_features_unchanged_by_future_data():
    pts = make_points()
    cut = date(2022, 6, 1)
    altered = [dict(p) if date.fromisoformat(p["date"]) <= cut else {"date": p["date"], "price": p["price"] * 3.7 + i}
               for i, p in enumerate(pts)]
    a = fe._annotated(pts, "fhs")
    b = fe._annotated(altered, "fhs")
    early_a = [(w["basisDate"], w["pct"], w["unusual"]) for w in a if w["basisDate"] <= cut]
    early_b = [(w["basisDate"], w["pct"], w["unusual"]) for w in b if w["basisDate"] <= cut]
    assert early_a and early_a == early_b
    for c in (date(2022, 6, 1), date(2022, 9, 1), date(2022, 12, 15)):
        assert fe.check_regime_no_lookahead(pts, "fhs", c)


def test_regime_no_lookahead_detects_leak(monkeypatch):
    pts = make_points()
    monkeypatch.setattr(fe, "sigma_percentile", lambda series, day: len(series.dates) / 10000)
    assert fe.check_regime_no_lookahead(pts, "fhs", date(2022, 6, 1)) is False


def test_unusual_flag_matches_build_forecast_rule():
    pts = make_points()
    closes = fc.clean_series(pts)
    series = fc.Series(closes)
    returns = series.horizon_returns()
    basis_date, basis_price = closes[-1]
    _, flag = fe._features(series, returns, basis_date, basis_price)
    past_abs = sorted(abs(r) for b, _, r, _ in returns if b < basis_date - timedelta(days=fc.HORIZON_DAYS))
    latest = series.close_on_or_before(basis_date - timedelta(days=fc.HORIZON_DAYS),
                                       basis_date - timedelta(days=fc.HORIZON_DAYS + fc.TARGET_SLACK_DAYS))
    assert flag == (abs(math.log(basis_price / latest[1])) > fc.quantile(past_abs, fc.UNUSUAL_PERCENTILE))
    spiked = [dict(p) for p in pts]
    spiked[-1]["price"] = spiked[-1]["price"] * 5
    s2 = fc.Series(fc.clean_series(spiked))
    _, flag2 = fe._features(s2, s2.horizon_returns(), basis_date, spiked[-1]["price"])
    assert flag2 is True


def _crafted(n=156, miss_bin="high"):
    pcts = {"low": 0.1, "mid": 0.5, "high": 0.9}
    order = ["low", "mid", "high"]
    d0 = date(2020, 1, 1)
    rows = []
    for i in range(n):
        b = order[i % 3]
        k = i // 3
        inside = (k % 2 == 0) if b == miss_bin else (k % 10 != 0)
        rows.append({"basisDate": d0 + timedelta(days=7 * i), "inside": inside, "pct": pcts[b],
                     "unusual": i % 20 == 0})
    return rows


def test_analyze_code_tables_and_unusual_split():
    a = fe.analyze_code(_crafted())
    assert a["weeks"] == 156 and a["skipped"] == 0
    assert sum(a["bins"][b]["n"] for b in fe.BINS) == 156
    assert a["worst"] == "high" and a["best"] in ("low", "mid")
    assert math.isclose(a["bins"]["high"]["coverage"], 0.5)
    assert a["gap"] >= fe.MIN_GAP
    assert sum(a["holdout"][b]["n"] for b in fe.BINS) == fe.HOLDOUT_WEEKS
    assert sum(a["beforeHoldout"][b]["n"] for b in fe.BINS) == 156 - fe.HOLDOUT_WEEKS
    assert sum(a["early"][b]["n"] for b in fe.BINS) + sum(a["late"][b]["n"] for b in fe.BINS) == 156
    assert a["unusual"]["unusual"]["n"] + a["unusual"]["usual"]["n"] == 156


def test_verdict_pass_with_worst_bin(monkeypatch):
    monkeypatch.setattr(fe, "_annotated", lambda points, method: _crafted())
    result = fe.regimes(make_daily(("usd", "a", "b")))
    assert result["verdict"]["verdict"] == "PASS"
    assert result["verdict"]["worst"] == "high"
    assert result["verdict"]["codesMatching"] == 3 == result["verdict"]["codesWithData"]


def test_verdict_pass_names_calm_bin_when_calm_is_worst(monkeypatch):
    monkeypatch.setattr(fe, "_annotated", lambda points, method: _crafted(miss_bin="low"))
    result = fe.regimes(make_daily(("usd", "a")))
    assert result["verdict"]["verdict"] == "PASS" and result["verdict"]["worst"] == "low"


def _jump_points(seed, n=2000):
    rng = random.Random(seed)
    p = 100.0
    d0 = date(2019, 1, 1)
    out = []
    for i in range(n):
        if i % 30 == 29:
            p *= math.exp(rng.choice((-1, 1)) * 0.12)
        else:
            p *= math.exp(rng.gauss(0, 0.002))
        out.append({"date": (d0 + timedelta(days=i)).isoformat(), "price": p})
    return out


def test_end_to_end_calm_regime_misses_more():
    daily = {"codes": {c: {p["date"]: (None, p["price"]) for p in _jump_points(s)}
                       for c, s in (("usd", 1), ("a", 2), ("b", 3))}}
    result = fe.regimes(daily)
    assert result["verdict"]["verdict"] == "PASS" and result["verdict"]["worst"] == "low"
    bins = result["codes"]["usd"]["bins"]
    assert bins["low"]["coverage"] < bins["mid"]["coverage"] - fe.MIN_GAP


def test_extremes_tie_has_no_worst():
    table = {"low": {"n": 5, "coverage": 0.5}, "mid": {"n": 5, "coverage": 0.5}, "high": {"n": 5, "coverage": 0.9}}
    assert fe._extremes(table)[0] is None
    table["mid"]["coverage"] = 0.6
    assert fe._extremes(table)[:2] == ("low", "high")


def test_verdict_fails_when_reference_bin_not_worst_before_holdout(monkeypatch):
    rows = _crafted()
    cut = len(rows) - fe.HOLDOUT_WEEKS
    shifted = [dict(r, inside=(r["pct"] != 0.1)) if i < cut else r for i, r in enumerate(rows)]
    monkeypatch.setattr(fe, "_annotated", lambda points, method: shifted)
    v = fe.regimes(make_daily(("usd", "a")))["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "primary-holdout"


def test_verdict_fails_first_condition(monkeypatch):
    flat = [dict(r, inside=True) for r in _crafted()]
    monkeypatch.setattr(fe, "_annotated", lambda points, method: flat)
    v = fe.regimes(make_daily(("usd", "a")))["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "primary-gap"

    late_flip = [dict(r, inside=(r["inside"] if i < 78 else (r["pct"] != 0.5))) for i, r in enumerate(_crafted())]
    monkeypatch.setattr(fe, "_annotated", lambda points, method: late_flip)
    v = fe.regimes(make_daily(("usd", "a")))["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "primary-halves"


def test_verdict_fails_on_holdout_and_code_share(monkeypatch):
    rows = _crafted()
    holdout_flip = rows[:-fe.HOLDOUT_WEEKS] + [dict(r, inside=(r["pct"] == 0.9 or r["inside"])) for r in rows[-fe.HOLDOUT_WEEKS:]]
    monkeypatch.setattr(fe, "_annotated", lambda points, method: holdout_flip)
    v = fe.regimes(make_daily(("usd", "a")))["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "primary-holdout"

    good, other = _crafted(), _crafted(miss_bin="low")

    def pick(points, method):
        return good if points[0]["price"] == primary_first else other

    primary_first = fe.points_from_daily(make_daily(("usd", "a", "b"))["codes"]["usd"])[0]["price"]
    monkeypatch.setattr(fe, "_annotated", pick)
    v = fe.regimes(make_daily(("usd", "a", "b")))["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "code-share"
    assert v["codesMatching"] == 1 and v["codesWithData"] == 3


def test_verdict_fails_without_primary_or_history():
    v = fe.regimes(make_daily(("a", "b")))["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "primary-no-data"
    short = {"codes": {"usd": {p["date"]: (None, p["price"]) for p in make_points(n=200)}}}
    result = fe.regimes(short)
    assert result["codes"]["usd"] is None
    assert result["verdict"]["reason"] == "primary-no-data"
    assert fe.regimes_report(result)[0] == "usd regimes insufficient-history"


def test_weeks_without_enough_trailing_data_are_skipped_and_counted(monkeypatch):
    calls = {"n": 0}

    def stub(series, day):
        calls["n"] += 1
        return None if calls["n"] <= 10 else 0.5

    monkeypatch.setattr(fe, "sigma_percentile", stub)
    rows = fe._annotated(make_points(), "fhs")
    a = fe.analyze_code(rows)
    assert a["skipped"] == 10
    assert sum(a["bins"][b]["n"] for b in fe.BINS) == a["weeks"] - 10


def test_random_walk_fails():
    daily = {"codes": {c: {p["date"]: (None, p["price"]) for p in make_points(seed=s)}
                       for c, s in (("usd", 11), ("a", 12), ("b", 13))}}
    v = fe.regimes(daily)["verdict"]
    assert v["verdict"] == "FAIL" and v["reason"] == "primary-halves"


def test_cli_regimes_json_matches_text(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fe, "_annotated", lambda points, method: _crafted())
    f = tmp_path / "daily.json"
    f.write_text(json.dumps(make_daily(("usd", "a"))))
    assert fe.main(["--daily", str(f), "--regimes"]) == 0
    text = capsys.readouterr().out.strip().splitlines()
    assert fe.main(["--daily", str(f), "--regimes", "--json", "--codes", "usd,a"]) == 0
    data = json.loads(capsys.readouterr().out)
    v = data["verdict"]
    assert set(data["codes"]) == {"usd", "a"} and {"bins", "early", "late", "holdout", "unusual", "skipped"} <= set(data["codes"]["usd"])
    assert text[-1].startswith(f"verdict {v['verdict']} worst={v['worst']} reason={v['reason']}")
    assert v["verdict"] == "PASS"
    assert fe.main(["--daily", str(f), "--regimes", "--codes", "a"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("verdict FAIL")


def test_cli_without_regimes_unchanged(tmp_path, capsys):
    f = tmp_path / "daily.json"
    f.write_text(json.dumps(make_daily()))
    assert fe.main(["--daily", str(f)]) == 0
    out = capsys.readouterr().out
    assert "verdict" not in out and "regimes" not in out and out.strip().splitlines()[-1].startswith("totals ")
