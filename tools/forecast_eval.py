#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_left
from datetime import timedelta
from statistics import median
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gheymat_forecast as fc
from forecast_report import points_from_daily


def _weeks(points: list[dict], method: str) -> list[dict]:
    closes = fc.clean_series(points)
    if not closes:
        return []
    series = fc.Series(closes)
    weeks = fc.backtest(series, series.horizon_returns(), method)
    return weeks if len(weeks) >= fc.MIN_BACKTEST_WEEKS else []


RECENT_WEEKS = 52


def recent_skill(weeks: list[dict]) -> tuple[float | None, int]:
    last = weeks[-RECENT_WEEKS:]
    if len(last) < RECENT_WEEKS:
        return None, len(last)
    naive = median(w["naiveErr"] for w in last)
    if not naive:
        return None, len(last)
    return 1 - median(w["err"] for w in last) / naive, len(last)


def tail_misses(weeks: list[dict]) -> tuple[float | None, float | None]:
    if not weeks:
        return None, None
    n = len(weeks)
    return (sum(1 for w in weeks if w["actual"] < w["low"]) / n,
            sum(1 for w in weeks if w["actual"] > w["high"]) / n)


def _metrics(weeks: list[dict], method: str) -> dict:
    summary = fc.summarize(weeks)
    naive = summary["medianNaiveErr"]
    mape = summary["medianErr"]
    r_skill, r_weeks = recent_skill(weeks)
    below, above = tail_misses(weeks)
    return {
        "method": method,
        "weeks": summary["n"],
        "coverage": summary["coverage"],
        "coverageRecent": fc.coverage(weeks[-fc.RECENT_WEEKS:]),
        "intervalScore": summary["meanIntervalScore"],
        "mape": mape,
        "naiveMape": naive,
        "skill": 1 - mape / naive if naive else None,
        "recent_skill": r_skill,
        "recent_weeks": r_weeks,
        "miss_below": below,
        "miss_above": above,
    }


def evaluate(points: list[dict], method: str) -> dict | None:
    weeks = _weeks(points, method)
    return _metrics(weeks, method) if weeks else None


def compare(points: list[dict], methods=tuple(fc.METHODS)) -> dict:
    by_method = {m: _weeks(points, m) for m in methods}
    results = {m: (_metrics(w, m) if w else None) for m, w in by_method.items()}
    live = [m for m in methods if by_method[m]]
    best = None
    if live:
        shared = set.intersection(*({w["basisDate"] for w in by_method[m]} for m in live))
        lo, hi = fc.COVERAGE_ALL
        rlo, rhi = fc.COVERAGE_RECENT
        scores = {}
        for m in live:
            if not lo <= results[m]["coverage"] <= hi:
                continue
            if not rlo <= results[m]["coverageRecent"] <= rhi:
                continue
            aligned = [w["intervalScore"] for w in by_method[m] if w["basisDate"] in shared]
            if aligned:
                scores[m] = sum(aligned) / len(aligned)
        if scores:
            best = min(scores, key=scores.get)
    return {"results": results, "best": best}


def check_no_lookahead(points: list[dict], method: str, cut) -> bool:
    closes = fc.clean_series(points)
    if not closes:
        return True
    full = fc.Series(closes)
    weeks = fc.backtest(full, full.horizon_returns(), method)
    head = fc.Series([c for c in closes if c[0] <= cut])
    head_returns = head.horizon_returns()
    for w in weeks:
        if w["basisDate"] + timedelta(days=fc.HORIZON_DAYS) > cut:
            continue
        band = fc.band_at(head_returns, w["basisDate"], head.sigma_at(w["basisDate"]), method)
        if band is None:
            return False
        expected = tuple(w["basis"] * math.exp(x) for x in band)
        if expected != (w["low"], w["likely"], w["high"]):
            return False
    return True


def _fmt(value, spec: str) -> str:
    return "-" if value is None else format(value, spec)


def _lines_for(code: str, outcome: dict) -> list[str]:
    lines = []
    for method, r in outcome["results"].items():
        if r is None:
            lines.append(f"{code} {method} insufficient-history")
            continue
        lines.append(f"{code} {method} weeks={r['weeks']} cov={r['coverage']:.3f} cov52={r['coverageRecent']:.3f} "
                     f"iscore={_fmt(r['intervalScore'], '.4f')} mape={_fmt(r['mape'], '.4f')} "
                     f"naive={_fmt(r['naiveMape'], '.4f')} skill={_fmt(r['skill'], '.3f')} "
                     f"recent_skill={_fmt(r['recent_skill'], '.3f')} recent_weeks={r['recent_weeks']} "
                     f"miss_below={_fmt(r['miss_below'], '.3f')} miss_above={_fmt(r['miss_above'], '.3f')}")
    lines.append(f"{code} best {outcome['best'] or '-'}")
    return lines


