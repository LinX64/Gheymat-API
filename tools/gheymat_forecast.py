"""7-day quantile forecast (filtered historical simulation by default) with walk-forward backtest and the AC-F gates (Gheymat CONTRACT.md "AI feed")."""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, timedelta
from statistics import median

METHODS = {"fhs": "filtered-quantile-v1", "eq": "empirical-quantile-v1"}
DEFAULT_METHOD = "fhs"
METHOD = METHODS[DEFAULT_METHOD]
EWMA_LAMBDA = 0.94
EWMA_SEED_RETURNS = 30
MIN_SIGMA = 1e-5
HORIZON_DAYS = 7
BAND = 0.8
Q_LOW, Q_MID, Q_HIGH = 0.1, 0.5, 0.9
TARGET_SLACK_DAYS = 3
LOOKBACK_DAYS = 3 * 365
MIN_RETURNS_FOR_BAND = 260
MIN_BACKTEST_WEEKS = 104
RECENT_WEEKS = 52
RECENT_WINDOW_DAYS = 90
MAX_RECENT_GAP_DAYS = 7
COVERAGE_ALL = (0.75, 0.85)
COVERAGE_RECENT = (0.70, 0.90)
UNUSUAL_PERCENTILE = 0.99
FRIDAY = 4
MAX_BASIS_TRADING_DAYS = 2


def clean_series(points):
    seen = {}
    for p in points:
        price = p.get("price")
        if price is None or not math.isfinite(price) or price <= 0:
            continue
        seen[date.fromisoformat(p["date"])] = float(price)
    return sorted(seen.items())


def quantile(sorted_values, q):
    if not sorted_values:
        raise ValueError("empty")
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


class Series:
    def __init__(self, closes):
        self.dates = [d for d, _ in closes]
        self.prices = [p for _, p in closes]
        self.sigma = ewma_sigma(self.prices)

    def sigma_at(self, day):
        i = bisect_right(self.dates, day) - 1
        return self.sigma[i] if i >= 0 else None

    def close_on_or_before(self, day, earliest):
        i = bisect_right(self.dates, day) - 1
        if i < 0 or self.dates[i] < earliest:
            return None
        return self.dates[i], self.prices[i]

    def horizon_returns(self):
        out = []
        for d, p, s in zip(self.dates, self.prices, self.sigma):
            target = d + timedelta(days=HORIZON_DAYS)
            hit = self.close_on_or_before(target, target - timedelta(days=TARGET_SLACK_DAYS))
            if hit is not None and hit[0] > d:
                out.append((d, hit[0], math.log(hit[1] / p), s))
        return out


def ewma_sigma(prices):
    if not prices:
        return []
    rets = [math.log(b / a) for a, b in zip(prices, prices[1:])]
    seed = rets[:EWMA_SEED_RETURNS]
    var = sum(r * r for r in seed) / len(seed) if seed else MIN_SIGMA ** 2
    out = [max(math.sqrt(var), MIN_SIGMA)]
    for r in rets:
        var = EWMA_LAMBDA * var + (1 - EWMA_LAMBDA) * r * r
        out.append(max(math.sqrt(var), MIN_SIGMA))
    return out


def band_at(returns, basis_date, sigma_now=None, method=DEFAULT_METHOD):
    earliest = basis_date - timedelta(days=LOOKBACK_DAYS)
    window = [(r, s) for b, t, r, s in returns if t <= basis_date and b >= earliest]
    if len(window) < MIN_RETURNS_FOR_BAND:
        return None
    if method == "fhs":
        if sigma_now is None:
            return None
        usable = sorted(r / s for r, s in window)
        return tuple(quantile(usable, q) * sigma_now for q in (Q_LOW, Q_MID, Q_HIGH))
    usable = sorted(r for r, _ in window)
    return quantile(usable, Q_LOW), quantile(usable, Q_MID), quantile(usable, Q_HIGH)


