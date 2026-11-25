#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
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


PUBLISHED_METHODS = tuple(m for m in fc.METHODS if m not in fc.BLEND_METHODS)


def compare(points: list[dict], methods=PUBLISHED_METHODS) -> dict:
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
    head_returns = head.horizon_returns(method)
    for w in weeks:
        if w["basisDate"] + timedelta(days=fc.HORIZON_DAYS) > cut:
            continue
        band = fc.band_at(head_returns, w["basisDate"], head.sigma_at(w["basisDate"], method), method)
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
    wins = {m: 0 for m in PUBLISHED_METHODS}
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


def verdict(codes: dict, perm: dict | None = None) -> dict:
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
    if perm is not None and (perm.get("p") is None or perm["p"] > PERM_MAX_P):
        return out(False, "primary-permutation", worst, matching)
    return out(True, "all-conditions-met", worst, matching)


PERM_BLOCK_DAYS = 20
PERM_MAX_P = 0.05
PERM_SEED = 20


def _gap_of(points: list[dict], method: str):
    annotated = _annotated(points, method)
    if not annotated:
        return None
    return analyze_code(annotated)["gap"]


def _shuffled_points(closes: list, order: list, blocks: list) -> list[dict]:
    price = closes[0][1]
    out = [{"date": closes[0][0].isoformat(), "price": price}]
    flat = [r for k in order for r in blocks[k]]
    for (d, _), r in zip(closes[1:], flat):
        price *= math.exp(r)
        out.append({"date": d.isoformat(), "price": price})
    return out


def permutation_pvalue(points: list[dict], method: str, n_perm: int, seed: int = PERM_SEED) -> dict:
    observed = _gap_of(points, method)
    closes = fc.clean_series(points)
    if observed is None or len(closes) < 2 or n_perm <= 0:
        return {"observed": observed, "n_perm": n_perm, "p": None}
    rets = [math.log(b / a) for (_, a), (_, b) in zip(closes, closes[1:])]
    blocks = [rets[i:i + PERM_BLOCK_DAYS] for i in range(0, len(rets), PERM_BLOCK_DAYS)]
    rng = random.Random(seed)
    order = list(range(len(blocks)))
    count = 0
    for _ in range(n_perm):
        rng.shuffle(order)
        gap = _gap_of(_shuffled_points(closes, order, blocks), method)
        if gap is None or round(gap, 9) >= round(observed, 9):
            count += 1
    return {"observed": observed, "n_perm": n_perm, "p": (1 + count) / (1 + n_perm)}


SWITCH_MIN_SCORE_GAIN = 0.03
SWITCH_COVERAGE_BAND = fc.COVERAGE_ALL
SWITCH_LOW_BIN_MIN_GAIN = 0.03
SWITCH_MIN_CODE_SHARE = 2 / 3
SWITCH_HOLDOUT_WEEKS = 52


def switch_rows(points: list[dict], method: str) -> list[dict] | None:
    closes = fc.clean_series(points)
    if not closes:
        return None
    series = fc.Series(closes)
    weeks = fc.backtest(series, series.horizon_returns(method), method)
    if len(weeks) < fc.MIN_BACKTEST_WEEKS:
        return None
    return [{"basisDate": w["basisDate"], "inside": w["inside"], "intervalScore": w["intervalScore"],
             "pct": sigma_percentile(series, w["basisDate"])} for w in weeks]


def _paired(default_rows: list[dict], candidate_rows: list[dict]) -> list[tuple[dict, dict]]:
    cand = {r["basisDate"]: r for r in candidate_rows}
    return [(r, cand[r["basisDate"]]) for r in default_rows if r["basisDate"] in cand]


