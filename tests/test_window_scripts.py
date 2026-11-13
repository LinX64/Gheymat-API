import datetime
import io
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import watchdog
import window

TEHRAN = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
OPEN = int(datetime.datetime(2026, 11, 14, 10, 0, tzinfo=TEHRAN).timestamp())
SHUT = int(datetime.datetime(2026, 11, 13, 19, 0, tzinfo=TEHRAN).timestamp())


def stamp(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_window_writes_open_output(tmp_path):
    out = tmp_path / "out"
    assert window.main({"GITHUB_OUTPUT": str(out)}, OPEN, io.StringIO()) == 0
    assert out.read_text() == "open=true\n"


def test_window_writes_closed_output_and_says_so(tmp_path):
    out = tmp_path / "out"
    log = io.StringIO()
    assert window.main({"GITHUB_OUTPUT": str(out)}, SHUT, log) == 0
    assert out.read_text() == "open=false\n"
    assert "Outside publishing hours" in log.getvalue()


def test_window_off_switch_is_always_open(tmp_path):
    out = tmp_path / "out"
    window.main({"GITHUB_OUTPUT": str(out), "GHEYMAT_HOURS": "off"}, SHUT, io.StringIO())
    assert out.read_text() == "open=true\n"


def runner(runs, calls):
    def run(argv):
        calls.append(argv)
        if argv[0] == "run":
            return 0, json.dumps(runs)
        return 0, ""
    return run


def test_watchdog_starts_a_run_when_idle():
    calls = []
    assert watchdog.main({}, OPEN, runner([], calls)) == 0
    assert calls[-1] == ["workflow", "run", "gheymat-latest.yml", "--ref", "master"]


def test_watchdog_leaves_an_active_run_alone():
    calls = []
    runs = [{"status": "in_progress", "createdAt": stamp(OPEN - 100)}]
    assert watchdog.main({}, OPEN, runner(runs, calls)) == 0
    assert all(call[0] != "workflow" for call in calls)


def test_watchdog_ignores_old_and_completed_runs():
    calls = []
    runs = [
        {"status": "in_progress", "createdAt": stamp(OPEN - 700)},
        {"status": "completed", "createdAt": stamp(OPEN - 10)},
    ]
    watchdog.main({}, OPEN, runner(runs, calls))
    assert calls[-1][0] == "workflow"


def test_watchdog_does_nothing_outside_hours():
    calls = []
    assert watchdog.main({}, SHUT, runner([], calls)) == 0
    assert calls == []


def test_watchdog_fails_when_listing_fails():
    assert watchdog.main({}, OPEN, lambda argv: (1, "")) == 1
