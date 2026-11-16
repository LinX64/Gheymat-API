import importlib.util
import json
import pathlib
import sys
from datetime import date, timedelta

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("forecast_track", TOOLS / "forecast_track.py")
ft = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ft)

BASIS = "2026-11-08"
TARGET = "2026-11-15"


def make_doc(code="usd", basis=BASIS, low=90.0, likely=100.0, high=110.0):
    target = (date.fromisoformat(basis) + timedelta(days=7)).isoformat()
    return {"code": code, "basis": {"date": basis, "price": likely}, "target": target,
            "low": low, "likely": likely, "high": high}


def series_of(*pairs):
    points = [{"date": d, "price": p} for d, p in pairs]
    return ft.fc.Series(ft.fc.clean_series(points))


def entry(day, actual=100.0, hit=True):
    target = (date.fromisoformat(day) + timedelta(days=7)).isoformat()
    return {"basisDate": day, "target": target, "likely": 100.0, "low": 90.0, "high": 110.0,
            "actual": actual, "hit": hit}


def fresh_state(tmp_path):
    state = ft.open_state(tmp_path, lambda *_: None)
    assert state is not None
    return state


def logged(state, code="usd", day=BASIS):
    return state["records"][day]["codes"][code]


def test_open_state_without_root_is_none():
    assert ft.open_state(None) is None


def test_first_write_wins_on_a_same_basis_rebuild(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc(likely=100.0))
    ft.record_forecast(state, make_doc(low=80.0, likely=95.0, high=120.0))
    assert (logged(state)["low"], logged(state)["likely"], logged(state)["high"]) == (90.0, 100.0, 110.0)
    assert ft.flush(state) is True
    saved = json.loads((tmp_path / "archive" / "forecast-log.json").read_text())
    assert len(saved) == 1 and saved[0]["codes"]["usd"]["likely"] == 100.0


def test_another_code_joins_an_existing_basis_day(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc("usd"))
    ft.record_forecast(state, make_doc("eur", likely=200.0, low=180.0, high=220.0))
    assert sorted(state["records"][BASIS]["codes"]) == ["eur", "usd"]
    assert logged(state, "usd")["likely"] == 100.0


def test_resolves_on_the_target_close_and_computes_hit(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), (TARGET, 105.0), ("2026-11-16", 120.0)))
    e = logged(state)
    assert (e["actual"], e["actualDate"], e["hit"]) == (105.0, TARGET, True)
    state2 = fresh_state(tmp_path / "other")
    ft.record_forecast(state2, make_doc())
    ft.resolve_pending(state2, "usd", series_of((BASIS, 100.0), (TARGET, 111.0)))
    assert logged(state2)["hit"] is False


def test_resolves_inside_the_slack_window(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), ("2026-11-14", 108.0), ("2026-11-16", 120.0)))
    e = logged(state)
    assert (e["actual"], e["actualDate"], e["hit"]) == (108.0, "2026-11-14", True)


def test_waits_while_no_close_reaches_the_target(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    state["changed"] = False
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), ("2026-11-14", 108.0)))
    assert logged(state)["actual"] is None and not logged(state).get("final") and state["changed"] is False


def test_no_close_in_the_slack_window_is_finalised_and_never_retried(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), ("2026-11-09", 101.0), ("2026-11-17", 120.0)))
    e = logged(state)
    assert e["actual"] is None and e["hit"] is None and e["actualDate"] is None and e["final"] is True
    state["changed"] = False
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), (TARGET, 105.0), ("2026-11-17", 120.0)))
    assert logged(state)["actual"] is None and state["changed"] is False
    assert ft.own_track(state, "usd") == []


def test_restated_history_never_changes_a_resolved_entry(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), (TARGET, 105.0), ("2026-11-16", 120.0)))
    before = json.loads(json.dumps(state["records"]))
    track_before = ft.own_track(state, "usd")
    state["changed"] = False
    restated = series_of((BASIS, 100.0), (TARGET, 50.0), ("2026-11-16", 120.0))
    ft.resolve_pending(state, "usd", restated)
    assert state["records"] == before and state["changed"] is False
    assert ft.own_track(state, "usd") == track_before
    assert track_before == [entry(BASIS, 105.0, True)]


