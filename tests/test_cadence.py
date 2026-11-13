import datetime
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import cadence as c

TEHRAN = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
DATES = {
    "saturday": datetime.date(2026, 11, 14),
    "sunday": datetime.date(2026, 11, 15),
    "monday": datetime.date(2026, 11, 16),
    "tuesday": datetime.date(2026, 11, 17),
    "wednesday": datetime.date(2026, 11, 18),
    "thursday": datetime.date(2026, 11, 19),
    "friday": datetime.date(2026, 11, 20),
}
WEEKDAY_NUMBERS = {
    "saturday": 5, "sunday": 6, "monday": 0, "tuesday": 1,
    "wednesday": 2, "thursday": 3, "friday": 4,
}
SAT_TO_WED = ["saturday", "sunday", "monday", "tuesday", "wednesday"]
SAT_WED_EDGES = [
    ("06:59", c.NIGHT),
    ("07:00", c.MID),
    ("08:59", c.MID),
    ("09:00", c.PEAK),
    ("18:59", c.PEAK),
    ("19:00", c.MID),
    ("22:59", c.MID),
    ("23:00", c.NIGHT),
    ("00:00", c.NIGHT),
]
THURSDAY_EDGES = [
    ("06:59", c.NIGHT),
    ("07:00", c.MID),
    ("09:00", c.PEAK),
    ("12:59", c.PEAK),
    ("13:00", c.MID),
    ("22:59", c.MID),
    ("23:00", c.NIGHT),
]


def at(weekday_name, hhmm):
    hour, minute = (int(part) for part in hhmm.split(":"))
    day = DATES[weekday_name.lower()]
    local = datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=TEHRAN)
    return int(local.timestamp())


def test_helper_weekdays_match_names():
    for name, number in WEEKDAY_NUMBERS.items():
        assert DATES[name].weekday() == number, name


def test_helper_is_tehran_local():
    assert at("saturday", "00:00") == int(
        datetime.datetime(2026, 11, 13, 20, 30, tzinfo=datetime.timezone.utc).timestamp()
    )


@pytest.mark.parametrize("day", SAT_TO_WED)
@pytest.mark.parametrize("hhmm,expected", SAT_WED_EDGES)
def test_saturday_to_wednesday_edges(day, hhmm, expected):
    assert c.tier(at(day, hhmm)) == expected


@pytest.mark.parametrize("hhmm,expected", THURSDAY_EDGES)
def test_thursday_edges(hhmm, expected):
    assert c.tier(at("thursday", hhmm)) == expected


@pytest.mark.parametrize("hour", range(24))
def test_friday_is_night_all_day(hour):
    assert c.tier(at("friday", f"{hour:02d}:00")) == c.NIGHT


def test_saturday_early_morning_continues_friday_night():
    assert c.tier(at("saturday", "00:00")) == c.NIGHT
    assert c.tier(at("saturday", "06:59")) == c.NIGHT


def test_tier_seconds_by_tier():
    assert c.tier_seconds("peak", 90) == 90
    assert c.tier_seconds("mid", 90) == 180
    assert c.tier_seconds("night", 90) == 300


def test_night_seconds_below_stale_rule():
    assert c.NIGHT_SECONDS < 900


def test_poll_seconds_by_tier():
    assert c.poll_seconds("peak") == 15
    assert c.poll_seconds("mid") == 30
    assert c.poll_seconds("night") == 60


def test_poll_seconds_unknown_falls_back_to_peak():
    assert c.poll_seconds("unknown") == 15


def test_local_time_offset_is_plus_three_thirty():
    utc_zero = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
    local = c.local_time(0)
    assert local - utc_zero == datetime.timedelta(hours=3, minutes=30)
    assert (local.hour, local.minute) == (3, 30)


@pytest.mark.parametrize("name", SAT_TO_WED + ["thursday", "friday"])
@pytest.mark.parametrize("hhmm", ["00:00", "07:00", "09:00", "13:00", "19:00", "23:00"])
def test_tier_same_for_int_and_float_epochs(name, hhmm):
    epoch = at(name, hhmm)
    assert c.tier(epoch) == c.tier(float(epoch))


def epoch(day, clock):
    hour, minute = (int(part) for part in clock.split(":"))
    local = datetime.datetime.combine(DATES[day], datetime.time(hour, minute), TEHRAN)
    return int(local.timestamp())


@pytest.mark.parametrize("day", SAT_TO_WED)
@pytest.mark.parametrize("clock,expected", [
    ("07:59", False), ("08:00", True), ("12:30", True), ("16:59", True), ("17:00", False), ("23:00", False),
])
def test_window_open_saturday_to_wednesday(day, clock, expected):
    assert c.in_window(epoch(day, clock)) is expected


@pytest.mark.parametrize("day", ["thursday", "friday"])
@pytest.mark.parametrize("clock", ["08:00", "10:00", "16:59"])
def test_window_closed_thursday_and_friday(day, clock):
    assert c.in_window(epoch(day, clock)) is False
