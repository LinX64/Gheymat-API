#!/usr/bin/env python3
"""Read-only report: run the 7-day forecast gates on the published daily closes and print which codes pass."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gheymat_ai  # noqa: E402
import gheymat_forecast as fc  # noqa: E402
from gheymat_seal import Sealer, load_published  # noqa: E402


def points_from_daily(series: dict) -> list[dict]:
    points = []
    for day in sorted(series):
        buy, sell = series[day]
        price = sell if sell is not None else buy
        if price:
            points.append({"date": day, "price": float(price)})
    return points


def diagnose(points: list[dict], today: date, method: str = fc.DEFAULT_METHOD) -> dict:
    closes = fc.clean_series(points)
    if not closes:
        return {"days": 0}
    series = fc.Series(closes)
    weeks = fc.backtest(series, series.horizon_returns(), method)
    out = {"days": len(closes), "first": closes[0][0].isoformat(), "last": closes[-1][0].isoformat(),
           "weeks": len(weeks)}
    if weeks:
        out["coverage"] = fc.coverage(weeks)
        out["recent"] = fc.coverage(weeks[-fc.RECENT_WEEKS:])
        errs = sorted(w["err"] for w in weeks)
        naive = sorted(w["naiveErr"] for w in weeks)
        out["mape"] = errs[len(errs) // 2] * 100
        out["naive"] = naive[len(naive) // 2] * 100
    out["gap"] = fc.max_recent_gap(series, today)
    return out


def report(daily: dict, today: date, generated_at: str, method: str = fc.DEFAULT_METHOD) -> list[str]:
    lines = [f"method: {fc.METHODS[method]}", f"{'code':8} {'result':20} {'days':>5} {'weeks':>5} {'cov':>6} {'52w':>6} {'mape':>6} {'naive':>6}  "
             f"likely (low-high) vs basis"]
    for code in sorted(daily.get("codes", {})):
        points = points_from_daily(daily["codes"][code])
        doc, reason = fc.build_forecast(code, points, today, generated_at, method=method)
        d = diagnose(points, today, method)
        cov = f"{d['coverage']:.3f}" if "coverage" in d else "-"
        rec = f"{d['recent']:.3f}" if "recent" in d else "-"
        mape = f"{d['mape']:.2f}" if "mape" in d else "-"
        naive = f"{d['naive']:.2f}" if "naive" in d else "-"
        tail = ""
        if doc:
            fallback = " (no-change)" if doc["likely"] == doc["basis"]["price"] else ""
            flag = " UNUSUAL" if doc["unusual"] else ""
            tail = f"{doc['likely']:,.0f} ({doc['low']:,.0f}-{doc['high']:,.0f}) vs {doc['basis']['price']:,.0f}{fallback}{flag}"
        result = "PASS" if doc else f"withheld:{reason}"
        lines.append(f"{code:8} {result:20} {d.get('days', 0):>5} {d.get('weeks', 0):>5} {cov:>6} {rec:>6} "
                     f"{mape:>6} {naive:>6}  {tail}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", required=True, help="a local checkout of the gh-pages branch")
    ap.add_argument("--method", choices=sorted(fc.METHODS), default=fc.DEFAULT_METHOD)
    ap.add_argument("--today", help="Tehran trading day to evaluate as (YYYY-MM-DD); default: today's Tehran trading day")
    args = ap.parse_args(argv)
    sealer = Sealer.from_env()
    pages = Path(args.pages)
    daily = load_published(pages, "v1/daily.json", sealer)
    if daily is None:
        print("could not read v1/daily.json (no plain copy, and keys missing or wrong)", file=sys.stderr)
        return 2
    today = date.fromisoformat(args.today) if args.today else gheymat_ai.default_today()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("\n".join(report(daily, today, generated_at, args.method)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
