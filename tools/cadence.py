"""Time-of-week publish cadence. Pure functions of the epoch; no I/O.

Tehran has a fixed offset of +03:30 (no daylight saving). The working week runs Saturday to Wednesday,
Thursday is a half day and Friday is the weekend. Tiers only ever lengthen the gap between publishes.
"""
import datetime

TEHRAN_OFFSET = datetime.timedelta(hours=3, minutes=30)
PEAK, MID, NIGHT = "peak", "mid", "night"

# Local-time window edges, hours since midnight, [start, end).
DAY_START = 9            # peak starts
DAY_END = 19             # Saturday to Wednesday: peak ends
THURSDAY_END = 13        # Thursday: peak ends
EVENING_END = 23         # mid ends, night starts
MORNING_START = 7        # night ends, mid starts

MID_SECONDS = 180
NIGHT_SECONDS = 300      # well under the app's 15 minute stale rule
HOT_SECONDS = 600        # stay fast this long after upstream moves outside peak
POLL = {PEAK: 15, MID: 30, NIGHT: 60}

FRIDAY, THURSDAY = 4, 3  # datetime.weekday(): Monday is 0


def local_time(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc) + TEHRAN_OFFSET


def tier(epoch):
    local = local_time(epoch)
    day, hour = local.weekday(), local.hour
    if day == FRIDAY:
        return NIGHT
    if hour >= EVENING_END or hour < MORNING_START:
        return NIGHT
    if hour < DAY_START:
        return MID
    end = THURSDAY_END if day == THURSDAY else DAY_END
    return PEAK if hour < end else MID


def tier_seconds(name, floor):
    """Minimum seconds between publishes in a tier; peak keeps the caller's own cadence."""
    if name == NIGHT:
        return NIGHT_SECONDS
    if name == MID:
        return MID_SECONDS
    return floor


def poll_seconds(name):
    return POLL.get(name, POLL[PEAK])
