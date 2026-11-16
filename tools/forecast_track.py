from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import archive_store
import gheymat_forecast as fc

NAME = "forecast-log"
TRACK_LIMIT = 12
TRACK_KEYS = ("basisDate", "target", "likely", "low", "high", "actual", "hit")


def open_state(root, log=print) -> dict | None:
    if root is None:
        return None
    try:
        records = archive_store.load(root, NAME, log)
    except Exception as e:
        log(f"ai: track skipped: {type(e).__name__}")
        return None
    return {"root": root, "records": {r["date"]: r for r in records}, "loaded": len(records),
            "changed": False, "dead": False}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_entry(item) -> bool:
    return (isinstance(item, dict) and set(item) == set(TRACK_KEYS) and isinstance(item["basisDate"], str)
            and isinstance(item["target"], str) and all(_number(item[k]) for k in ("likely", "low", "high", "actual"))
            and isinstance(item["hit"], bool))


def previous_track(previous) -> list[dict]:
    items = previous.get("track") if isinstance(previous, dict) else None
    if not isinstance(items, list):
        return []
    kept = [dict(i) for i in items if _valid_entry(i)]
    kept.sort(key=lambda i: i["basisDate"], reverse=True)
    return kept[:TRACK_LIMIT]


def _day(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _unresolved(entry) -> bool:
    return isinstance(entry, dict) and entry.get("actual") is None and not entry.get("final")


def resolve_pending(state: dict, code: str, series) -> None:
    if not series.dates:
        return
    latest = series.dates[-1]
    for basis_text, record in state["records"].items():
        entry = record.get("codes", {}).get(code) if isinstance(record.get("codes"), dict) else None
        if not _unresolved(entry):
            continue
        basis, target = _day(basis_text), _day(entry.get("target"))
        if basis is None or target is None or latest < target:
            continue
        low, high = entry.get("low"), entry.get("high")
        if not (_number(low) and _number(high)):
            continue
        found = series.close_on_or_before(target, target - timedelta(days=fc.TARGET_SLACK_DAYS))
        if found is not None and found[0] > basis:
            entry["actual"] = found[1]
            entry["actualDate"] = found[0].isoformat()
            entry["hit"] = bool(low <= found[1] <= high)
        else:
            entry["actual"] = None
            entry["actualDate"] = None
            entry["hit"] = None
            entry["final"] = True
        state["changed"] = True


def own_track(state: dict, code: str) -> list[dict]:
    out = []
    for basis_text in sorted(state["records"], reverse=True):
        codes = state["records"][basis_text].get("codes")
        entry = codes.get(code) if isinstance(codes, dict) else None
        if not isinstance(entry, dict) or entry.get("actual") is None:
            continue
        item = {"basisDate": basis_text, "target": entry.get("target"), "likely": entry.get("likely"),
                "low": entry.get("low"), "high": entry.get("high"), "actual": entry.get("actual"),
                "hit": entry.get("hit")}
        if _valid_entry(item):
            out.append(item)
    return out


def merge_track(previous: list[dict], own: list[dict]) -> list[dict]:
    merged = {i["basisDate"]: i for i in own}
    for i in previous:
        merged[i["basisDate"]] = i
    ordered = [merged[d] for d in sorted(merged, reverse=True)]
    return ordered[:TRACK_LIMIT]


def _skip(state: dict, e: Exception, log) -> None:
    if not state["dead"]:
        log(f"ai: track skipped: {type(e).__name__}")
    state["dead"] = True


def _skip_code(e: Exception, log) -> None:
    log(f"ai: track skipped: {type(e).__name__}")


def build_track(state: dict | None, code: str, points: list[dict], previous, log=print) -> list[dict]:
    fallback = previous_track(previous)
    if state is None or state["dead"]:
        return fallback
    try:
        series = fc.Series(fc.clean_series(points))
        resolve_pending(state, code, series)
        return merge_track(fallback, own_track(state, code))
    except Exception as e:
        _skip_code(e, log)
        return fallback


def record_forecast(state: dict | None, doc: dict, log=print) -> None:
    if state is None or state["dead"]:
        return
    try:
        basis = doc["basis"]["date"]
        record = state["records"].get(basis)
        if record is None or not isinstance(record.get("codes"), dict):
            record = {"date": basis, "codes": {}}
            state["records"][basis] = record
        if doc["code"] in record["codes"]:
            return
        record["codes"][doc["code"]] = {
            "target": doc["target"], "low": doc["low"], "likely": doc["likely"], "high": doc["high"],
            "actual": None, "actualDate": None, "hit": None}
        state["changed"] = True
    except Exception as e:
        _skip_code(e, log)


def _backup_unreadable(root) -> None:
    path = Path(root) / archive_store.ARCHIVE_DIR / f"{NAME}.json"
    if not path.is_file():
        return
    try:
        raw = path.read_bytes()
        if raw.strip() not in (b"", b"[]"):
            path.with_name(path.name + ".corrupt").write_bytes(raw)
    except OSError:
        pass


def flush(state: dict | None, log=print) -> bool:
    if state is None or state["dead"] or not state["changed"]:
        return False
    try:
        if state["loaded"] == 0:
            _backup_unreadable(state["root"])
        records = [state["records"][d] for d in sorted(state["records"])]
        written = archive_store.write(state["root"], NAME, records, state["loaded"], log)
    except Exception as e:
        _skip(state, e, log)
        return False
    state["changed"] = False
    return written
