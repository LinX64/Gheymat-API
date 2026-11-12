import datetime

TEHRAN_OFFSET = datetime.timedelta(hours=3, minutes=30)
PEAK, MID, NIGHT = "peak", "mid", "night"

DAY_START = 9
DAY_END = 19
THURSDAY_END = 13
EVENING_END = 23
MORNING_START = 7

MID_SECONDS = 180
NIGHT_SECONDS = 300
HOT_SECONDS = 120
POLL = {PEAK: 15, MID: 30, NIGHT: 60}

FRIDAY, THURSDAY = 4, 3


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
    if name == NIGHT:
        return NIGHT_SECONDS
    if name == MID:
        return MID_SECONDS
    return floor


def poll_seconds(name):
    return POLL.get(name, POLL[PEAK])
