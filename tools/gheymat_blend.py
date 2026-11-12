from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import timedelta

import gheymat_forecast as fc
import gheymat_signals as gs
import news_archive as na

VARIANTS = (
    {"name": "baseline", "signal": None, "kind": None, "suffix": None},
    {"name": "vol-scale-by-oil-shock", "signal": "oil", "kind": "vol", "suffix": "oil"},
    {"name": "drift-by-usd-move", "signal": "usd", "kind": "drift", "suffix": "usd"},
    {"name": "vol-scale-by-news-shock", "signal": "news", "kind": "vol", "suffix": "news"},
)
INTERVAL_SCORE_MARGIN = 0.03
VARIANT_WEEKS = 312
SHOCK_QUANTILE = 0.75
MIN_SHOCK_SAMPLES = 30
MIN_FIT_SAMPLES = 250
MAX_SCALE = 1.5
DRIFT_MIN_T = 2.0
FLAT_PCT = 0.5
NEWS_LOOKBACK_DAYS = 7
FA_DIGITS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")
LABELS = {
    "oil": ("Brent", "برنت"),
    "usd": ("US dollar index", "شاخص دلار آمریکا"),
}


class Context:
    def __init__(self, series_obs, fetched_on, news_records=None):
        self.obs = {k: v for k, v in (series_obs or {}).items() if k in gs.SERIES and v}
        self.lags = {k: gs.effective_lag_days(k, v, fetched_on) for k, v in self.obs.items()}
        self.news = na.latest_by_date(news_records or [])
        self.news_list = list(self.news.values())
        days = sorted(self.news)
        self.news_first = days[0] if days else None
        self._cache = {}

    def has(self, signal):
        if signal == "news":
            return len(self.news) >= fc.MIN_BACKTEST_WEEKS
        return signal in self.obs

    def feature(self, signal, day):
        key = (signal, day)
        if key in self._cache:
            return self._cache[key]
        if signal == "news":
            first = self.news_first
            if first is None or (day - timedelta(days=NEWS_LOOKBACK_DAYS)).isoformat() < first:
                value = None
            else:
                value = na.news_tilt(self.news_list, day) * 100
        elif signal in self.obs:
            value = gs.weekly_change(self.obs[signal], day, self.lags[signal])
        else:
            value = None
        self._cache[key] = value
        return value


def summary_of(weeks):
    s = fc.summarize(weeks)
    s["coverageRecent"] = fc.coverage(weeks[-fc.RECENT_WEEKS:])
    return s


def gate(baseline_summary, variant_summary, aligned_weeks, margin=INTERVAL_SCORE_MARGIN):
    reasons = []
    base_is = baseline_summary.get("meanIntervalScore")
    var_is = variant_summary.get("meanIntervalScore")
    base_err = baseline_summary.get("medianErr")
    var_err = variant_summary.get("medianErr")
    cov = variant_summary.get("coverage", 0.0)
    cov_recent = variant_summary.get("coverageRecent", 0.0)
    if aligned_weeks < fc.MIN_BACKTEST_WEEKS:
        reasons.append("weeks")
    if not fc.COVERAGE_ALL[0] <= cov <= fc.COVERAGE_ALL[1]:
        reasons.append("calibration")
    if not fc.COVERAGE_RECENT[0] <= cov_recent <= fc.COVERAGE_RECENT[1]:
        reasons.append("calibration-recent")
    improvement = None
    if base_is is None or var_is is None or base_is <= 0:
        reasons.append("no-score")
    else:
        improvement = 1 - var_is / base_is
        if improvement < margin:
            reasons.append("margin")
    if base_err is None or var_err is None or var_err > base_err:
        reasons.append("median-error")
    metrics = {
        "alignedWeeks": aligned_weeks,
        "coverage": cov,
        "coverageRecent": cov_recent,
        "meanIntervalScore": var_is,
        "baselineMeanIntervalScore": base_is,
        "improvement": improvement,
        "medianErr": var_err,
        "baselineMedianErr": base_err,
        "margin": margin,
        "reasons": reasons,
    }
    return not reasons, metrics


