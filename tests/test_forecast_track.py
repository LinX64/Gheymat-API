import base64
import importlib.util
import json
import pathlib
import sys
from datetime import date, timedelta

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("forecast_track", TOOLS / "forecast_track.py")
ft = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ft)

MASTER = bytes(range(32))
KEY_B64 = base64.b64encode(MASTER).decode()
OTHER_B64 = base64.b64encode(bytes(range(1, 33))).decode()
LOG_FILE = "forecast-log.bin"
BASIS = "2026-11-08"
TARGET = "2026-11-15"


@pytest.fixture(autouse=True)
def key_env(monkeypatch):
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", KEY_B64)
    monkeypatch.setattr(ft, "_warned", False)


def read_log(root, master=MASTER):
    key = ft._derive(master)
    return ft._decrypt(key, (pathlib.Path(root) / LOG_FILE).read_bytes())


def write_log(root, records, master=MASTER):
    (pathlib.Path(root) / LOG_FILE).write_bytes(ft._encrypt(ft._derive(master), records))


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
    saved = read_log(tmp_path)
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
    (tmp_path / LOG_FILE).write_bytes(b"not a valid log")
    logs = []
    state = ft.open_state(tmp_path, logs.append)
    previous = {"track": [entry("2026-11-01"), entry("2026-10-25", 95.0)]}
    track = ft.build_track(state, "usd", [{"date": BASIS, "price": 100.0}], previous, logs.append)
    assert track == [entry("2026-11-01"), entry("2026-10-25", 95.0)]
    ft.record_forecast(state, make_doc())
    assert ft.flush(state, logs.append) is True
    assert (tmp_path / (LOG_FILE + ".corrupt")).read_bytes() == b"not a valid log"
    assert len(read_log(tmp_path)) == 1


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
    assert (tmp_path / LOG_FILE).exists()


def test_flush_writes_only_when_something_changed(tmp_path, monkeypatch):
    calls = []
    real = ft._write_atomic
    monkeypatch.setattr(ft, "_write_atomic", lambda *a, **k: calls.append(1) or real(*a, **k))
    state = fresh_state(tmp_path)
    assert ft.flush(state) is False and calls == []
    ft.record_forecast(state, make_doc())
    assert ft.flush(state) is True and len(calls) == 1
    assert ft.flush(state) is False and len(calls) == 1


def test_file_on_disk_is_ciphertext(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc("usd", likely=123456.0, low=111111.0, high=134567.0))
    assert ft.flush(state) is True
    raw = (tmp_path / LOG_FILE).read_bytes()
    raw.decode("ascii")
    with pytest.raises(ValueError):
        json.loads(raw)
    decoded = base64.b64decode(raw, validate=True)
    for needle in (b"123456", b"111111", b"usd", BASIS.encode()):
        assert needle not in raw and needle not in decoded
    assert not (tmp_path / "archive").exists()


def test_round_trip_across_a_reopen(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc("usd"))
    ft.record_forecast(state, make_doc("eur", likely=200.0, low=180.0, high=220.0))
    ft.resolve_pending(state, "usd", series_of((BASIS, 100.0), (TARGET, 105.0)))
    assert ft.flush(state) is True
    again = fresh_state(tmp_path)
    assert again["loaded"] == 1 and again["records"] == state["records"]
    assert ft.own_track(again, "usd") == [entry(BASIS, 105.0, True)]


