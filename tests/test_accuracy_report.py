import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import accuracy_report as ar
import forecast_track
import night_export

CLOSED = datetime(2026, 11, 20, 8, 30, tzinfo=timezone.utc).timestamp()
NEAR_OPEN = datetime(2026, 11, 21, 4, 26, tzinfo=timezone.utc).timestamp()
KEY = base64.b64encode(bytes(range(32))).decode()


def runner(stdout="0", code=0, raises=None):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if raises:
            raise raises
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")
    run.calls = calls
    return run


def read_out(path):
    return dict(line.split("=", 1) for line in Path(path).read_text().splitlines())


def series(prices, start=datetime(2026, 1, 1)):
    return {(start + timedelta(days=i)).date().isoformat(): [p, p] for i, p in enumerate(prices)}


def test_artifact_name_uses_tehran_date():
    assert ar.artifact_name(CLOSED) == "report-2026-11-20"
    late = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc).timestamp()
    assert ar.artifact_name(late) == "report-2026-11-21"


def test_check_skips_when_artifact_exists(tmp_path):
    out = tmp_path / "o"
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(out)}
    fake = runner("1")
    assert ar.check(env, CLOSED, lambda *_: None, fake) is True
    assert read_out(out) == {"skip": "true", "name": "report-2026-11-20"}
    assert "report-2026-11-20" in fake.calls[0][2]


def test_check_runs_when_artifact_missing(tmp_path):
    out = tmp_path / "o"
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(out)}
    assert ar.check(env, CLOSED, lambda *_: None, runner("0")) is False
    assert read_out(out)["skip"] == "false"


def test_check_skips_when_lookup_fails(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "o")}
    assert ar.check(env, CLOSED, lambda *_: None, runner(raises=OSError())) is True
    assert ar.check(env, CLOSED, lambda *_: None, runner("x", code=1)) is True


def test_force_ignores_existing_artifact(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "o"), "REPORT_FORCE": "true"}
    fake = runner("1")
    assert ar.check(env, CLOSED, lambda *_: None, fake) is False
    assert fake.calls == []


def test_force_does_not_override_window(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "o"), "REPORT_FORCE": "true"}
    assert ar.check(env, NEAR_OPEN, lambda *_: None, runner("0")) is True


def test_check_skips_when_window_opens_soon(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "o")}
    fake = runner("0")
    assert ar.check(env, NEAR_OPEN, lambda *_: None, fake) is True
    assert fake.calls == []


OPEN_AT = datetime(2026, 11, 21, 4, 30, tzinfo=timezone.utc).timestamp()


def test_check_gap_boundary(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "o")}
    assert ar.check(env, OPEN_AT - 299, lambda *_: None, runner("0")) is True
    assert ar.check(env, OPEN_AT - 301, lambda *_: None, runner("0")) is False


def test_run_gap_boundary(monkeypatch, tmp_path):
    stub_eval(monkeypatch)
    monkeypatch.setattr(ar, "fetch_daily", lambda env, work, seconds=60: daily_of(["alpha"]))
    env = {"GITHUB_OUTPUT": str(tmp_path / "o"), "REPORT_OUT_DIR": str(tmp_path / "out")}
    logs = []
    assert ar.run(env, OPEN_AT - 299, logs.append, lambda: 0.0) == 0
    assert logs == ["report: skipped (window close)"]
    logs.clear()
    assert ar.run(env, OPEN_AT - 301, logs.append, lambda: 0.0) == 0
    assert any(line.startswith("report: codes=1") for line in logs)


def test_check_skips_when_not_keyed(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "o"), "REPORT_KEYED": "false"}
    fake = runner("0")
    logs = []
    assert ar.check(env, CLOSED, logs.append, fake) is True
    assert fake.calls == [] and logs == ["report not exported (no key)"]
    env["REPORT_KEYED"] = "true"
    assert ar.check(env, CLOSED, lambda *_: None, runner("0")) is False


def test_run_exits_at_once_when_window_close(monkeypatch, tmp_path):
    monkeypatch.setattr(ar, "fetch_daily", lambda *a, **k: pytest.fail("fetched"))
    logs = []
    assert ar.run({"GITHUB_OUTPUT": str(tmp_path / "o")}, NEAR_OPEN, logs.append, lambda: 0.0) == 0
    assert read_out(tmp_path / "o") == {"report": "false"}


def test_quality_clean():
    q = ar.quality(series([100 + i for i in range(30)]))
    assert q["issues"] is False and q["days"] == 30


def test_quality_gap():
    s = series([100, 101])
    s["2026-02-01"] = [102, 102]
    q = ar.quality(s)
    assert q["gaps"] == 1 and q["issues"]


def test_quality_bad_closes_and_dates():
    s = series([100, 0, 101])
    s["2026-01-10"] = [None, None]
    s["nope"] = [1, 1]
    q = ar.quality(s)
    assert q["badCloses"] == 2 and q["badDates"] == 1


def test_quality_jump():
    q = ar.quality(series([100, 130, 131]))
    assert q["jumps"] == 1
    assert ar.quality(series([100, 124]))["jumps"] == 0


