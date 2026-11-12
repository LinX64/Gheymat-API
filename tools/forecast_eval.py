#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import timedelta
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


def _metrics(weeks: list[dict], method: str) -> dict:
    summary = fc.summarize(weeks)
    naive = summary["medianNaiveErr"]
    mape = summary["medianErr"]
    return {
        "method": method,
        "weeks": summary["n"],
        "coverage": summary["coverage"],
        "coverageRecent": fc.coverage(weeks[-fc.RECENT_WEEKS:]),
        "intervalScore": summary["meanIntervalScore"],
        "mape": mape,
        "naiveMape": naive,
        "skill": 1 - mape / naive if naive else None,
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
                     f"naive={_fmt(r['naiveMape'], '.4f')} skill={_fmt(r['skill'], '.3f')}")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare the forecast methods walk-forward on a local daily history file.")
    ap.add_argument("--daily", required=True, help="a local daily history JSON file")
    ap.add_argument("--codes", help="comma separated codes to evaluate; default: all")
    ap.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    args = ap.parse_args(argv)
    try:
        daily = json.loads(Path(args.daily).read_text(encoding="utf-8"))
        codes = [c for c in args.codes.split(",") if c] if args.codes else None
        if args.json:
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
