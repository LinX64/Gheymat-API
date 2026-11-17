#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accuracy_report

PUBLIC_LEN = 32
NONCE_LEN = accuracy_report.NONCE_LEN


def keygen(private_out: Path) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    private = X25519PrivateKey.generate()
    raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    fd = os.open(private_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(base64.b64encode(raw))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(public).decode("ascii")


def decrypt_report(private_b64: bytes, sealed: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    private = X25519PrivateKey.from_private_bytes(base64.b64decode(private_b64.strip(), validate=True))
    blob = base64.b64decode(sealed.strip(), validate=True)
    if len(blob) <= PUBLIC_LEN + NONCE_LEN:
        raise ValueError("short")
    peer = X25519PublicKey.from_public_bytes(blob[:PUBLIC_LEN])
    key = accuracy_report._hkdf(private.exchange(peer), accuracy_report.REPORT_INFO)
    return AESGCM(key).decrypt(blob[PUBLIC_LEN:PUBLIC_LEN + NONCE_LEN], blob[PUBLIC_LEN + NONCE_LEN:], None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Owner tool for the encrypted accuracy report.")
    sub = ap.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("keygen")
    gen.add_argument("--private-out", required=True)
    dec = sub.add_parser("decrypt")
    dec.add_argument("--private", required=True)
    dec.add_argument("--in", dest="source", required=True)
    dec.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "keygen":
            print(keygen(Path(args.private_out)))
            return 0
        plain = decrypt_report(Path(args.private).read_bytes(), Path(args.source).read_bytes())
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(plain)
        return 0
    except Exception as e:
        print(f"night_export: failed ({type(e).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
