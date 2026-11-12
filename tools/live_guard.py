
import json
import os
import re
import tempfile
from pathlib import Path

KINDS = ("status", "challenge", "format", "token", "timeout", "diverge", "frozen")
COOL_STEPS = (900, 1800, 3600, 7200)
MAX_RETRY_AFTER = 7200
_QUIET_SLACK = 60
_MAX_MARKS = 16
_MARK_LEN = 40
_CHALLENGE_MARKERS = ("/cdn-cgi/challenge-platform", "Just a moment")
_UNSAFE_PARTS = ("dist", "site")


def _has_challenge(head):
    if not isinstance(head, str):
        return False
    return any(m in head for m in _CHALLENGE_MARKERS)


def _parse_retry_after(value):
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or not re.fullmatch(r"[0-9]{1,12}", v):
        return None
    return max(0, min(int(v), MAX_RETRY_AFTER))


def classify_response(status, head, retry_after):
    challenge = _has_challenge(head)
    if challenge:
        return "blocked", "challenge", _parse_retry_after(retry_after)
    if status in (403, 429):
        return "blocked", "status", _parse_retry_after(retry_after)
    if status >= 400:
        return "failed", "status", None
    return "ok", None, None


def new_state():
    return {
        "quiet_until": 0,
        "cool": COOL_STEPS[0],
        "clean_since": 0,
        "live_fp": None,
        "live_fp_since": 0,
        "primary_marks": [],
    }


def _num(value, default=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return value


def _unsafe_path(path):
    try:
        p = Path(path)
        if os.path.islink(p):
            return True
        parts = set(p.parts) | set(p.resolve().parts)
        return any(u in parts for u in _UNSAFE_PARTS)
    except (OSError, ValueError, RuntimeError):
        return True


def load_state(path, now):
    try:
        if not path or not isinstance(path, str) or _unsafe_path(path):
            return new_state()
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return new_state()
        state = new_state()
        now = _num(now, 0)
        state["quiet_until"] = max(
            0, min(_num(raw.get("quiet_until"), 0), now + MAX_RETRY_AFTER + _QUIET_SLACK)
        )
        cool = _num(raw.get("cool"), COOL_STEPS[0])
        state["cool"] = int(cool) if int(cool) in COOL_STEPS else COOL_STEPS[0]
        state["clean_since"] = max(0, min(_num(raw.get("clean_since"), 0), now))
        fp = raw.get("live_fp")
        state["live_fp"] = fp[:200] if isinstance(fp, str) else None
        state["live_fp_since"] = max(0, min(_num(raw.get("live_fp_since"), 0), now))
        marks = raw.get("primary_marks")
        if isinstance(marks, list):
            state["primary_marks"] = [
                m[:_MARK_LEN] for m in marks if isinstance(m, str)
            ][:_MAX_MARKS]
        return state
    except Exception:
        return new_state()


def save_state(path, state):
    tmp = None
    try:
        if not path or not isinstance(path, str) or _unsafe_path(path):
            return False
        directory = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".live_guard.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
        tmp = None
        return True
    except Exception:
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def is_quiet(state, now):
    return now < state["quiet_until"]


def effective_order(order, live_name, state, now, primary_short=False):
    if is_quiet(state, now) and not primary_short:
        return [n for n in order if n != live_name]
    return list(order)


def record_block(state, now, kind, retry_after):
    new = dict(state)
    new["primary_marks"] = list(state.get("primary_marks", []))
    cool = state.get("cool", COOL_STEPS[0])
    wait = max(cool, retry_after or 0)
    new["quiet_until"] = now + min(wait, MAX_RETRY_AFTER)
    if cool in COOL_STEPS:
        idx = COOL_STEPS.index(cool)
        new["cool"] = COOL_STEPS[min(idx + 1, len(COOL_STEPS) - 1)]
    else:
        new["cool"] = COOL_STEPS[0]
    new["clean_since"] = 0
    return new


def record_clean(state, now):
    new = dict(state)
    new["primary_marks"] = list(state.get("primary_marks", []))
    since = state.get("clean_since", 0)
    if not since:
        new["clean_since"] = now
    elif now - since >= MAX_RETRY_AFTER:
        new["cool"] = COOL_STEPS[0]
        new["clean_since"] = now
    return new


def frozen_check(state, live_fp, primary_mark, now, window=1200, min_marks=3):
    new = dict(state)
    marks = list(state.get("primary_marks", []))
    if live_fp != state.get("live_fp") or state.get("live_fp") is None:
        new["live_fp"] = live_fp
        new["live_fp_since"] = now
        marks = [primary_mark] if primary_mark is not None else []
    elif primary_mark is not None and primary_mark not in marks and len(marks) < _MAX_MARKS:
        marks.append(primary_mark)
    new["primary_marks"] = marks
    frozen = (now - new["live_fp_since"] >= window) and len(marks) >= min_marks
    return frozen, new


def status_line(outcome, kind=None, fp=None):
    if kind not in KINDS:
        kind = "status"
    if outcome == "ok":
        return "live: ok fp=%s" % (str(fp)[:12] if fp is not None else "")
    if outcome == "failed":
        return "live: failed %s" % kind
    if outcome == "blocked":
        return "live: blocked %s" % kind
    return "live: quiet"
