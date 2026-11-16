import importlib.util
import math
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("forecast_confidence", TOOLS / "forecast_confidence.py")
fcf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fcf)

SNAP_SPEC = importlib.util.spec_from_file_location("gheymat_snapshot", TOOLS / "gheymat_snapshot.py")
snap = importlib.util.module_from_spec(SNAP_SPEC)
SNAP_SPEC.loader.exec_module(snap)


def doc(low=90.0, high=110.0, price=100.0, unusual=False, day="2026-11-08"):
    return {"basis": {"date": day, "price": price}, "low": low, "high": high, "unusual": unusual}


def conf(d, live, previous=None):
    return fcf.build_confidence(d, live, previous)


def test_quiet_document_is_normal():
    assert conf(doc(), 100.0) == {"level": "normal", "reasons": []}


def test_unusual_alone():
    assert conf(doc(unusual=True), 100.0) == {"level": "low", "reasons": ["unusual"]}


def test_band_broken_alone_above_and_below():
    assert conf(doc(), 111.0)["reasons"] == ["band-broken"]
    assert conf(doc(), 89.0)["reasons"] == ["band-broken"]


def test_moved_since_basis_alone():
    assert conf(doc(), 106.0) == {"level": "low", "reasons": ["moved-since-basis"]}


def test_band_edges_are_not_broken():
    assert "band-broken" not in conf(doc(), 110.0)["reasons"]
    assert "band-broken" not in conf(doc(), 90.0)["reasons"]


def test_moved_threshold_is_strict():
    d = doc(low=80.0, high=125.0, price=100.0)
    limit = fcf.MOVE_FRACTION * math.log(125.0 / 80.0)
    assert conf(d, 100.0 * math.exp(limit * 0.999))["reasons"] == []
    assert conf(d, 100.0 * math.exp(limit * 1.001))["reasons"] == ["moved-since-basis"]


def test_band_broken_excludes_moved_and_order_is_fixed():
    assert conf(doc(), 130.0)["reasons"] == ["band-broken"]
    assert conf(doc(unusual=True), 130.0)["reasons"] == ["unusual", "band-broken"]
    assert conf(doc(unusual=True), 106.0)["reasons"] == ["unusual", "moved-since-basis"]


def test_invalid_live_price_skips_live_reasons():
    for live in (None, 0, -5, float("nan"), float("inf"), True, "x"):
        assert conf(doc(), live) == {"level": "normal", "reasons": []}
    assert conf(doc(unusual=True), None)["reasons"] == ["unusual"]


def test_sticky_reasons_stay_within_a_basis():
    first = conf(doc(), 130.0)
    again = conf(doc(), 100.0, first)
    assert again == {"level": "low", "reasons": ["band-broken"]}
    merged = conf(doc(), 106.0, first)
    assert merged["reasons"] == ["band-broken"]


def test_no_live_price_keeps_sticky_reasons():
    assert conf(doc(), None, {"level": "low", "reasons": ["band-broken"]})["reasons"] == ["band-broken"]


def test_garbage_previous_is_ignored():
    assert conf(doc(), 100.0, {"reasons": ["bogus", 3]}) == {"level": "normal", "reasons": []}
    assert conf(doc(), 100.0, "x") == {"level": "normal", "reasons": []}


def test_safe_confidence_resets_on_a_new_basis():
    old = doc(day="2026-11-01")
    old["confidence"] = {"level": "low", "reasons": ["band-broken"]}
    assert fcf.safe_confidence(doc(), 100.0, old) == {"level": "normal", "reasons": []}
    same = doc()
    same["confidence"] = {"level": "low", "reasons": ["band-broken"]}
    assert fcf.safe_confidence(doc(), 100.0, same)["reasons"] == ["band-broken"]


def test_safe_confidence_logs_and_returns_none_on_error():
    logs = []
    assert fcf.safe_confidence({"basis": {"date": "d", "price": 1}, "low": 1, "high": 2, "unusual": object()}, 1.5, None, logs.append) is not None
    assert fcf.safe_confidence(None, 1.0, None, logs.append) is None
    assert logs == ["ai: confidence skipped: AttributeError"]


def test_live_prices_for_picks_sell_else_buy_and_filters():
    rates = [
        {"code": "a", "kind": "currency", "sell": 10, "buy": 9},
        {"code": "b", "kind": "coin", "sell": None, "buy": 7},
        {"code": "c", "kind": "currency", "sell": None, "buy": None},
        {"code": "d", "kind": "currency", "sell": 0, "buy": 5},
        {"code": "e", "kind": "gold", "sell": 3, "buy": 3},
        {"code": "f", "kind": "currency", "sell": 4, "buy": 4},
    ]
    daily = {"codes": {"a": {}, "b": {}, "c": {}, "d": {}, "e": {}}}
    assert snap.live_prices_for(rates, daily) == {"a": 10.0, "b": 7.0}


def test_live_price_far_off_the_basis_is_ignored():
    assert conf(doc(), 1000.0) == {"level": "normal", "reasons": []}
    assert conf(doc(), 10.0) == {"level": "normal", "reasons": []}
    assert conf(doc(), 199.0) == {"level": "low", "reasons": ["band-broken"]}
