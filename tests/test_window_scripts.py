import datetime
import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import cadence
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


def test_next_open_after_thursday_noon_is_saturday_eight():
    thursday = int(datetime.datetime(2026, 11, 19, 14, 0, tzinfo=TEHRAN).timestamp())
    saturday = int(datetime.datetime(2026, 11, 21, 8, 0, tzinfo=TEHRAN).timestamp())
    assert cadence.next_open(thursday) == saturday


def test_next_open_after_hours_is_next_morning():
    evening = int(datetime.datetime(2026, 11, 14, 18, 0, tzinfo=TEHRAN).timestamp())
    morning = int(datetime.datetime(2026, 11, 15, 8, 0, tzinfo=TEHRAN).timestamp())
    assert cadence.next_open(evening) == morning


def test_publish_loop_checks_window_only_at_start():
    source = (pathlib.Path(__file__).resolve().parents[1] / "tools" / "publish_loop.py").read_text()
    assert source.count("cadence.in_window") == 1