def _evaluate_all(daily: dict, codes=None) -> dict:
    wanted = sorted(daily.get("codes", {}))
    if codes:
        wanted = [c for c in wanted if c in set(codes)]
    return {c: compare(points_from_daily(daily["codes"][c])) for c in wanted}


def _wins(outcomes: dict) -> dict:
    wins = {m: 0 for m in fc.METHODS}
    for o in outcomes.values():
        if o["best"]:
            wins[o["best"]] += 1
    return wins


def report(daily: dict, codes=None) -> list[str]:
    outcomes = _evaluate_all(daily, codes)
    lines = []
    for code, outcome in outcomes.items():
        lines.extend(_lines_for(code, outcome))
    wins = _wins(outcomes)
    lines.append("totals " + " ".join(f"{m}={n}" for m, n in wins.items()))
    return lines


MIN_GAP = 0.10
MIN_CODE_SHARE = 2 / 3
HOLDOUT_WEEKS = 52
PRIMARY_CODE = "usd"
BINS = ("low", "mid", "high")
TERCILE_LOW = 1 / 3
TERCILE_HIGH = 2 / 3


def sigma_percentile(series, basis_date) -> float | None:
    hi = bisect_left(series.dates, basis_date)
    lo = bisect_left(series.dates, basis_date - timedelta(days=fc.LOOKBACK_DAYS))
    trailing = series.sigma[lo:hi]
    now = series.sigma_at(basis_date)
    if now is None or len(trailing) < fc.MIN_RETURNS_FOR_BAND:
        return None
    less = sum(1 for x in trailing if x < now)
    equal = sum(1 for x in trailing if x == now)
    return (less + 0.5 * equal) / len(trailing)


def regime_bin(pct: float) -> str:
    if pct < TERCILE_LOW:
        return "low"
    if pct >= TERCILE_HIGH:
        return "high"
    return "mid"


def _features(series, returns, basis_date, basis_price) -> tuple[float | None, bool]:
    pct = sigma_percentile(series, basis_date)
    week = timedelta(days=fc.HORIZON_DAYS)
    past_abs = sorted(abs(r) for d, _, r, _ in returns if d < basis_date - week)
    latest = series.close_on_or_before(basis_date - week, basis_date - week - timedelta(days=fc.TARGET_SLACK_DAYS))
    unusual = False
    if latest is not None and past_abs:
        unusual = abs(math.log(basis_price / latest[1])) > fc.quantile(past_abs, fc.UNUSUAL_PERCENTILE)
    return pct, unusual


def _annotated(points: list[dict], method: str) -> list[dict] | None:
    closes = fc.clean_series(points)
    if not closes:
        return None
    series = fc.Series(closes)
    returns = series.horizon_returns()
    weeks = fc.backtest(series, returns, method)
    if len(weeks) < fc.MIN_BACKTEST_WEEKS:
        return None
    out = []
    for w in weeks:
        pct, unusual = _features(series, returns, w["basisDate"], w["basis"])
        out.append({"basisDate": w["basisDate"], "inside": w["inside"], "pct": pct, "unusual": unusual})
    return out


def check_regime_no_lookahead(points: list[dict], method: str, cut) -> bool:
    closes = fc.clean_series(points)
    if not closes:
        return True
    full = fc.Series(closes)
    full_returns = full.horizon_returns()
    weeks = fc.backtest(full, full_returns, method)
    head = fc.Series([c for c in closes if c[0] <= cut])
    head_returns = head.horizon_returns()
    for w in weeks:
        if w["basisDate"] > cut:
            continue
        if _features(full, full_returns, w["basisDate"], w["basis"]) != _features(head, head_returns, w["basisDate"], w["basis"]):
            return False
    return True


def _cell(rows: list[dict]) -> dict:
    return {"n": len(rows), "coverage": sum(1 for r in rows if r["inside"]) / len(rows) if rows else None}


def _table(rows: list[dict]) -> dict:
    kept = [r for r in rows if r["pct"] is not None]
    return {b: _cell([r for r in kept if regime_bin(r["pct"]) == b]) for b in BINS}


def _extremes(table: dict) -> tuple[str | None, str | None, float | None]:
    populated = [(b, table[b]["coverage"]) for b in BINS if table[b]["n"]]
    if len(populated) < 2:
        return None, None, None
    worst = min(populated, key=lambda x: x[1])
    best = max(populated, key=lambda x: x[1])
    tied = sum(1 for _, c in populated if c == worst[1]) > 1
    return (None if tied else worst[0]), best[0], best[1] - worst[1]


