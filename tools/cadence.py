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

WINDOW_START = 8
WINDOW_END = 17
WINDOW_DAYS = (5, 6, 0, 1, 2, 3)
NIGHT_SLOTS = ((20, 30), (23, 30))
NIGHT_SLOT_MINUTES = 5


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


def in_day_window(epoch):
    local = local_time(epoch)
    day = local.weekday()
    if day not in WINDOW_DAYS:
        return False
    end = THURSDAY_END if day == THURSDAY else WINDOW_END
    return WINDOW_START <= local.hour < end


def in_night_slot(epoch):
    local = local_time(epoch)
    for hour, minute in NIGHT_SLOTS:
        if local.hour == hour and minute <= local.minute < minute + NIGHT_SLOT_MINUTES:
            return True
    return False


def in_window(epoch):
    return in_day_window(epoch) or in_night_slot(epoch)


def next_day_open(epoch, horizon_hours=24 * 8):
    offset = int(TEHRAN_OFFSET.total_seconds())
    t = epoch - (epoch + offset) % 3600 + 3600
    for _ in range(horizon_hours):
        if in_day_window(t):
            return t
        t += 3600
    return t


def next_open(epoch, horizon_hours=24 * 8):
    return next_day_open(epoch, horizon_hours)


def next_night_start(epoch):
    offset = int(TEHRAN_OFFSET.total_seconds())
    midnight = epoch - (epoch + offset) % 86400
    starts = []
    for day in range(2):
        for hour, minute in NIGHT_SLOTS:
            starts.append(midnight + day * 86400 + hour * 3600 + minute * 60)
    return min(t for t in starts if t > epoch)
