from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FILE_NAME = "headline-log.jsonl"
MAX_ROWS = 2000
INFO = b"headline-log"
NONCE_LEN = 12
KEY_LEN = 32
FIELDS = ("id", "first_seen", "title", "category", "model_effect", "model_confidence", "model", "ranking_version")


class LogError(Exception):
    pass


def master_key(env=None) -> bytes | None:
    env = os.environ if env is None else env
    text = env.get("GHEYMAT_PAYLOAD_KEY")
    if not text:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None
    return raw if len(raw) == KEY_LEN else None


def derive(master: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=INFO).derive(master)


def log_path(state_dir) -> Path:
    return Path(state_dir) / FILE_NAME


def encrypt_row(key: bytes, row: dict) -> str:
    nonce = os.urandom(NONCE_LEN)
    plain = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain, None)).decode("ascii")


def decrypt_row(key: bytes, line: str) -> dict:
    try:
        blob = base64.b64decode(line.strip(), validate=True)
        if len(blob) <= NONCE_LEN:
            raise ValueError("short")
        obj = json.loads(AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], None))
    except (binascii.Error, ValueError, InvalidTag) as e:
        raise LogError("wrong key or corrupt line") from e
    if not isinstance(obj, dict):
        raise LogError("wrong key or corrupt line")
    return obj


def read_rows(state_dir, key: bytes) -> list[dict]:
    path = log_path(state_dir)
    if not path.exists():
        return []
    try:
        text = path.read_bytes().decode("ascii")
    except UnicodeDecodeError as e:
        raise LogError("wrong key or corrupt line") from e
    return [decrypt_row(key, line) for line in text.splitlines() if line.strip()]


def append(state_dir, rows: list[dict], key: bytes, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = read_rows(state_dir, key)
    seen = {r.get("id") for r in kept}
    for row in rows:
        if row.get("id") in seen:
            continue
        seen.add(row["id"])
        kept.append({**{k: row.get(k) for k in FIELDS}, "first_seen": row.get("first_seen") or stamp})
    kept = kept[-MAX_ROWS:]
    path = log_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(encrypt_row(key, r) + "\n" for r in kept), encoding="ascii")
    os.replace(tmp, path)
    return kept


_warned = False


def collect(rows: list[dict], env=None, now: datetime | None = None, log=print) -> None:
    global _warned
    env = os.environ if env is None else env
    try:
        state_dir = env.get("GHEYMAT_STATE_DIR", "")
        if not state_dir or not rows:
            return
        key = master_key(env)
        if key is None:
            if not _warned:
                _warned = True
                log("Headline log: off (no key)")
            return
        try:
            kept = append(state_dir, rows, derive(key), now)
        except LogError:
            path = log_path(state_dir)
            os.replace(path, path.with_name(path.name + ".unreadable"))
            kept = append(state_dir, rows, derive(key), now)
        log(f"Headline log: {len(kept)} rows since {str(kept[0]['first_seen'])[:10]}")
    except Exception as e:
        log(f"Headline log: skipped ({type(e).__name__})")
