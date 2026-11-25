from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import archive_store
import gheymat_forecast as fc

NAME = "forecast-log"
FILE_NAME = "forecast-log.bin"
INFO = b"forecast-log"
NONCE_LEN = 12
KEY_LEN = 32
TRACK_LIMIT = 12
TRACK_KEYS = ("basisDate", "target", "likely", "low", "high", "actual", "hit")

_warned = False


def _derive(master: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=INFO).derive(master)


def _encrypt(key: bytes, records: list[dict]) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(NONCE_LEN)
    plain = json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain, None))


def _decrypt(key: bytes, raw: bytes) -> list[dict]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = base64.b64decode(raw.strip(), validate=True)
    if len(blob) <= NONCE_LEN:
        raise ValueError("short")
    data = json.loads(AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], None))
    if not isinstance(data, list) or not all(isinstance(r, dict) and isinstance(r.get("date"), str) for r in data):
        raise ValueError("shape")
    return data


def _plain_paths(root) -> tuple[Path, Path]:
    plain = Path(root) / archive_store.ARCHIVE_DIR / f"{NAME}.json"
    return plain, plain.with_name(plain.name + ".corrupt")


def _remove_plain(root, log) -> None:
    for path in _plain_paths(root):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log("ai: track cleanup incomplete")


def _read_encrypted(path: Path, key: bytes, log) -> tuple[list[dict], bool] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        log("ai: track log unreadable, skipped")
        return None
    try:
        return _decrypt(key, raw), False
    except Exception:
        pass
    backup = path.with_name(path.name + ".corrupt")
    if backup.exists():
        try:
            kept = _decrypt(key, backup.read_bytes())
        except Exception:
            log("ai: track log unreadable, skipped")
            return None
        log("ai: track log restored from backup")
        return kept, True
    try:
        with backup.open("xb") as f:
            f.write(raw)
    except OSError:
        log("ai: track log unreadable, skipped")
        return None
    log("ai: track log unreadable, starting empty")
    return [], False


def _read_plain(plain: Path) -> list[dict] | None:
    try:
        raw = plain.read_bytes()
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("date"), str)]


def open_state(root, log=print, env=None) -> dict | None:
    global _warned
    if root is None:
        return None
    try:
        import headline_log
        master = headline_log.master_key(env)
        if master is None:
            if not _warned:
                _warned = True
                log("ai: track off (no key)")
            return None
        key = _derive(master)
        path = Path(root) / FILE_NAME
        records: list[dict] = []
        changed = False
        drop_plain = False
        drop_backup = False
        plain, _ = _plain_paths(root)
        has_plain = plain.is_file()
        if path.exists():
            found = _read_encrypted(path, key, log)
            if found is None:
                return None
            records, drop_backup = found
            changed = drop_backup
            _remove_plain(root, log)
        elif has_plain:
            imported = _read_plain(plain)
            if imported is None:
                log("ai: track log unreadable, skipped")
                return None
            records = imported
            changed = True
            drop_plain = True
        else:
            _remove_plain(root, log)
    except Exception as e:
        log(f"ai: track skipped: {type(e).__name__}")
        return None
    return {"root": root, "key": key, "records": {r["date"]: r for r in records}, "loaded": len(records),
            "changed": changed, "dead": False, "drop_plain": drop_plain, "drop_backup": drop_backup}


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


def _write_atomic(root, key: bytes, records: list[dict]) -> None:
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_encrypt(key, records))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, folder / FILE_NAME)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def flush(state: dict | None, log=print) -> bool:
    if state is None or state["dead"] or not state["changed"]:
        return False
    try:
        records = [state["records"][d] for d in sorted(state["records"])]
        if len(records) < state["loaded"]:
            log("ai: track log kept (refusing to shrink)")
            return False
        _write_atomic(state["root"], state["key"], records)
    except Exception as e:
        _skip(state, e, log)
        return False
    state["changed"] = False
    if state.get("drop_plain"):
        state["drop_plain"] = False
        _remove_plain(state["root"], log)
    if state.get("drop_backup"):
        state["drop_backup"] = False
        try:
            (Path(state["root"]) / (FILE_NAME + ".corrupt")).unlink(missing_ok=True)
        except OSError:
            log("ai: track cleanup incomplete")
    return True
