import importlib.util
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import gheymat_blend as blend
import signal_shadow as shadow

FSPEC = importlib.util.spec_from_file_location("test_gheymat_forecast", pathlib.Path(__file__).resolve().parent / "test_gheymat_forecast.py")
tf = importlib.util.module_from_spec(FSPEC)
FSPEC.loader.exec_module(tf)


def daily_from(points_by_code):
    return {"codes": {c: {p["date"]: [None, p["price"]] for p in pts} for c, pts in points_by_code.items()}}


def test_score_counts_wins_and_baseline(monkeypatch):
    names = iter(["vol-scale-by-oil-shock", "baseline", "vol-scale-by-oil-shock"])
    monkeypatch.setattr(blend, "best_variant", lambda *a, **k: {"name": next(names), "spec": None, "report": {}})
    daily = daily_from({c: tf.walk(seed=i) for i, c in enumerate(("aaa", "bbb", "ccc"), 1)})
    result = shadow.score(daily, object())
    assert result == {"codes": 3, "wins": {"vol-scale-by-oil-shock": 2}, "baseline": 1}


def test_score_skips_malformed_and_short_codes():
    daily = daily_from({"short": tf.walk(years=1)})
    daily["codes"]["bad"] = {"2026-01-01": "oops"}
    daily["codes"]["worse"] = None
    daily["codes"]["empty"] = {}
    assert shadow.score(daily, object()) == {"codes": 0, "wins": {}, "baseline": 0}
    assert shadow.score({}, None) == {"codes": 0, "wins": {}, "baseline": 0}


def test_score_without_context_is_all_baseline():
    result = shadow.score(daily_from({"usd": tf.walk(seed=7)}), None)
    assert result == {"codes": 1, "wins": {}, "baseline": 1}


def test_line_format():
    result = {"codes": 12, "wins": {"drift-by-usd-move": 1, "vol-scale-by-oil-shock": 2}, "baseline": 9}
    assert shadow.line(result) == "ai: signal shadow 12 codes, baseline 9, vol-scale-by-oil-shock 2, drift-by-usd-move 1"
    assert shadow.line({"codes": 0, "wins": {}, "baseline": 0}) == "ai: signal shadow 0 codes, baseline 0"