@pytest.mark.parametrize("value", [None, "", "%%%", base64.b64encode(b"short").decode()])
def test_no_usable_key_turns_the_log_off_and_keeps_the_previous_track(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("GHEYMAT_PAYLOAD_KEY")
    else:
        monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", value)
    logs = []
    assert ft.open_state(tmp_path, logs.append) is None
    assert ft.open_state(tmp_path, logs.append) is None
    assert logs == ["ai: track off (no key)"]
    previous = {"track": [entry("2026-11-01")]}
    assert ft.build_track(None, "usd", [], previous) == [entry("2026-11-01")]
    assert not (tmp_path / LOG_FILE).exists()


def test_explicit_env_overrides_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("GHEYMAT_PAYLOAD_KEY")
    assert ft.open_state(tmp_path, lambda *_: None, {"GHEYMAT_PAYLOAD_KEY": KEY_B64}) is not None


def test_wrong_key_is_backed_up_as_ciphertext_and_never_shrinks_the_track(tmp_path):
    write_log(tmp_path, [{"date": "2026-10-01", "codes": {"usd": {"target": "2026-10-08", "likely": 77777.0}}}],
              master=bytes(range(1, 33)))
    original = (tmp_path / LOG_FILE).read_bytes()
    logs = []
    state = ft.open_state(tmp_path, logs.append)
    assert state["records"] == {} and state["loaded"] == 0
    previous = {"track": [entry("2026-11-01"), entry("2026-10-25", 95.0)]}
    assert ft.build_track(state, "usd", [{"date": BASIS, "price": 100.0}], previous) == previous["track"]
    assert (tmp_path / (LOG_FILE + ".corrupt")).read_bytes() == original
    assert b"77777" not in original and logs == ["ai: track log unreadable, starting empty"]
    ft.record_forecast(state, make_doc())
    assert ft.flush(state) is True
    assert [r["date"] for r in read_log(tmp_path)] == [BASIS]
    assert (tmp_path / (LOG_FILE + ".corrupt")).read_bytes() == original


def test_a_log_that_is_not_a_list_of_records_is_treated_as_corrupt(tmp_path):
    (tmp_path / LOG_FILE).write_bytes(ft._encrypt(ft._derive(MASTER), {"date": "x"}))
    state = ft.open_state(tmp_path, lambda *_: None)
    assert state["records"] == {}
    assert (tmp_path / (LOG_FILE + ".corrupt")).exists()


def test_atomic_write_leaves_no_temp_file(tmp_path, monkeypatch):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    assert ft.flush(state) is True
    assert sorted(p.name for p in tmp_path.iterdir()) == [LOG_FILE]
    ft.record_forecast(state, make_doc("eur"))

    def boom(*_a):
        raise OSError("disk")
    monkeypatch.setattr(ft.os, "replace", boom)
    before = (tmp_path / LOG_FILE).read_bytes()
    assert ft.flush(state, lambda *_: None) is False
    assert sorted(p.name for p in tmp_path.iterdir()) == [LOG_FILE]
    assert (tmp_path / LOG_FILE).read_bytes() == before


def test_refuses_to_write_fewer_records_than_were_loaded(tmp_path):
    write_log(tmp_path, [{"date": "2026-10-01", "codes": {}}, {"date": "2026-10-02", "codes": {}}])
    before = (tmp_path / LOG_FILE).read_bytes()
    state = fresh_state(tmp_path)
    assert state["loaded"] == 2
    del state["records"]["2026-10-01"]
    state["changed"] = True
    logs = []
    assert ft.flush(state, logs.append) is False
    assert logs == ["ai: track log kept (refusing to shrink)"]
    assert (tmp_path / LOG_FILE).read_bytes() == before


def test_plain_leftover_is_imported_then_deleted(tmp_path):
    folder = tmp_path / "archive"
    folder.mkdir()
    record = {"date": "2026-10-01", "codes": {"usd": {"target": "2026-10-08", "low": 1.0, "likely": 2.0,
                                                      "high": 3.0, "actual": None, "actualDate": None, "hit": None}}}
    (folder / "forecast-log.json").write_text(json.dumps([record]), encoding="utf-8")
    (folder / "forecast-log.json.corrupt").write_text("old", encoding="utf-8")
    state = fresh_state(tmp_path)
    assert state["records"] == {"2026-10-01": record} and state["changed"] is True
    assert ft.flush(state) is True
    assert read_log(tmp_path) == [record]
    assert not (folder / "forecast-log.json").exists() and not (folder / "forecast-log.json.corrupt").exists()


def test_plain_leftover_is_dropped_without_import_when_the_encrypted_log_exists(tmp_path):
    write_log(tmp_path, [{"date": "2026-10-05", "codes": {}}])
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "forecast-log.json").write_text(json.dumps([{"date": "2026-10-01", "codes": {}}]), encoding="utf-8")
    state = fresh_state(tmp_path)
    assert list(state["records"]) == ["2026-10-05"]
    assert not (folder / "forecast-log.json").exists()


def test_failed_plain_deletion_is_logged_and_does_not_block(tmp_path, monkeypatch):
    write_log(tmp_path, [])
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "forecast-log.json").write_text("[]", encoding="utf-8")

    def boom(self, missing_ok=False):
        raise OSError("busy")
    monkeypatch.setattr(pathlib.Path, "unlink", boom)
    logs = []
    assert ft.open_state(tmp_path, logs.append) is not None
    assert logs and all(m == "ai: track cleanup incomplete" for m in logs)


def test_nonce_differs_between_two_writes_of_the_same_content(tmp_path):
    state = fresh_state(tmp_path)
    ft.record_forecast(state, make_doc())
    assert ft.flush(state) is True
    first = base64.b64decode((tmp_path / LOG_FILE).read_bytes())
    state["changed"] = True
    assert ft.flush(state) is True
    second = base64.b64decode((tmp_path / LOG_FILE).read_bytes())
    assert first[:ft.NONCE_LEN] != second[:ft.NONCE_LEN] and first != second
    assert read_log(tmp_path) == [state["records"][BASIS]]


def test_unreadable_log_file_skips_the_track_for_this_run(tmp_path, monkeypatch):
    write_log(tmp_path, [{"date": "2026-10-01", "codes": {}}])
    real = ft.Path.read_bytes

    def boom(self):
        if self.name == LOG_FILE:
            raise OSError("io")
        return real(self)
    monkeypatch.setattr(ft.Path, "read_bytes", boom)
    assert ft.open_state(tmp_path, lambda *_: None) is None


def test_failed_backup_skips_the_track_for_this_run(tmp_path, monkeypatch):
    (tmp_path / LOG_FILE).write_bytes(b"not a valid log")
    real = ft.Path.write_bytes

    def boom(self, data):
        if self.name.endswith(".corrupt"):
            raise OSError("io")
        return real(self, data)
    monkeypatch.setattr(ft.Path, "write_bytes", boom)
    assert ft.open_state(tmp_path, lambda *_: None) is None
    assert (tmp_path / LOG_FILE).read_bytes() == b"not a valid log"


def test_stray_plain_corrupt_file_is_removed_when_the_encrypted_log_exists(tmp_path):
    write_log(tmp_path, [{"date": "2026-10-05", "codes": {}}])
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "forecast-log.json.corrupt").write_text("old", encoding="utf-8")
    fresh_state(tmp_path)
    assert not (folder / "forecast-log.json.corrupt").exists()
