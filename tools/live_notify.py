from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_FILE = "live-notify.json"
DEFAULT_URL = "https://api.gheymat.pl/v1/live/notify"
MAX_CODES = 20
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _sell(rate) -> float | None:
    for key in ("sell", "price", "buy"):
        v = rate.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v)
    return None


def _tehran_day(ts) -> str | None:
    try:
        moment = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(TEHRAN).date().isoformat() if moment.tzinfo else None


def _intraday_base(doc, today):
    points = doc.get("points") if isinstance(doc, dict) else None
    best = None
    for p in points if isinstance(points, list) else []:
        if not isinstance(p, dict):
            continue
        day, value = _tehran_day(p.get("ts")), _sell(p)
        if day and day < today and value and (best is None or p["ts"] > best[0]):
            best = (p["ts"], value)
    return best[1] if best else None


def _change(code, sell, daily, today, load_doc=None):
    base = _intraday_base(load_doc(f"v1/intraday/{code}"), today) if load_doc else None
    if base:
        return round((sell - base) / base * 100, 2)
    series = (daily or {}).get("codes", {}).get(code) or {}
    days = [d for d in series if d < today]
    if not days:
        return None
    buy, close = series[max(days)]
    base = close if close is not None else buy
    return round((sell - base) / base * 100, 2) if base else None


def build_payload(rates, daily, today: str, as_of: str, last: dict, load_doc=None) -> dict | None:
    rows = []
    for r in rates if isinstance(rates, list) else []:
        code = r.get("code") if isinstance(r, dict) else None
        sell = _sell(r) if code else None
        if sell is None or last.get(code) == sell:
            continue
        before = last.get(code)
        move = abs(sell - before) / before if before else 0.0
        rows.append((move, code, {"code": code, "sell": sell, "changePercent": _change(code, sell, daily, today, load_doc)}))
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


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run(env, state_dir, rates, daily, today: str, as_of: str, log=print, post=None, load_doc=None) -> bool:
    secret = (env or {}).get("LIVE_NOTIFY_SECRET")
    if not secret:
        return False
    try:
        path = Path(state_dir) / STATE_FILE if state_dir else None
        last = _load(path) if path else {}
        payload = build_payload(rates, daily, today, as_of, last, load_doc)
        if payload is None:
            return False
        if post is None:
            import requests
            post = requests.post
        override = env.get("LIVE_NOTIFY_URL")
        url = override if isinstance(override, str) and override.startswith("https://") else DEFAULT_URL
        resp = post(url, json=payload, timeout=10,
                    headers={"Authorization": f"Bearer {secret}"})
        if getattr(resp, "status_code", 0) != 200:
            log(f"live-notify: not accepted ({getattr(resp, 'status_code', 0)})")
            return False
        if path:
            last.update({row["code"]: row["sell"] for row in payload["rates"]})
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, json.dumps(last, separators=(",", ":"), sort_keys=True))
        log(f"live-notify: sent {len(payload['rates'])}")
        return True
    except Exception as e:
        log(f"live-notify: skipped ({type(e).__name__})")
        return False
