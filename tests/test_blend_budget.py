import math
import pathlib
import random
import sys
import time
from datetime import date, timedelta

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gheymat_ai as ai
import gheymat_blend as gb
import gheymat_forecast as fc

END = date(2026, 11, 8)
TODAY = date(2026, 11, 9)
NOW = "2026-11-09T06:00:00Z"
CODES = 28
CONSERVATIVE_BOUND_SECONDS = ai.BUDGET_SECONDS / 2


def walk(seed, start, end, sigma, base, skip_friday=False):
    rng = random.Random(seed)
    out, v, d = [], base, start
    while d <= end:
        v *= math.exp(rng.gauss(0.0, sigma))
        if not (skip_friday and d.weekday() == fc.FRIDAY):
            out.append((d, v))
        d += timedelta(days=1)
    return out


def points_for(seed, years):
    start = END - timedelta(days=years * 365)
    return [{"date": d.isoformat(), "price": round(p, 2)} for d, p in walk(seed, start, END, 0.008, 50000.0, True)]


def context(years):
    start = END - timedelta(days=years * 365 + 60)
    return gb.Context({"oil": walk(1, start, END, 0.02, 80.0), "usd": walk(2, start, END, 0.003, 120.0)}, TODAY)


def run(years):
    ctx = context(years)
    started = time.perf_counter()
    built = 0
    for i in range(CODES):
        doc, _ = fc.build_forecast(f"c{i}", points_for(100 + i, years), TODAY, NOW, signal_ctx=ctx)
        built += doc is not None
    return time.perf_counter() - started, built


def test_three_year_history_all_codes_within_budget():
    elapsed, built = run(3)
    print(f"blend budget 3y: {elapsed:.2f}s for {CODES} codes, {built} built")
    assert elapsed < CONSERVATIVE_BOUND_SECONDS


def test_eight_year_history_all_codes_within_budget():
    elapsed, built = run(8)
    print(f"blend budget 8y: {elapsed:.2f}s for {CODES} codes, {built} built")
    assert elapsed < CONSERVATIVE_BOUND_SECONDS