def test_quality_flat_runs():
    assert ar.quality(series([5] * 5 + [6]))["flatRuns"] == 0
    assert ar.quality(series([5] * 6))["flatRuns"] == 1
    assert ar.quality(series([5] * 13))["flatRuns"] == 1


def test_cross_check_counts():
    daily = {"alpha": {"2026-01-01": [100, 100], "2026-01-02": [100, 100], "2026-01-03": [100, 100]},
             "beta": {"2026-01-01": [50, 50]}}
    live = {"2026-01-01": {"alpha": 100.0, "beta": 50.0}, "2026-01-02": {"alpha": 101.5},
            "2026-01-03": {"alpha": 90.0, "gamma": 5.0}, "2026-01-04": {"alpha": 1.0}}
    out = ar.cross_check(daily, live)
    assert out["compared"] == 4
    assert out["over1"] == 2 and out["over3"] == 1
    assert out["codes"]["alpha"]["2026-01-02"] == pytest.approx(abs(100 / 101.5 - 1))


def test_cross_check_empty():
    assert ar.cross_check({"alpha": {}}, {})["compared"] == 0


def write_track(directory, env, records):
    master = base64.b64decode(env["GHEYMAT_PAYLOAD_KEY"])
    Path(directory).mkdir(exist_ok=True)
    (Path(directory) / forecast_track.FILE_NAME).write_bytes(
        forecast_track._encrypt(forecast_track._derive(master), records))


def test_track_stats(tmp_path):
    env = {"GHEYMAT_PAYLOAD_KEY": KEY}
    write_track(tmp_path, env, [
        {"date": "2026-01-01", "codes": {"alpha": {"actual": 5, "hit": True}, "beta": {"actual": 5, "hit": False}}},
        {"date": "2026-01-08", "codes": {"alpha": {"actual": None, "hit": None}}},
        {"date": "2026-01-15", "codes": {"alpha": {"actual": 7, "hit": True}}},
    ])
    out = ar.track_stats(tmp_path, env)
    assert out["scored"] == 3 and out["hits"] == 2
    assert out["rate"] == pytest.approx(2 / 3)
    assert out["codes"]["alpha"] == {"scored": 2, "hits": 2}


def test_track_stats_missing_or_wrong_key(tmp_path):
    assert ar.track_stats(tmp_path, {"GHEYMAT_PAYLOAD_KEY": KEY})["scored"] == 0
    write_track(tmp_path, {"GHEYMAT_PAYLOAD_KEY": KEY}, [{"date": "d", "codes": {"a": {"actual": 1, "hit": True}}}])
    other = base64.b64encode(bytes(32)).decode()
    assert ar.track_stats(tmp_path, {"GHEYMAT_PAYLOAD_KEY": other})["scored"] == 0


def fake_live(monkeypatch, data):
    mod = types.SimpleNamespace(read=lambda d, k: data, derive_key=lambda env: b"k" * 32, FILE_NAME="live-close.bin")
    monkeypatch.setitem(sys.modules, "live_close", mod)


def test_live_closes_uses_frozen_interface(monkeypatch):
    fake_live(monkeypatch, {"2026-01-01": {"alpha": 1.0}})
    assert ar.live_closes("x", {}) == {"2026-01-01": {"alpha": 1.0}}
    monkeypatch.setitem(sys.modules, "live_close", types.SimpleNamespace(
        read=lambda d, k: 1 / 0, derive_key=lambda e: b"k", FILE_NAME="x"))
    assert ar.live_closes("x", {}) == {}


def daily_of(codes):
    return {"codes": {c: series([100000 + (i % 7) * 1111 for i in range(60)]) for c in codes}}


def stub_eval(monkeypatch, passing=True):
    monkeypatch.setattr(ar, "evaluate_code", lambda code, s, t, g: {
        "diag": {"coverage": 0.8, "weeks": 10}, "pass": passing, "reason": None, "compare": {}, "regime": None})


def test_report_round_trip_and_clean_logs(monkeypatch, tmp_path):
    stub_eval(monkeypatch)
    fake_live(monkeypatch, {"2026-01-01": {"alpha": 123456.0}})
    monkeypatch.setattr(ar, "fetch_daily", lambda env, work, seconds=60: daily_of(["alpha", "beta"]))
    private = tmp_path / "owner.key"
    public = night_export.keygen(private)
    env = {"GHEYMAT_OWNER_PUBKEY": public, "GHEYMAT_PAYLOAD_KEY": KEY, "REPORT_OUT_DIR": str(tmp_path / "out"),
           "REPORT_FEED_DIR": str(tmp_path / "feed"), "GITHUB_OUTPUT": str(tmp_path / "o"),
           "GITHUB_REPOSITORY": "owner/repo"}
    logs = []
    assert ar.main([], env, CLOSED, logs.append, lambda: 0.0) == 0
    assert read_out(tmp_path / "o") == {"report": "true"}
    sealed = (tmp_path / "out" / "report.bin").read_bytes()
    body = json.loads(night_export.decrypt_report(private.read_bytes(), sealed))
    assert set(body["codes"]) == {"alpha", "beta"}
    assert body["partial"] is False and body["archiveVsLive"]["compared"] == 1
    assert "alpha" not in sealed.decode()
    text = "\n".join(logs)
    assert "alpha" not in text and "beta" not in text
    assert "http" not in text and "github.com" not in text
    assert not re.search(r"\d{4,}", text)
    allowed = re.compile(r"report: codes=\d+ passing=\d+ quality_issues=\d+ live_scored=\d+ "
                         r"seconds=\d+ partial=(yes|no)|report: skipped \([a-z ]+\)|report not exported \(no key\)|"
                         r"report: [a-z ]+ failed \(\w+\)")
    assert all(allowed.fullmatch(line) for line in logs), logs
    assert "codes=2 passing=2 quality_issues=0 live_scored=0" in text
    assert "partial=no" in text