def _table(returns, ctx, signal):
    bs = [b for b, _, _, _ in returns]
    return {
        "bs": bs,
        "ts": [t for _, t, _, _ in returns],
        "y": [r / s for _, _, r, s in returns],
        "x": [ctx.feature(signal, b) for b in bs],
    }


def _window(table, basis):
    lo = bisect_left(table["bs"], basis - timedelta(days=fc.LOOKBACK_DAYS))
    hi = bisect_right(table["bs"], basis)
    ts, xs = table["ts"], table["x"]
    return [i for i in range(lo, hi) if ts[i] <= basis and xs[i] is not None]


def _fit_vol(table, idx):
    if len(idx) < MIN_FIT_SAMPLES:
        return None
    xs, ys = table["x"], table["y"]
    thr = fc.quantile(sorted(abs(xs[i]) for i in idx), SHOCK_QUANTILE)
    shock = [ys[i] ** 2 for i in idx if abs(xs[i]) > thr]
    overall = sum(ys[i] ** 2 for i in idx) / len(idx)
    if len(shock) < MIN_SHOCK_SAMPLES or overall <= 0:
        return None
    scale = min(MAX_SCALE, max(1.0, math.sqrt(sum(shock) / len(shock) / overall)))
    return (thr, scale) if scale > 1.0 else None


def _fit_drift(table, idx):
    n = len(idx)
    if n < MIN_FIT_SAMPLES:
        return None
    xs, ys = table["x"], table["y"]
    mx = sum(xs[i] for i in idx) / n
    my = sum(ys[i] for i in idx) / n
    sxx = sum((xs[i] - mx) ** 2 for i in idx)
    if sxx <= 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in idx)
    syy = sum((ys[i] - my) ** 2 for i in idx)
    beta = sxy / sxx
    resid = (syy - beta * sxy) / (n - 2)
    if resid <= 0:
        return None
    t = beta / math.sqrt(resid / sxx)
    if abs(t) / math.sqrt(fc.HORIZON_DAYS) < DRIFT_MIN_T:
        return None
    return beta, mx


class _Evaluator:
    def __init__(self, spec, ctx, returns, method, base_cache):
        self.spec = spec
        self.ctx = ctx
        self.returns = returns
        self.method = method
        self.table = _table(returns, ctx, spec["signal"])
        self.base_cache = base_cache

    def base(self, bdate, sigma):
        if bdate not in self.base_cache:
            self.base_cache[bdate] = fc.band_at(self.returns, bdate, sigma, self.method)
        return self.base_cache[bdate]

    def band(self, bdate, sigma):
        x = self.ctx.feature(self.spec["signal"], bdate)
        if x is None or sigma is None:
            return None, False, x
        if self.spec["kind"] == "vol":
            base = self.base(bdate, sigma)
            if base is None:
                return None, False, x
            fit = _fit_vol(self.table, _window(self.table, bdate))
            if fit is None or abs(x) <= fit[0]:
                return base, False, x
            lo, mid, hi = base
            scale = fit[1]
            return (mid + (lo - mid) * scale, mid, mid + (hi - mid) * scale), True, x
        idx = _window(self.table, bdate)
        fit = _fit_drift(self.table, idx)
        if fit is None or self.method != "fhs":
            base = self.base(bdate, sigma)
            return base, False, x
        beta, mx = fit
        ys, xs = self.table["y"], self.table["x"]
        resid = sorted(ys[i] - beta * (xs[i] - mx) for i in idx)
        shift = beta * (x - mx)
        return tuple((fc.quantile(resid, q) + shift) * sigma for q in (fc.Q_LOW, fc.Q_MID, fc.Q_HIGH)), True, x


