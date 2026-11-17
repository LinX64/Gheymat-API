from __future__ import annotations

import base64
import binascii
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ENV_SOURCES = "GHEYMAT_LEAD_SOURCES"
ENV_KEY = "GHEYMAT_PAYLOAD_KEY"
ENV_STATE = "GHEYMAT_STATE_DIR"
DAY_FILE = "lead-day.bin"
INFO = b"lead-samples"
NONCE_LEN = 12
KEY_LEN = 32
MAX_SOURCES = 6
REQUEST_TIMEOUT = 5.0
TOTAL_BUDGET = 10.0
MAX_BODY = 2_000_000
MAX_SAMPLES = 20_000
FUTURE_SLACK = 120
MAX_GAP = 0.05
THROTTLE_SECONDS = 1800
MARKER = "_marker"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
TS_UNITS = ("s", "ms", "iso")

_warned = False


class StoreError(Exception):
    pass


def _mono() -> float:
    return time.monotonic()


def _finite_pos(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _valid_path(p) -> bool:
    return (isinstance(p, list) and 0 < len(p) <= 12
            and all((isinstance(k, str) and k) or (isinstance(k, int) and not isinstance(k, bool) and k >= 0) for k in p))


def _valid_source(s) -> bool:
    if not isinstance(s, dict):
        return False
    if not isinstance(s.get("id"), str) or not ID_PATTERN.match(s["id"]):
        return False
    url = s.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 2000:
        return False
    has_value = "value_path" in s
    has_range = "lo_path" in s or "hi_path" in s
    if has_value == has_range:
        return False
    if has_value:
        if not _valid_path(s["value_path"]):
            return False
    elif not (_valid_path(s.get("lo_path")) and _valid_path(s.get("hi_path"))):
        return False
    if s.get("ts_path") is not None:
        if not _valid_path(s["ts_path"]) or s.get("ts_unit") not in TS_UNITS:
            return False
        age = s.get("max_age_seconds")
        if isinstance(age, bool) or not isinstance(age, int) or age <= 0:
            return False
    if "scale" in s and not _finite_pos(s["scale"]):
        return False
    if s.get("factor") is not None and not _finite_pos(s["factor"]):
        return False
    chk = s.get("check")
    if chk is not None:
        if not isinstance(chk, dict) or not isinstance(chk.get("against"), str) or not chk["against"]:
            return False
        lo, hi = chk.get("min_ratio"), chk.get("max_ratio")
        if not (_finite_pos(lo) and _finite_pos(hi) and lo < hi):
            return False
    return True


def load_config(env) -> list[dict] | None:
    text = (env or {}).get(ENV_SOURCES)
    if not text or not str(text).strip():
        return None
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(raw, list) or not raw:
        return None
    kept, seen = [], set()
    for s in raw:
        if _valid_source(s) and s["id"] not in seen:
            seen.add(s["id"])
            kept.append(s)
    dropped = len(raw) - len(kept)
    if dropped:
        print(f"lead: {dropped} invalid source{'s' if dropped != 1 else ''} dropped")
    if len(kept) > MAX_SOURCES:
        print(f"lead: {len(kept) - MAX_SOURCES} sources over the limit dropped")
        kept = kept[:MAX_SOURCES]
    return kept or None


def derive_key(env) -> bytes | None:
    text = (env or {}).get(ENV_KEY)
    if not text:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None
    if len(raw) != KEY_LEN:
        return None
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=INFO).derive(raw)


def _dig(obj, path):
    cur = obj
    for k in path:
        if isinstance(k, int):
            if not isinstance(cur, list) or k >= len(cur):
                return None
            cur = cur[k]
        else:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
    return cur


def _number(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, str):
        try:
            x = float(x.strip().replace(",", ""))
        except ValueError:
            return None
    if isinstance(x, (int, float)):
        x = float(x)
        return x if math.isfinite(x) else None
    return None