def test_corrupt_archive_keeps_the_previous_track(tmp_path):
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "forecast-log.json").write_text("{not json", encoding="utf-8")
    logs = []
    state = ft.open_state(tmp_path, logs.append)
    previous = {"track": [entry("2026-11-01"), entry("2026-10-25", 95.0)]}
    track = ft.build_track(state, "usd", [{"date": BASIS, "price": 100.0}], previous, logs.append)
    assert track == [entry("2026-11-01"), entry("2026-10-25", 95.0)]
    ft.record_forecast(state, make_doc())
    assert ft.flush(state, logs.append) is True
    assert (folder / "forecast-log.json.corrupt").read_text() == "{not json"


def test_track_shape_order_and_cap(tmp_path):
    state = fresh_state(tmp_path)
    for i in range(15):
        day = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        target = (date(2026, 1, 8) + timedelta(days=i)).isoformat()
        state["records"][day] = {"date": day, "codes": {"usd": {
            "target": target, "low": 90.0, "likely": 100.0, "high": 110.0,
            "actual": 100.0 + i, "actualDate": target, "hit": True}}}
    state["records"]["2026-02-01"] = {"date": "2026-02-01", "codes": {"usd": {
        "target": "2026-02-08", "low": 90.0, "likely": 100.0, "high": 110.0,
        "actual": None, "actualDate": None, "hit": None}}}
    track = ft.build_track(state, "usd", [{"date": "2026-02-01", "price": 100.0}], None)
    assert len(track) == 12
    assert [t["basisDate"] for t in track] == sorted((t["basisDate"] for t in track), reverse=True)
    assert track[0]["basisDate"] == "2026-01-15" and track[-1]["basisDate"] == "2026-01-04"
    assert all(list(t) == list(ft.TRACK_KEYS) for t in track)
    assert track[0] == {"basisDate": "2026-01-15", "target": "2026-01-22", "likely": 100.0, "low": 90.0,
                        "high": 110.0, "actual": 114.0, "hit": True}


def test_published_values_win_over_the_archive_in_the_merge(tmp_path):
    state = fresh_state(tmp_path)
    state["records"]["2026-01-01"] = {"date": "2026-01-01", "codes": {"usd": {
        "target": "2026-01-08", "low": 90.0, "likely": 100.0, "high": 110.0,
        "actual": 105.0, "actualDate": "2026-01-08", "hit": True}}}
    previous = {"track": [entry("2026-01-01", 99.0), entry("2025-12-25", 97.0)]}
    track = ft.build_track(state, "usd", [{"date": "2026-01-02", "price": 100.0}], previous)
    assert [(t["basisDate"], t["actual"]) for t in track] == [("2026-01-01", 99.0), ("2025-12-25", 97.0)]


def test_without_state_the_previous_track_is_kept():
    previous = {"track": [entry("2026-01-01"), {"junk": 1}]}
    assert ft.build_track(None, "usd", [], previous) == [entry("2026-01-01")]
    assert ft.build_track(None, "usd", [], None) == []
    ft.record_forecast(None, make_doc())
    assert ft.flush(None) is False


def test_an_exception_is_scoped_to_its_code_and_falls_back(tmp_path, monkeypatch):
    state = fresh_state(tmp_path)
    logs = []

    def boom(*_args):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(ft, "resolve_pending", boom)
    previous = {"track": [entry("2026-01-01")]}
    assert ft.build_track(state, "usd", [{"date": BASIS, "price": 100.0}], previous, logs.append) == [entry("2026-01-01")]
    assert ft.build_track(state, "eur", [{"date": BASIS, "price": 100.0}], previous, logs.append) == [entry("2026-01-01")]
    ft.record_forecast(state, make_doc(), logs.append)
    assert logs == ["ai: track skipped: RuntimeError"] * 2
    assert state["dead"] is False
    assert ft.flush(state, logs.append) is True
    assert (tmp_path / "archive" / "forecast-log.json").exists()


def test_flush_writes_only_when_something_changed(tmp_path, monkeypatch):
    calls = []
    real = ft.archive_store.write
    monkeypatch.setattr(ft.archive_store, "write", lambda *a, **k: calls.append(1) or real(*a, **k))
    state = fresh_state(tmp_path)
    assert ft.flush(state) is False and calls == []
    ft.record_forecast(state, make_doc())
    assert ft.flush(state) is True and len(calls) == 1
    assert ft.flush(state) is False and len(calls) == 1