def _aligned(baseline_weeks, variant_weeks):
    have = {w["basisDate"] for w in variant_weeks}
    keep = {w["basisDate"] for w in baseline_weeks} & have
    return ([w for w in baseline_weeks if w["basisDate"] in keep],
            [w for w in variant_weeks if w["basisDate"] in keep])


def best_variant(code, series, returns, signal_ctx, baseline_weeks=None, method=fc.DEFAULT_METHOD):
    report = {}
    if signal_ctx is None or not series.dates:
        return {"name": "baseline", "spec": None, "report": report}
    if baseline_weeks is None:
        baseline_weeks = fc.backtest(series, returns, method)
    cutoff = series.dates[-1] - timedelta(days=VARIANT_WEEKS * fc.HORIZON_DAYS)
    base_cache = {}
    winner = None
    for spec in VARIANTS:
        if spec["signal"] is None:
            continue
        if not signal_ctx.has(spec["signal"]):
            report[spec["name"]] = {"reasons": ["no-signal"]}
            continue
        evaluator = _Evaluator(spec, signal_ctx, returns, method, base_cache)

        def band_fn(bdate, sigma, ev=evaluator):
            if bdate < cutoff:
                return None
            return ev.band(bdate, sigma)[0]

        weeks = fc.backtest(series, returns, method, band_fn)
        base_weeks, var_weeks = _aligned(baseline_weeks, weeks)
        passed, metrics = gate(summary_of(base_weeks), summary_of(var_weeks), len(var_weeks))
        report[spec["name"]] = metrics
        if passed and (winner is None or metrics["meanIntervalScore"] < winner["metrics"]["meanIntervalScore"]):
            winner = {"name": spec["name"], "spec": spec, "weeks": var_weeks, "baselineWeeks": base_weeks,
                      "metrics": metrics, "evaluator": evaluator}
    if winner is None:
        return {"name": "baseline", "spec": None, "report": report}
    winner["report"] = report
    return winner


def _fa(text):
    return text.translate(FA_DIGITS)


def signal_entry(spec, change):
    change = round(change, 1)
    trend = "up" if change > FLAT_PCT else "down" if change < -FLAT_PCT else "flat"
    key = spec["signal"]
    if key == "news":
        en = f"News tilt {change:+.1f}% toward a higher dollar"
        fa = _fa(f"تمایل خبرها {abs(change):.1f}٪ به سمت {'افزایش' if change >= 0 else 'کاهش'} دلار")
    else:
        en_name, fa_name = LABELS[key]
        word = "افزایش" if change >= 0 else "کاهش"
        en = f"{en_name} {change:+.1f}% this week"
        fa = _fa(f"{fa_name} این هفته {abs(change):.1f}٪ {word} یافت")
    return {"key": key, "trend": trend, "change": change, "reason": {"en": en, "fa": fa}}


def choose(code, series, returns, signal_ctx, baseline_weeks, basis_date, method=fc.DEFAULT_METHOD):
    best = best_variant(code, series, returns, signal_ctx, baseline_weeks, method)
    if best["spec"] is None:
        return None
    band, active, x = best["evaluator"].band(basis_date, series.sigma_at(basis_date))
    if band is None or not active or x is None:
        return None
    weeks = best["weeks"]
    summary = fc.summarize(weeks)
    return {
        "name": best["name"],
        "suffix": best["spec"]["suffix"],
        "band": band,
        "coverage": summary["coverage"],
        "weeks": summary["n"],
        "mape": summary["medianErr"] * 100,
        "naive": summary["medianNaiveErr"] * 100,
        "signals": [signal_entry(best["spec"], x)],
        "metrics": best["metrics"],
    }


def method_name(method, suffix):
    return fc.METHODS[method] + (f"+{suffix}" if suffix else "")


def expected_methods(signal_ctx, method=fc.DEFAULT_METHOD):
    names = {fc.METHODS[method]}
    if signal_ctx is not None:
        for spec in VARIANTS:
            if spec["signal"] is not None and signal_ctx.has(spec["signal"]):
                names.add(method_name(method, spec["suffix"]))
    return names