def _parse_ts(x, unit) -> float | None:
    if unit == "iso":
        if not isinstance(x, str):
            return None
        try:
            dt = datetime.fromisoformat(x.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return None
        v = dt.timestamp()
    else:
        v = _number(x)
        if v is None:
            return None
        if unit == "ms":
            v /= 1000.0
    return v if math.isfinite(v) and v > 0 else None


def _epoch(now) -> float:
    if isinstance(now, datetime):
        return now.timestamp() if now.tzinfo else now.replace(tzinfo=timezone.utc).timestamp()
    return float(now)


def _reference_value(reference, key):
    if not isinstance(reference, dict):
        return None
    for k in (key, key.lower(), key.upper()):
        v = reference.get(k)
        if _finite_pos(v):
            return float(v)
    return None


def _extract(src, body, now_s, reference):
    t = None
    if src.get("ts_path") is not None:
        ts = _parse_ts(_dig(body, src["ts_path"]), src["ts_unit"])
        if ts is None:
            return None
        if now_s - ts > src["max_age_seconds"] or ts - now_s > FUTURE_SLACK:
            return None
        t = int(ts)
    else:
        t = int(now_s // 60 * 60)
    if "value_path" in src:
        raw = _number(_dig(body, src["value_path"]))
        if raw is None or raw <= 0:
            return None
    else:
        lo = _number(_dig(body, src["lo_path"]))
        hi = _number(_dig(body, src["hi_path"]))
        if lo is None or hi is None or lo <= 0 or hi <= 0 or lo > hi:
            return None
        raw = (lo + hi) / 2.0
        if (hi - lo) / raw > MAX_GAP:
            return None
    value = raw * float(src.get("scale", 1)) * float(src.get("factor") or 1)
    if not _finite_pos(value):
        return None
    out = {"series": src["id"], "t": t, "got": int(now_s), "value": value}
    chk = src.get("check")
    if chk:
        ref = _reference_value(reference, chk["against"])
        if ref is None:
            out["unchecked"] = True
        else:
            ratio = value / ref
            if not (chk["min_ratio"] <= ratio <= chk["max_ratio"]):
                return None
    return out


def _default_http():
    import requests
    return requests.Session()


def _read_body(resp):
    if getattr(resp, "status_code", None) != 200:
        return None
    length = (getattr(resp, "headers", None) or {}).get("Content-Length")
    try:
        if length is not None and int(length) > MAX_BODY:
            return None
    except (TypeError, ValueError):
        return None
    if hasattr(resp, "iter_content"):
        chunks, total = [], 0
        for chunk in resp.iter_content(65536):
            total += len(chunk)
            if total > MAX_BODY:
                return None
            chunks.append(chunk)
        data = b"".join(chunks)
    else:
        data = resp.content
        if len(data) > MAX_BODY:
            return None
    return data


def _fetch(http, src, timeout):
    resp = http.get(src["url"], timeout=timeout, allow_redirects=False, stream=True)
    try:
        data = _read_body(resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()
    if data is None:
        return None
    return json.loads(data.decode("utf-8"))


def sample(env, now, log=print, http=None, reference=None) -> list[dict]:
    global _warned
    sources = load_config(env)
    if sources is None:
        return []
    if derive_key(env) is None:
        if not _warned:
            _warned = True
            log("lead: off (no key)")
        return []
    now_s = _epoch(now)
    http = http or _default_http()
    deadline = _mono() + TOTAL_BUDGET
    results: list = [None] * len(sources)
    threads = []

    def work(i, src):
        try:
            body = _fetch(http, src, min(REQUEST_TIMEOUT, TOTAL_BUDGET))
            results[i] = ("ok", None if body is None else _extract(src, body, now_s, reference))
        except Exception as e:
            results[i] = ("err", type(e).__name__)

    for i, src in enumerate(sources):
        t = threading.Thread(target=work, args=(i, src), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(max(0.0, deadline - _mono()))
    out, seen, errors, answered = [], set(), {}, 0
    for res in list(results):
        if res is None:
            errors["Deadline"] = errors.get("Deadline", 0) + 1
            continue
        kind, val = res
        if kind == "err":
            errors[val] = errors.get(val, 0) + 1
            continue
        if val is None:
            continue
        key = (val["series"], val["t"])
        if key in seen:
            continue
        seen.add(key)
        out.append(val)
        answered += 1
    msg = f"lead: {answered} of {len(sources)} series answered"
    if errors:
        msg += "; errors " + ", ".join(f"{k}x{v}" for k, v in sorted(errors.items()))
    log(msg)
    return out


def _encrypt(key, rec) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(NONCE_LEN)
    plain = json.dumps(rec, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain, None)).decode("ascii")


def _decrypt(key, line) -> dict:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        blob = base64.b64decode(line.strip(), validate=True)
        if len(blob) <= NONCE_LEN:
            raise ValueError("short")
        obj = json.loads(AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], None))
    except (binascii.Error, ValueError, InvalidTag) as e:
        raise StoreError("unreadable") from e
    if not isinstance(obj, dict):
        raise StoreError("unreadable")
    return obj


def _records(path: Path, key) -> list[dict]:
    if not path.exists():
        return []
    try:
        text = path.read_bytes().decode("ascii")
    except UnicodeDecodeError as e:
        raise StoreError("unreadable") from e
    return [_decrypt(key, ln) for ln in text.splitlines() if ln.strip()]


def _keep_backup(path: Path) -> None:
    backup = path.with_name(path.name + ".unreadable")
    try:
        data = path.read_bytes()
        with open(backup, "xb") as fh:
            fh.write(data)
    except FileExistsError:
        pass
    except OSError:
        pass


def _valid_sample(s) -> bool:
    return (isinstance(s, dict) and isinstance(s.get("series"), str) and s["series"] != MARKER
            and isinstance(s.get("t"), int) and not isinstance(s["t"], bool) and _finite_pos(s.get("value")))


def _store(directory, file_name, samples, key, marker_t=None) -> int:
    if key is None:
        return 0
    path = Path(directory) / file_name
    try:
        existing = _records(path, key)
    except StoreError:
        _keep_backup(path)
        return 0
    marker = next((r for r in existing if r.get("series") == MARKER), None)
    data = [r for r in existing if r.get("series") != MARKER]
    seen = {(r.get("series"), r.get("t")) for r in data}
    added = 0
    for s in samples:
        if not _valid_sample(s):
            continue
        k = (s["series"], s["t"])
        if k in seen:
            continue
        seen.add(k)
        rec = {"series": s["series"], "t": s["t"], "got": s.get("got"), "value": s["value"]}
        if s.get("unchecked"):
            rec["unchecked"] = True
        data.append(rec)
        added += 1
    if len(data) > MAX_SAMPLES:
        data = data[-MAX_SAMPLES:]
    if marker_t is not None:
        marker = {"series": MARKER, "t": int(marker_t)}
    if added == 0 and marker_t is None:
        return 0
    lines = [_encrypt(key, r) + "\n" for r in data]
    if marker is not None:
        lines.append(_encrypt(key, marker) + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(lines), encoding="ascii")
    os.replace(tmp, path)
    return added


def append(directory, file_name, samples, key, now=None) -> int:
    return _store(directory, file_name, samples, key)


def read(directory, file_name, key) -> list[dict]:
    if key is None:
        return []
    path = Path(directory) / file_name
    try:
        recs = _records(path, key)
    except StoreError:
        return []
    return [r for r in recs if r.get("series") != MARKER]


def summary(samples) -> dict:
    rows = [s for s in samples if isinstance(s, dict)]
    return {"series": len({s.get("series") for s in rows}), "total": len(rows),
            "unchecked": sum(1 for s in rows if s.get("unchecked"))}


def _marker_time(directory, file_name, key):
    try:
        recs = _records(Path(directory) / file_name, key)
    except StoreError:
        return None, True
    for r in recs:
        if r.get("series") == MARKER and isinstance(r.get("t"), int):
            return r["t"], False
    return None, False


def day_run(env, now, live_prices, log=print) -> None:
    try:
        state_dir = (env or {}).get(ENV_STATE)
        if not state_dir or load_config(env) is None:
            return
        key = derive_key(env)
        if key is None:
            sample(env, now, log)
            return
        now_s = _epoch(now)
        last, broken = _marker_time(state_dir, DAY_FILE, key)
        if broken:
            log("lead: store unreadable")
            return
        if last is not None and 0 <= now_s - last < THROTTLE_SECONDS:
            return
        rows = sample(env, now, log, reference=live_prices)
        stored = _store(state_dir, DAY_FILE, rows, key, marker_t=now_s)
        log(f"lead: {stored} stored")
    except Exception as e:
        try:
            log(f"lead: skipped ({type(e).__name__})")
        except Exception:
            pass
