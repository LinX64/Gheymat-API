from __future__ import annotations

import bisect
import csv
import io
from datetime import date, timedelta

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
SERIES = {"oil": "DCOILBRENTEU", "usd": "DTWEXBGS"}
FETCH_TIMEOUT = 10
MAX_BYTES = 2_000_000
MIN_LAG_DAYS = {"oil": 7, "usd": 10}


def parse_fred_csv(text: str) -> list[tuple[date, float]]:
    out: dict[date, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        try:
            day = date.fromisoformat(row[0].strip())
        except ValueError:
            continue
        raw = row[1].strip()
        if raw in ("", "."):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue
        out[day] = value
    return sorted(out.items())


def fetch_fred(series_id: str, http, timeout: float = FETCH_TIMEOUT) -> list[tuple[date, float]]:
    r = http.get(FRED_URL.format(series_id), timeout=timeout)
    if getattr(r, "status_code", 200) != 200:
        raise RuntimeError("fred status")
    text = r.text
    if len(text) > MAX_BYTES:
        raise RuntimeError("fred response too large")
    obs = parse_fred_csv(text)
    if not obs:
        raise RuntimeError("fred empty")
    return obs


def measured_lag_days(observations: list[tuple[date, float]], fetched_on: date) -> int | None:
    if not observations:
        return None
    return max(0, (fetched_on - observations[-1][0]).days)


def effective_lag_days(key: str, observations: list[tuple[date, float]], fetched_on: date) -> int:
    measured = measured_lag_days(observations, fetched_on) or 0
    return max(MIN_LAG_DAYS[key], measured)


def value_known_at(observations: list[tuple[date, float]], basis_date: date, lag_days: int) -> tuple[date, float] | None:
    cutoff = basis_date - timedelta(days=lag_days)
    days = [d for d, _ in observations]
    i = bisect.bisect_right(days, cutoff)
    return observations[i - 1] if i else None


def weekly_change(observations: list[tuple[date, float]], basis_date: date, lag_days: int,
                  horizon: int = 7) -> float | None:
    now = value_known_at(observations, basis_date, lag_days)
    prev = value_known_at(observations, basis_date - timedelta(days=horizon), lag_days)
    if now is None or prev is None or now[0] == prev[0] or prev[1] <= 0:
        return None
    return (now[1] / prev[1] - 1) * 100


def load_signals(http, today: date, log=print) -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = {}
    for key, series_id in SERIES.items():
        try:
            out[key] = fetch_fred(series_id, http, FETCH_TIMEOUT)
        except Exception as e:
            log(f"signals {key}: unavailable ({type(e).__name__})")
    return out
