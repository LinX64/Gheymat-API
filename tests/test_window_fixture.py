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


def test_fixture_friday_open_only_in_night_slots():
    fridays = [
        case for case in CASES
        if datetime.datetime.fromtimestamp(case["epoch"], TEHRAN).weekday() == FRIDAY
    ]
    assert fridays
    for case in fridays:
        local = datetime.datetime.fromtimestamp(case["epoch"], TEHRAN)
        in_slot = any(
            local.hour == h and m <= local.minute < m + 5 for h, m in c.NIGHT_SLOTS + c.FRIDAY_SLOTS
        )
        assert case["open"] == in_slot, case


def test_fixture_has_night_slot_edges_on_friday_and_thursday():
    edges = {case["epoch"]: case["open"] for case in CASES}
    for day in (14, 19, 20):
        for hour, minute in ((20, 30), (23, 30)):
            start = int(datetime.datetime(2026, 11, day, hour, minute, tzinfo=TEHRAN).timestamp())
            assert edges[start - 1] is False
            assert edges[start] is True
            assert edges[start + 300 - 1] is True
            assert edges[start + 300] is False


def test_fixture_has_thursday_1300_edge():
    edges = {case["epoch"]: case["open"] for case in CASES}
    assert edges[THURSDAY_1300] is False
    assert edges[THURSDAY_1300 - 1] is True
    assert edges[THURSDAY_1300 + 1] is False


def test_fixture_is_sorted_and_unique():
    epochs = [case["epoch"] for case in CASES]
    assert epochs == sorted(set(epochs))


def test_fixture_has_friday_noon_slot_edges():
    edges = {case["epoch"]: case["open"] for case in CASES}
    start = int(datetime.datetime(2026, 11, 20, 12, 0, tzinfo=TEHRAN).timestamp())
    assert edges[start - 1] is False
    assert edges[start] is True
    assert edges[start + 299] is True
    assert edges[start + 300] is False


def test_fixture_saturday_noon_is_day_window_not_a_slot():
    saturday_noon = int(datetime.datetime(2026, 11, 14, 12, 0, tzinfo=TEHRAN).timestamp())
    assert {case["epoch"]: case["open"] for case in CASES}[saturday_noon] is True
    assert c.in_night_slot(saturday_noon) is False
