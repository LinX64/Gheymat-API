import datetime
import io
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import cadence
import idle
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
        {"status": "in_progress", "createdAt": stamp(OPEN - watchdog.ACTIVE_WITHIN - 100)},
        {"status": "completed", "createdAt": stamp(OPEN - 10)},
    ]
    watchdog.main({}, OPEN, runner(runs, calls))
    assert calls[-1][0] == "workflow"


def test_watchdog_also_starts_a_run_outside_hours():
    calls = []
    assert watchdog.main({}, SHUT, runner([], calls)) == 0
    assert calls[-1][0] == "workflow"


def test_watchdog_leaves_a_running_idle_run_alone():
    calls = []
    runs = [{"status": "in_progress", "createdAt": stamp(SHUT - 100)}]
    watchdog.main({}, SHUT, runner(runs, calls))
    assert all(call[0] != "workflow" for call in calls)


def test_watchdog_fails_when_listing_fails():
    assert watchdog.main({}, OPEN, lambda argv: (1, "")) == 1


MASTER = {"GITHUB_REF": "refs/heads/master"}


def idle_run(environ, now):
    slept, calls = [], []
    code = idle.main(environ, now, sleep=slept.append, run=lambda argv: calls.append(argv) or 0)
    return code, slept, calls


def test_idle_sleeps_until_the_window_then_starts_the_next_run():
    code, slept, calls = idle_run(MASTER, SHUT)
    assert code == 0
    assert len(slept) == 1 and 0 < slept[0] <= idle.MAX_SLEEP
    assert calls == [["workflow", "run", "gheymat-latest.yml", "--ref", "master"]]


def test_idle_wakes_just_after_the_window_opens():
    opens = int(datetime.datetime(2026, 11, 14, 8, 0, tzinfo=TEHRAN).timestamp())
    code, slept, calls = idle_run(MASTER, opens - 90)
    assert slept == [90 + idle.LATE]


def test_idle_does_not_sleep_inside_the_window():
    code, slept, calls = idle_run(MASTER, OPEN)
    assert slept == [] and len(calls) == 1


def test_idle_off_master_does_nothing():
    code, slept, calls = idle_run({"GITHUB_REF": "refs/heads/develop"}, SHUT)
    assert code == 0 and slept == [] and calls == []


def test_idle_fails_when_dispatch_fails():
    assert idle.main(MASTER, OPEN, sleep=lambda s: None, run=lambda argv: 1) == 1


def test_next_open_after_thursday_noon_is_saturday_eight():
    thursday = int(datetime.datetime(2026, 11, 19, 14, 0, tzinfo=TEHRAN).timestamp())
    saturday = int(datetime.datetime(2026, 11, 21, 8, 0, tzinfo=TEHRAN).timestamp())
    assert cadence.next_open(thursday) == saturday


def test_next_open_after_hours_is_next_morning():
    evening = int(datetime.datetime(2026, 11, 14, 18, 0, tzinfo=TEHRAN).timestamp())
    morning = int(datetime.datetime(2026, 11, 15, 8, 0, tzinfo=TEHRAN).timestamp())
    assert cadence.next_open(evening) == morning
