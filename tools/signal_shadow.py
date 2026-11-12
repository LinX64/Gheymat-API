from __future__ import annotations

import gheymat_blend
import gheymat_forecast as fc


def score(daily: dict, signal_ctx, method=fc.DEFAULT_METHOD) -> dict:
    wins: dict[str, int] = {}
    baseline = 0
    codes = 0
    entries = daily.get("codes", {}) if isinstance(daily, dict) else {}
    for code in sorted(entries, key=str):
        try:
            points = []
            for day in sorted(entries[code]):
                buy, sell = entries[code][day]
                price = sell if sell is not None else buy
                if price:
                    points.append({"date": day, "price": float(price)})
            closes = fc.clean_series(points)
            if not closes:
                continue
            series = fc.Series(closes)
            returns = series.horizon_returns()
            weeks = fc.backtest(series, returns, method)
            if len(weeks) < fc.MIN_BACKTEST_WEEKS:
                continue
            best = gheymat_blend.best_variant(code, series, returns, signal_ctx, weeks, method)
            name = best["name"]
        except Exception:
            continue
        codes += 1
        if name == "baseline":
            baseline += 1
        else:
            wins[name] = wins.get(name, 0) + 1
    return {"codes": codes, "wins": wins, "baseline": baseline}


def line(result: dict) -> str:
    parts = [f"ai: signal shadow {result['codes']} codes", f"baseline {result['baseline']}"]
    wins = result["wins"]
    for spec in gheymat_blend.VARIANTS:
        count = wins.get(spec["name"], 0)
        if spec["signal"] is not None and count:
            parts.append(f"{spec['name']} {count}")
    return ", ".join(parts)
