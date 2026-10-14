"""Sealed static channel for the Gheymat app (see Gheymat/CONTRACT.md "Sealed static channel").

Every published document is written at an opaque path derived from its logical path with HMAC-SHA256,
sealed with ChaCha20-Poly1305 (AAD = "gheymat-v1:" + logical path) and signed with Ed25519.
Keys come from the environment: GHEYMAT_PAYLOAD_KEY (32 bytes, base64) and GHEYMAT_SIGNING_KEY
(Ed25519 private key, 32 raw bytes, base64).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

VERSION = 1
AAD_PREFIX = b"gheymat-v1:"
OPAQUE_PREFIX = "d/"
OPAQUE_LEN = 20


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


@dataclass
class Sealer:
    payload_key: bytes
    signing_key: Ed25519PrivateKey

    @classmethod
    def from_env(cls) -> "Sealer | None":
        pk = os.environ.get("GHEYMAT_PAYLOAD_KEY")
        sk = os.environ.get("GHEYMAT_SIGNING_KEY")
        if not pk or not sk:
            return None
        return cls(unb64(pk), Ed25519PrivateKey.from_private_bytes(unb64(sk)))

    def opaque_path(self, logical: str) -> str:
        digest = hmac.new(self.payload_key, logical.encode("utf-8"), hashlib.sha256).hexdigest()
        return OPAQUE_PREFIX + digest[:OPAQUE_LEN]

    def seal(self, logical: str, obj, issued: int | None = None) -> dict:
        issued = int(issued if issued is not None else time.time())
        plaintext = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        aad = AAD_PREFIX + logical.encode("utf-8")
        ciphertext = ChaCha20Poly1305(self.payload_key).encrypt(nonce, plaintext, aad)
        signed = nonce + ciphertext + issued.to_bytes(8, "big") + aad
        signature = self.signing_key.sign(signed)
        return {"v": VERSION, "path": logical, "issued": issued, "nonce": b64(nonce),
                "ciphertext": b64(ciphertext), "sig": b64(signature)}


def open_envelope(envelope: dict, payload_key: bytes, public_key: Ed25519PublicKey, logical: str, max_age: int | None = None):
    if envelope.get("v") != VERSION or envelope.get("path") != logical:
        raise ValueError("envelope does not match the requested path")
    nonce, ciphertext = unb64(envelope["nonce"]), unb64(envelope["ciphertext"])
    issued = int(envelope["issued"])
    aad = AAD_PREFIX + logical.encode("utf-8")
    public_key.verify(unb64(envelope["sig"]), nonce + ciphertext + issued.to_bytes(8, "big") + aad)
    if max_age is not None and time.time() - issued > max_age:
        raise ValueError("envelope too old")
    return json.loads(ChaCha20Poly1305(payload_key).decrypt(nonce, ciphertext, aad))
