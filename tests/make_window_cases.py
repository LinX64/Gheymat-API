#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import cadence as c

TEHRAN = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
START = datetime.datetime(2026, 11, 14, 0, 0, tzinfo=TEHRAN)
DAYS = 7
STEP = datetime.timedelta(minutes=30)
EDGE_HOURS = (7, 8, 12, 13, 16, 17)
OUT = ROOT / "tests" / "fixtures" / "window_cases.json"


def epoch_of(moment):
    return int(moment.timestamp())


def sample_epochs():
    epochs = set()
    moment = START
    end = START + datetime.timedelta(days=DAYS)
    while moment < end:
        epochs.add(epoch_of(moment))
        moment += STEP
    for day in range(DAYS):
        base = START + datetime.timedelta(days=day)
        for hour in EDGE_HOURS:
            boundary = epoch_of(base.replace(hour=hour))
            epochs.update((boundary - 1, boundary, boundary + 1))
    return sorted(epochs)


def build_cases():
    return [{"epoch": epoch, "open": c.in_window(epoch)} for epoch in sample_epochs()]


def main():
    cases = build_cases()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