def _pair_stats(pairs: list[tuple[dict, dict]]) -> dict | None:
    if not pairs:
        return None
    n = len(pairs)
    d_score = sum(a["intervalScore"] for a, _ in pairs) / n
    c_score = sum(b["intervalScore"] for _, b in pairs) / n
    low = [(a, b) for a, b in pairs if a["pct"] is not None and regime_bin(a["pct"]) == "low"]
    gain = 1 - c_score / d_score if d_score else None
    low_gain = None
    if low:
        low_gain = (sum(1 for _, b in low if b["inside"]) - sum(1 for a, _ in low if a["inside"])) / len(low)
    return {"n": n, "gain": gain, "lowGain": low_gain,
            "candCoverage": sum(1 for _, b in pairs if b["inside"]) / n}


def _positive(x) -> bool:
    return x is not None and x > 0


def switch_decision(default_outcomes: dict, candidate_outcomes: dict) -> dict:
    def out(switch, reason):
        return {"switch": switch, "reason": reason}

    per_code = {}
    for code in sorted(set(default_outcomes) & set(candidate_outcomes)):
        d, c = default_outcomes[code], candidate_outcomes[code]
        if d and c:
            pairs = _paired(d, c)
            if len(pairs) > SWITCH_HOLDOUT_WEEKS:
                per_code[code] = (pairs[:-SWITCH_HOLDOUT_WEEKS], pairs[-SWITCH_HOLDOUT_WEEKS:])
    if not per_code:
        return out(False, "no-data")
    pooled = [p for pre, _ in per_code.values() for p in pre]
    full = _pair_stats(pooled)
    lo, hi = SWITCH_COVERAGE_BAND
    if not lo <= full["candCoverage"] <= hi:
        return out(False, "coverage-band")
    if full["gain"] is None or round(full["gain"], 9) < SWITCH_MIN_SCORE_GAIN:
        return out(False, "score-gain")
    if full["lowGain"] is None or round(full["lowGain"], 9) < SWITCH_LOW_BIN_MIN_GAIN:
        return out(False, "low-bin")
    held = _pair_stats([p for _, tail in per_code.values() for p in tail])
    if not (_positive(held["gain"]) and _positive(held["lowGain"])):
        return out(False, "holdout")
    agree = 0
    for pre, _ in per_code.values():
        st = _pair_stats(pre)
        if _positive(st["gain"]) and _positive(st["lowGain"]):
            agree += 1
    if agree / len(per_code) < SWITCH_MIN_CODE_SHARE:
        return out(False, "code-share")
    return out(True, "all-conditions-met")


def regimes(daily: dict, codes=None, method: str = fc.DEFAULT_METHOD, n_perm: int = 0) -> dict:
    wanted = sorted(daily.get("codes", {}))
    if codes:
        wanted = [c for c in wanted if c in set(codes)]
    analyses = {}
    for c in wanted:
        annotated = _annotated(points_from_daily(daily["codes"][c]), method)
        analyses[c] = analyze_code(annotated) if annotated else None
    if n_perm <= 0:
        return {"codes": analyses, "verdict": verdict(analyses)}
    perm = None
    if daily.get("codes", {}).get(PRIMARY_CODE) is not None and analyses.get(PRIMARY_CODE) is not None:
        perm = permutation_pvalue(points_from_daily(daily["codes"][PRIMARY_CODE]), method, n_perm)
    return {"codes": analyses, "verdict": verdict(analyses, perm if perm is not None else {"p": None}),
            "permutation": perm}


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
    perm = result.get("permutation")
    if perm is not None:
        lines.append(f"permutation n_perm={perm['n_perm']} observed={_fmt(perm['observed'], '.3f')} "
                     f"p={_fmt(perm['p'], '.4f')} max={PERM_MAX_P:.2f}")
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
    ap.add_argument("--perm", type=int, default=0, help="with --regimes: permutation count for the primary code")
    args = ap.parse_args(argv)
    try:
        daily = json.loads(Path(args.daily).read_text(encoding="utf-8"))
        codes = [c for c in args.codes.split(",") if c] if args.codes else None
        if args.regimes:
            result = regimes(daily, codes, n_perm=args.perm)
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
