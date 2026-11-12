from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 2
MAGIC = b"gheymat-seal"
HKDF_PATH_INFO = b"gheymat/v2/path"
HKDF_ENC_INFO = b"gheymat/v2/enc"
OPAQUE_PREFIX = "d/"
OPAQUE_LEN = 32
KEY_LEN = 32
NONCE_LEN = 12
TAG_LEN = 16
SIG_LEN = 64
DEFAULT_KID = 1
CREDENTIAL_LOOKALIKE = re.compile(r"AKID[A-Za-z0-9]{32}|(?:AKIA|ASIA)[A-Z2-7]{16}|AIza[A-Za-z0-9]{35}")
MAX_AGE = 2 * 60 * 60
MAX_FUTURE = 5 * 60
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
MAX_STATE_BYTES = 64 * 1024 * 1024
ENVELOPE_FIELDS = ("v", "kid", "issued", "nonce", "ciphertext", "sig")


class EnvelopeError(ValueError):
    pass


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError) as e:
        raise EnvelopeError("bad base64") from e


def subkey(master: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=info).derive(master)


def derive_keys(master: bytes) -> tuple[bytes, bytes]:
    if len(master) != KEY_LEN:
        raise ValueError("payload key must be 32 bytes")
    return subkey(master, HKDF_PATH_INFO), subkey(master, HKDF_ENC_INFO)


def opaque_path(master: bytes, logical: str) -> str:
    path_key, _ = derive_keys(master)
    digest = hmac.new(path_key, logical.encode("utf-8"), hashlib.sha256).hexdigest()
    return OPAQUE_PREFIX + digest[:OPAQUE_LEN]


def header(logical: str, issued: int, nonce: bytes, kid: int = DEFAULT_KID, version: int = VERSION) -> bytes:
    path = logical.encode("utf-8")
    if not 0 < len(path) <= 0xFFFF or not 0 <= kid <= 0xFF or not 0 <= version <= 0xFF:
        raise ValueError("header field out of range")
    if not 0 <= issued < 1 << 63 or len(nonce) != NONCE_LEN:
        raise ValueError("header field out of range")
    return MAGIC + bytes([version, kid]) + len(path).to_bytes(2, "big") + path + issued.to_bytes(8, "big") + nonce


@dataclass
class Sealer:
    payload_key: bytes
    signing_key: Ed25519PrivateKey
    kid: int = DEFAULT_KID
    path_key: bytes = field(init=False, repr=False)
    enc_key: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.path_key, self.enc_key = derive_keys(self.payload_key)

    @classmethod
    def from_env(cls) -> "Sealer | None":
        pk = os.environ.get("GHEYMAT_PAYLOAD_KEY")
        sk = os.environ.get("GHEYMAT_SIGNING_KEY")
        if not pk or not sk:
            return None
        payload, signing = unb64(pk), unb64(sk)
        if len(payload) != KEY_LEN or len(signing) != KEY_LEN:
            raise SystemExit("GHEYMAT_PAYLOAD_KEY / GHEYMAT_SIGNING_KEY must be base64 of 32 raw bytes")
        return cls(payload, Ed25519PrivateKey.from_private_bytes(signing))

    def opaque_path(self, logical: str) -> str:
        digest = hmac.new(self.path_key, logical.encode("utf-8"), hashlib.sha256).hexdigest()
        return OPAQUE_PREFIX + digest[:OPAQUE_LEN]

    def seal(self, logical: str, obj, issued: int | None = None) -> dict:
        issued = int(issued if issued is not None else time.time())
        plaintext = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        for _ in range(16):
            nonce = os.urandom(NONCE_LEN)
            aad = header(logical, issued, nonce, self.kid)
            ciphertext = ChaCha20Poly1305(self.enc_key).encrypt(nonce, plaintext, aad)
            signature = self.signing_key.sign(aad + ciphertext)
            envelope = {"v": VERSION, "kid": self.kid, "issued": issued, "nonce": b64(nonce),
                        "ciphertext": b64(ciphertext), "sig": b64(signature)}
            if not CREDENTIAL_LOOKALIKE.search(json.dumps(envelope)):
                return envelope
        return envelope


def _int_field(envelope: dict, name: str) -> int:
    value = envelope.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnvelopeError(f"{name} is not an integer")
    return value


def _str_field(envelope: dict, name: str) -> bytes:
    value = envelope.get(name)
    if not isinstance(value, str):
        raise EnvelopeError(f"{name} is not a string")
    return unb64(value)


def open_envelope(envelope: dict, payload_key: bytes,
                  public_key: Ed25519PublicKey | Mapping[int, Ed25519PublicKey], logical: str,
                  max_age: int | None = MAX_AGE, *, max_future: int | None = MAX_FUTURE,
                  last_accepted: int | None = None, now: float | None = None):
    if not isinstance(envelope, dict):
        raise EnvelopeError("envelope is not an object")
    if _int_field(envelope, "v") != VERSION:
        raise EnvelopeError("unsupported envelope version")
    kid = _int_field(envelope, "kid")
    if not 0 <= kid <= 0xFF:
        raise EnvelopeError("bad key id")
    if isinstance(public_key, Mapping):
        if kid not in public_key:
            raise EnvelopeError("unknown signing key")
        verifier = public_key[kid]
    else:
        verifier = public_key
    issued = _int_field(envelope, "issued")
    if not 0 <= issued < 1 << 63:
        raise EnvelopeError("issued out of range")
    nonce, ciphertext, signature = (_str_field(envelope, n) for n in ("nonce", "ciphertext", "sig"))
    if len(nonce) != NONCE_LEN or len(signature) != SIG_LEN or len(ciphertext) < TAG_LEN:
        raise EnvelopeError("bad field length")
    aad = header(logical, issued, nonce, kid)
    try:
        verifier.verify(signature, aad + ciphertext)
    except InvalidSignature as e:
        raise EnvelopeError("bad signature") from e
    if last_accepted is not None and issued < last_accepted:
        raise EnvelopeError("envelope older than the last accepted one")
    current = time.time() if now is None else now
    if max_future is not None and issued - current > max_future:
        raise EnvelopeError("envelope is dated in the future")
    if max_age is not None and current - issued > max_age:
        raise EnvelopeError("envelope too old")
    _, enc_key = derive_keys(payload_key)
    try:
        plaintext = ChaCha20Poly1305(enc_key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as e:
        raise EnvelopeError("cannot open envelope") from e
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise EnvelopeError("plaintext is not JSON") from e


def load_published(out: Path, logical: str, sealer: Sealer | None):
    plain = out / logical
    if plain.exists():
        try:
            return json.loads(plain.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
    if sealer is None:
        return None
    sealed = out / sealer.opaque_path(logical)
    if not sealed.exists():
        return None
    try:
        text = sealed.read_text(encoding="utf-8")
        if len(text) > MAX_STATE_BYTES:
            return None
        return open_envelope(json.loads(text), sealer.payload_key, sealer.signing_key.public_key(), logical,
                             max_age=None, max_future=None)
    except (ValueError, OSError, TypeError):
        return None
