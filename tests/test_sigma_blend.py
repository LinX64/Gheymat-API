import hashlib
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import gheymat_forecast as fc
import gheymat_blend

END = date(2026, 11, 8)
TODAY = date(2026, 11, 9)
NOW = "2026-11-09T06:00:00Z"
DEFAULT_DIGEST = "e2e9913c63a62f8528232d6c3a04631618c67c407bb5ba4ede5705bc1da78f59"


def walk(seed=7, years=12, sigma=0.008):
    rng = random.Random(seed)
    price = 50000.0
    points = []
    d = END - timedelta(days=years * 365)
    while d <= END:
        if d.weekday() != fc.FRIDAY:
            price *= math.exp(rng.gauss(0.0, sigma))
            points.append({"date": d.isoformat(), "price": round(price, 2)})
        d += timedelta(days=1)
    return points


def test_registry_keeps_default_and_adds_variant():
    assert fc.DEFAULT_METHOD == "fhs"
    assert fc.METHOD == "filtered-quantile-v1"
    assert fc.METHODS["fhs2"] == "filtered-quantile-v2"
    assert fc.BLEND_WEIGHT == 0.5


def test_published_methods_stay_default_only():
    assert gheymat_blend.expected_methods(None) == {"filtered-quantile-v1"}


def test_blend_uses_only_earlier_data():
    pts = walk(years=4)
    closes = fc.clean_series(pts)
    cut = len(closes) // 2
    base = fc.Series(closes)
    changed = [(d, p * 3 if i > cut else p) for i, (d, p) in enumerate(closes)]
    other = fc.Series(changed)
    a = base.sigma_for("fhs2")
    b = other.sigma_for("fhs2")
    assert a[: cut + 1] == b[: cut + 1]
    assert a[cut + 5] != b[cut + 5]


def test_blend_matches_formula():
    closes = fc.clean_series(walk(years=3))
    series = fc.Series(closes)
    rets = [math.log(b / a) for (_, a), (_, b) in zip(closes, closes[1:])]
    i = 600
    window = rets[max(0, i - 1 - fc.BLEND_LONG_RETURNS): i - 1]
    long_var = sum(r * r for r in window) / len(window)
    expected = math.sqrt(0.5 * series.sigma[i] ** 2 + 0.5 * long_var)
    assert abs(series.sigma_for("fhs2")[i] - expected) < 1e-12


def test_default_sigma_unchanged_by_variant():
    series = fc.Series(fc.clean_series(walk(years=3)))
    assert series.sigma_for("fhs") is series.sigma
    assert series.sigma_for(None) is series.sigma
    series.sigma_for("fhs2")
    assert series.sigma_for("fhs") is series.sigma


def test_default_forecast_is_byte_identical():
    doc, why = fc.build_forecast("alpha", walk(), TODAY, NOW)
    assert why is None
    assert hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest() == DEFAULT_DIGEST


def test_variant_builds_valid_forecast_and_passes_gates():
    doc, why = fc.build_forecast("alpha", walk(), TODAY, NOW, method="fhs2")
    assert why is None
    assert doc["method"] == "filtered-quantile-v2"
    assert 0 < doc["low"] <= doc["likely"] <= doc["high"]
    assert fc.COVERAGE_ALL[0] <= doc["coverage"] <= fc.COVERAGE_ALL[1]
    assert doc["backtestWeeks"] >= fc.MIN_BACKTEST_WEEKS


def test_variant_band_ignores_future_data():
    closes = fc.clean_series(walk(years=6))
    cut = closes[len(closes) // 2][0]
    basis = cut - timedelta(days=10)
    full = fc.Series(closes)
    head = fc.Series([c for c in closes if c[0] <= cut])
    a = fc.band_at(full.horizon_returns("fhs2"), basis, full.sigma_at(basis, "fhs2"), "fhs2")
    b = fc.band_at(head.horizon_returns("fhs2"), basis, head.sigma_at(basis, "fhs2"), "fhs2")
    assert a == b and a is not None


def test_variant_ignores_signal_context(monkeypatch):
    calls = []
    monkeypatch.setattr(gheymat_blend, "choose", lambda *a, **k: calls.append(1))
    pts = walk()
    plain = fc.build_forecast("alpha", pts, TODAY, NOW, method="fhs2")
    with_ctx = fc.build_forecast("alpha", pts, TODAY, NOW, method="fhs2", signal_ctx=object())
    assert plain == with_ctx and calls == []
    fc.build_forecast("alpha", pts, TODAY, NOW, signal_ctx=object())
    assert calls == [1]
