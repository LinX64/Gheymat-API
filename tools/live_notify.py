from __future__ import annotations

import json
from pathlib import Path

STATE_FILE = "live-notify.json"
DEFAULT_URL = "https://api.gheymat.pl/v1/live/notify"
MAX_CODES = 20


def _sell(rate) -> float | None:
    for key in ("sell", "price", "buy"):
        v = rate.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v)
    return None


def _change(code, sell, daily, today):
    series = (daily or {}).get("codes", {}).get(code) or {}
    days = [d for d in series if d < today]
    if not days:
        return None
    buy, close = series[max(days)]
    base = close if close is not None else buy
    return round((sell - base) / base * 100, 2) if base else None


def build_payload(rates, daily, today: str, as_of: str, last: dict) -> dict | None:
    rows = []
    for r in rates if isinstance(rates, list) else []:
        code = r.get("code") if isinstance(r, dict) else None
        sell = _sell(r) if code else None
        if sell is None or last.get(code) == sell:
            continue
        before = last.get(code)
        move = abs(sell - before) / before if before else 0.0
        rows.append((move, code, {"code": code, "sell": sell, "changePercent": _change(code, sell, daily, today)}))
    if not rows:
        return None
    rows.sort(key=lambda x: (-x[0], x[1]))
    return {"asOf": as_of, "rates": [row for _, _, row in rows[:MAX_CODES]]}


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run(env, state_dir, rates, daily, today: str, as_of: str, log=print, post=None) -> bool:
    secret = (env or {}).get("LIVE_NOTIFY_SECRET")
    if not secret:
        return False
    try:
        path = Path(state_dir) / STATE_FILE if state_dir else None
        last = _load(path) if path else {}
        payload = build_payload(rates, daily, today, as_of, last)
        if payload is None:
            return False
        if post is None:
            import requests
            post = requests.post
        resp = post(env.get("LIVE_NOTIFY_URL") or DEFAULT_URL, json=payload, timeout=10,
                    headers={"Authorization": f"Bearer {secret}"})
        if getattr(resp, "status_code", 0) != 200:
            log(f"live-notify: not accepted ({getattr(resp, 'status_code', 0)})")
            return False
        if path:
            last.update({row["code"]: row["sell"] for row in payload["rates"]})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(last, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        log(f"live-notify: sent {len(payload['rates'])}")
        return True
    except Exception as e:
        log(f"live-notify: skipped ({type(e).__name__})")
        return False
