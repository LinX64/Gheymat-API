from __future__ import annotations

import base64
import binascii
import json
import math
import os
import tempfile
from pathlib import Path

FILE_NAME = "live-close.bin"
ENV_KEY = "GHEYMAT_PAYLOAD_KEY"
ENV_STATE = "GHEYMAT_STATE_DIR"
INFO = b"live-close"
NONCE_LEN = 12
KEY_LEN = 32
MAX_DAYS = 1096

_warned = False


class StoreError(Exception):
    pass


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


def _price(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _encrypt(key: bytes, data: dict) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(NONCE_LEN)
    plain = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain, None))


def _decrypt(key: bytes, raw: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = base64.b64decode(raw.strip(), validate=True)
    if len(blob) <= NONCE_LEN:
        raise StoreError("short")
    data = json.loads(AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], None))
    if not isinstance(data, dict):
        raise StoreError("shape")
    for day, codes in data.items():
        if not isinstance(day, str) or not isinstance(codes, dict):
            raise StoreError("shape")
        if not all(isinstance(c, str) and _price(v) for c, v in codes.items()):
            raise StoreError("shape")
    return data


def _keep_backup(path: Path, raw: bytes) -> None:
    backup = path.with_name(path.name + ".corrupt")
    try:
        with open(backup, "xb") as fh:
            fh.write(raw)
    except OSError:
        pass


def _load(path: Path, key: bytes) -> dict | None:
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return _decrypt(key, raw)
    except Exception:
        _keep_backup(path, raw)
        return None


def _write_atomic(path: Path, key: bytes, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_encrypt(key, data))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(directory, day, prices, key) -> bool:
    if key is None or not isinstance(day, str) or not day or not isinstance(prices, dict):
        return False
    fresh = {c: float(v) for c, v in prices.items() if isinstance(c, str) and c and _price(v)}
    if not fresh:
        return False
    path = Path(directory) / FILE_NAME
    data = _load(path, key)
    if data is None:
        return False
    loaded = len(data)
    current = data.get(day, {})
    merged = dict(current)
    merged.update(fresh)
    if day in data and merged == current:
        return False
    data[day] = merged
    if len(data) > MAX_DAYS:
        drop = sorted(data)[:len(data) - MAX_DAYS]
        if day in drop:
            return False
        for old in drop:
            del data[old]
    if len(data) < loaded:
        return False
    _write_atomic(path, key, data)
    return True


def read(directory, key) -> dict:
    if key is None:
        return {}
    try:
        return _decrypt(key, (Path(directory) / FILE_NAME).read_bytes())
    except Exception:
        return {}


def day_hook(env, now, live_prices, log=print) -> bool:
    global _warned
    try:
        state_dir = (env or {}).get(ENV_STATE)
        if not state_dir:
            return False
        key = derive_key(env)
        if key is None:
            if not _warned:
                _warned = True
                log("live-close: off (no key)")
            return False
        import gheymat_ai
        day = gheymat_ai.default_today(now).isoformat()
        return record(state_dir, day, dict(live_prices or {}), key)
    except Exception:
        return False
