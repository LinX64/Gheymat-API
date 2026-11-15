import datetime
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import cadence as c

FIXTURE = ROOT / "tests" / "fixtures" / "window_cases.json"
TEHRAN = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
THURSDAY_1300 = int(datetime.datetime(2026, 11, 19, 13, 0, tzinfo=TEHRAN).timestamp())
FRIDAY = 4


def load_cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


CASES = load_cases()


def test_fixture_matches_cadence():
    for case in CASES:
        assert c.in_window(case["epoch"]) == case["open"], case


def test_fixture_has_open_and_closed_cases():
    assert any(case["open"] for case in CASES)
    assert any(not case["open"] for case in CASES)


def test_fixture_has_friday_case():
    fridays = [
        case for case in CASES
        if datetime.datetime.fromtimestamp(case["epoch"], TEHRAN).weekday() == FRIDAY
    ]
    assert fridays
    assert all(not case["open"] for case in fridays)


def test_fixture_has_thursday_1300_edge():
    edges = {case["epoch"]: case["open"] for case in CASES}
    assert edges[THURSDAY_1300] is False
    assert edges[THURSDAY_1300 - 1] is True
    assert edges[THURSDAY_1300 + 1] is False


def test_fixture_is_sorted_and_unique():
    epochs = [case["epoch"] for case in CASES]
    assert epochs == sorted(set(epochs))