def test_no_owner_key_computes_but_does_not_export(monkeypatch, tmp_path):
    stub_eval(monkeypatch)
    monkeypatch.setattr(ar, "fetch_daily", lambda env, work, seconds=60: daily_of(["alpha"]))
    env = {"REPORT_OUT_DIR": str(tmp_path / "out"), "GITHUB_OUTPUT": str(tmp_path / "o")}
    logs = []
    assert ar.run(env, CLOSED, logs.append, lambda: 0.0) == 0
    assert "report not exported (no key)" in logs
    assert not (tmp_path / "out").exists()
    assert read_out(tmp_path / "o") == {"report": "false"}


def test_time_budget_marks_partial(monkeypatch, tmp_path):
    stub_eval(monkeypatch)
    monkeypatch.setattr(ar, "fetch_daily", lambda env, work, seconds=60: daily_of(["a", "b", "c", "d"]))
    ticks = iter(range(0, 10000, 75))
    private = tmp_path / "k"
    env = {"GHEYMAT_OWNER_PUBKEY": night_export.keygen(private), "REPORT_OUT_DIR": str(tmp_path / "out"),
           "GITHUB_OUTPUT": str(tmp_path / "o")}
    logs = []
    assert ar.run(env, CLOSED, logs.append, lambda: float(next(ticks))) == 0
    body = json.loads(night_export.decrypt_report(private.read_bytes(), (tmp_path / "out" / "report.bin").read_bytes()))
    assert body["partial"] is True and 0 < len(body["codes"]) < 4
    assert any("partial=yes" in line for line in logs)


def test_failures_leave_exit_code_zero(monkeypatch, tmp_path):
    env = {"GITHUB_OUTPUT": str(tmp_path / "o")}
    logs = []
    monkeypatch.setattr(ar, "fetch_daily", lambda *a, **k: 1 / 0)
    assert ar.main([], env, CLOSED, logs.append, lambda: 0.0) == 0
    monkeypatch.setattr(ar, "fetch_daily", lambda *a, **k: daily_of(["alpha"]))
    monkeypatch.setattr(ar, "evaluate_code", lambda *a: 1 / 0)
    monkeypatch.setattr(ar, "build", lambda *a, **k: 1 / 0)
    assert ar.main([], env, CLOSED, logs.append, lambda: 0.0) == 0
    monkeypatch.setattr(ar, "fetch_daily", lambda *a, **k: (_ for _ in ()).throw(SystemExit("secret text")))
    assert ar.main([], env, CLOSED, logs.append, lambda: 0.0) == 0
    assert ar.main(["--check"], {"GITHUB_OUTPUT": str(tmp_path / "p")}, CLOSED, logs.append, lambda: 0.0) == 0
    assert all("secret" not in line for line in logs)


def test_code_failure_logs_type_only(monkeypatch, tmp_path):
    monkeypatch.setattr(ar, "fetch_daily", lambda *a, **k: daily_of(["alpha"]))
    monkeypatch.setattr(ar, "evaluate_code", lambda *a: (_ for _ in ()).throw(ValueError("alpha 12345")))
    logs = []
    ar.run({"GITHUB_OUTPUT": str(tmp_path / "o")}, CLOSED, logs.append, lambda: 0.0)
    assert "report: code evaluation failed (ValueError)" in logs
    assert all("12345" not in line for line in logs)


def test_evaluate_code_real_small_series():
    s = series([100 * (1 + 0.002 * ((i * 7) % 11 - 5)) + i * 0.1 for i in range(420)])
    today = datetime(2027, 2, 25).date()
    out = ar.evaluate_code("alpha", s, today, "2027-02-25T00:00:00Z")
    assert set(out) == {"diag", "pass", "reason", "compare", "regime"}
    json.dumps(out, default=str)


def test_invalid_owner_key_skips_before_any_work(monkeypatch, tmp_path):
    monkeypatch.setattr(ar, "fetch_daily", lambda *a, **k: pytest.fail("fetched"))
    logs = []
    env = {"GHEYMAT_OWNER_PUBKEY": "not-a-key", "GITHUB_OUTPUT": str(tmp_path / "o")}
    assert ar.run(env, CLOSED, logs.append, lambda: 0.0) == 0
    assert logs == ["report: skipped (invalid key)"]


def test_log_summary_carries_no_rate():
    assert "coverage=" not in pathlib.Path(ar.__file__).read_text(encoding="utf-8")