def backtest(series, returns, method=DEFAULT_METHOD):
    weeks = []
    if not series.dates:
        return weeks
    cursor = series.dates[-1] - timedelta(days=HORIZON_DAYS)
    first = series.dates[0]
    while cursor > first:
        basis = series.close_on_or_before(cursor, cursor - timedelta(days=TARGET_SLACK_DAYS))
        if basis is not None:
            bdate, bprice = basis
            target = bdate + timedelta(days=HORIZON_DAYS)
            actual = series.close_on_or_before(target, target - timedelta(days=TARGET_SLACK_DAYS))
            band = band_at(returns, bdate, series.sigma_at(bdate), method)
            if actual is not None and band is not None:
                lo, mid, hi = (bprice * math.exp(x) for x in band)
                weeks.append({
                    "basisDate": bdate, "basis": bprice, "actual": actual[1],
                    "low": lo, "likely": mid, "high": hi,
                    "inside": lo <= actual[1] <= hi,
                    "err": abs(mid - actual[1]) / actual[1],
                    "naiveErr": abs(bprice - actual[1]) / actual[1],
                })
        cursor -= timedelta(days=HORIZON_DAYS)
    weeks.reverse()
    return weeks


def previous_trading_day(today):
    d = today - timedelta(days=1)
    while d.weekday() == FRIDAY:
        d -= timedelta(days=1)
    return d


def basis_is_fresh(basis_date, today):
    floor = today
    for _ in range(MAX_BASIS_TRADING_DAYS):
        floor = previous_trading_day(floor)
    return basis_date >= floor


def max_recent_gap(series, today):
    window_start = today - timedelta(days=RECENT_WINDOW_DAYS)
    recent = [d for d in series.dates if d >= window_start]
    if not recent:
        return None
    gaps = [(b - a).days for a, b in zip(recent, recent[1:])]
    gaps.append((today - recent[-1]).days)
    return max(gaps)


def coverage(weeks):
    return sum(1 for w in weeks if w["inside"]) / len(weeks) if weeks else 0.0


def apply_skill(likely, basis_price, mape, naive_mape):
    return likely if mape < naive_mape else basis_price


def build_forecast(code, points, today, generated_at, history_close=None, method=DEFAULT_METHOD):
    closes = clean_series(points)
    if not closes:
        return None, "no-history"
    series = Series(closes)
    basis_date, basis_price = closes[-1]
    if history_close is not None and (basis_date.isoformat(), basis_price) != (history_close["date"], history_close["price"]):
        return None, "basis-mismatch"
    if not basis_is_fresh(basis_date, today):
        return None, "basis-stale"
    gap = max_recent_gap(series, today)
    if gap is None or gap > MAX_RECENT_GAP_DAYS:
        return None, "recent-gap"
    returns = series.horizon_returns()
    weeks = backtest(series, returns, method)
    if len(weeks) < MIN_BACKTEST_WEEKS:
        return None, "history"
    cov_all = coverage(weeks)
    cov_recent = coverage(weeks[-RECENT_WEEKS:])
    if not COVERAGE_ALL[0] <= cov_all <= COVERAGE_ALL[1]:
        return None, "calibration"
    if not COVERAGE_RECENT[0] <= cov_recent <= COVERAGE_RECENT[1]:
        return None, "calibration-recent"
    band = band_at(returns, basis_date, series.sigma_at(basis_date), method)
    if band is None:
        return None, "history"
    low, likely, high = (basis_price * math.exp(x) for x in band)
    mape = median(w["err"] for w in weeks) * 100
    naive = median(w["naiveErr"] for w in weeks) * 100
    likely = apply_skill(likely, basis_price, mape, naive)
    all_r = [r for _, _, r, _ in returns]
    widest = math.exp(max(all_r) - min(all_r))
    if not (0 < low <= likely <= high) or high / low > widest:
        return None, "sanity"
    past_abs = sorted(abs(r) for b, _, r, _ in returns if b < basis_date - timedelta(days=HORIZON_DAYS))
    latest = series.close_on_or_before(basis_date - timedelta(days=HORIZON_DAYS),
                                       basis_date - timedelta(days=HORIZON_DAYS + TARGET_SLACK_DAYS))
    unusual = False
    if latest is not None and past_abs:
        unusual = abs(math.log(basis_price / latest[1])) > quantile(past_abs, UNUSUAL_PERCENTILE)
    target = basis_date + timedelta(days=HORIZON_DAYS)
    doc = {
        "code": code,
        "generatedAt": generated_at,
        "basis": {"date": basis_date.isoformat(), "price": basis_price},
        "horizonDays": HORIZON_DAYS,
        "target": target.isoformat(),
        "likely": round(likely, 2),
        "low": round(low, 2),
        "high": round(high, 2),
        "band": BAND,
        "coverage": round(cov_all, 3),
        "backtestWeeks": len(weeks),
        "error": {"mape": round(mape, 2), "naiveMape": round(naive, 2)},
        "unusual": unusual,
        "method": METHODS[method],
        "track": [],
        "signals": [],
    }
    return doc, None