def analyze_code(annotated: list[dict]) -> dict:
    weeks = len(annotated)
    skipped = sum(1 for r in annotated if r["pct"] is None)
    table = _table(annotated)
    worst, best, gap = _extremes(table)
    half = weeks // 2
    return {
        "weeks": weeks,
        "skipped": skipped,
        "bins": table,
        "early": _table(annotated[:half]),
        "late": _table(annotated[half:]),
        "holdout": _table(annotated[-HOLDOUT_WEEKS:]),
        "beforeHoldout": _table(annotated[:-HOLDOUT_WEEKS]),
        "unusual": {"unusual": _cell([r for r in annotated if r["unusual"]]),
                    "usual": _cell([r for r in annotated if not r["unusual"]])},
        "worst": worst,
        "best": best,
        "gap": gap,
    }


def _gap_ok(gap) -> bool:
    return gap is not None and round(gap, 9) >= MIN_GAP


def verdict(codes: dict) -> dict:
    live = {c: a for c, a in codes.items() if a is not None}
    primary = live.get(PRIMARY_CODE)

    def out(passed, reason, worst, matching):
        return {"verdict": "PASS" if passed else "FAIL", "reason": reason, "worst": worst,
                "codesWithData": len(live), "codesMatching": matching}

    if primary is None or primary["gap"] is None:
        return out(False, "primary-no-data", None, 0)
    worst, best = primary["worst"], primary["best"]
    matching = sum(1 for a in live.values() if worst is not None and a["worst"] == worst and _gap_ok(a["gap"]))
    if not _gap_ok(primary["gap"]):
        return out(False, "primary-gap", worst, matching)
    if worst is None:
        return out(False, "primary-tie", None, 0)
    if not (_extremes(primary["early"])[0] == worst and _extremes(primary["late"])[0] == worst):
        return out(False, "primary-halves", worst, matching)
    hold = primary["holdout"]
    if _extremes(primary["beforeHoldout"])[0] != worst:
        return out(False, "primary-holdout", worst, matching)
    hc, hb = hold[worst]["coverage"], hold[best]["coverage"]
    if not (_extremes(hold)[0] == worst and hc is not None and hb is not None and hc < hb):
        return out(False, "primary-holdout", worst, matching)
    if matching / len(live) < MIN_CODE_SHARE:
        return out(False, "code-share", worst, matching)
    return out(True, "all-conditions-met", worst, matching)


def regimes(daily: dict, codes=None, method: str = fc.DEFAULT_METHOD) -> dict:
    wanted = sorted(daily.get("codes", {}))
    if codes:
        wanted = [c for c in wanted if c in set(codes)]
    analyses = {}
    for c in wanted:
        annotated = _annotated(points_from_daily(daily["codes"][c]), method)
        analyses[c] = analyze_code(annotated) if annotated else None
    return {"codes": analyses, "verdict": verdict(analyses)}


def _table_line(code: str, label: str, table: dict) -> str:
    cells = " ".join(f"{b}[n={table[b]['n']} cov={_fmt(table[b]['coverage'], '.3f')}]" for b in BINS)
    return f"{code} {label} {cells}"


def regimes_report(result: dict) -> list[str]:
    lines = []
    for code, a in result["codes"].items():
        if a is None:
            lines.append(f"{code} regimes insufficient-history")
            continue
        lines.append(f"{code} regimes weeks={a['weeks']} skipped={a['skipped']} worst={a['worst'] or '-'} "
                     f"gap={_fmt(a['gap'], '.3f')}")
        for label in ("bins", "early", "late", "holdout", "beforeHoldout"):
            lines.append(_table_line(code, "all" if label == "bins" else label, a[label]))
        u, n = a["unusual"]["unusual"], a["unusual"]["usual"]
        lines.append(f"{code} unusual n={u['n']} cov={_fmt(u['coverage'], '.3f')} "
                     f"usual n={n['n']} cov={_fmt(n['coverage'], '.3f')}")
    v = result["verdict"]
    lines.append(f"verdict {v['verdict']} worst={v['worst'] or '-'} reason={v['reason']} "
                 f"codes={v['codesMatching']}/{v['codesWithData']}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare the forecast methods walk-forward on a local daily history file.")
    ap.add_argument("--daily", required=True, help="a local daily history JSON file")
    ap.add_argument("--codes", help="comma separated codes to evaluate; default: all")
    ap.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    ap.add_argument("--regimes", action="store_true", help="report range coverage by volatility regime")
    args = ap.parse_args(argv)
    try:
        daily = json.loads(Path(args.daily).read_text(encoding="utf-8"))
        codes = [c for c in args.codes.split(",") if c] if args.codes else None
        if args.regimes:
            result = regimes(daily, codes)
            print(json.dumps(result) if args.json else "\n".join(regimes_report(result)))
        elif args.json:
            outcomes = _evaluate_all(daily, codes)
            print(json.dumps({"codes": outcomes, "totals": _wins(outcomes)}))
        else:
            print("\n".join(report(daily, codes)))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(type(e).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
