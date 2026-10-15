#!/usr/bin/env python3
"""Integrity gate for the sealed static channel (run in CI after gheymat_snapshot.py, before deploy).

Opens the sealed `v1/latest` envelope in the dist directory using only the Ed25519 PUBLIC key for
signature verification and the master payload key (GHEYMAT_PAYLOAD_KEY) for the opaque path and the
decryption subkey. The signing secret is never read. Prints a single fixed line and never any key, path
or exception text.

Usage: python tools/verify_sealed.py dist [--expect-rates 37] [--max-age 900] [--public-key <b64>]
Exit 0 only when the envelope verifies, decrypts, matches the logical path and carries the expected rates.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gheymat_seal import DEFAULT_KID, KEY_LEN, MAX_ENVELOPE_BYTES, open_envelope, opaque_path, unb64  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: E402

PUBLIC_KEY_B64 = "W4Sr3k2r9u76QrRcY94/Npv7Z9JolJjrrW25Z45y5J8="
LOGICAL = "v1/latest"
EXPECTED_RATES = 37
MAX_AGE_SECONDS = 900


def verify(dist: Path, payload_key: bytes, public_keys: dict[int, Ed25519PublicKey], expect_rates: int, max_age: int) -> int:
    sealed = dist / opaque_path(payload_key, LOGICAL)
    text = sealed.read_text(encoding="utf-8")
    if len(text) > MAX_ENVELOPE_BYTES:
        raise ValueError("envelope too large")
    snapshot = open_envelope(json.loads(text), payload_key, public_keys, LOGICAL, max_age=max_age)
    rates = snapshot.get("rates")
    if not isinstance(rates, list):
        raise ValueError("no rates")
    codes = [r.get("code") for r in rates if isinstance(r, dict)]
    if len(codes) != expect_rates or len(set(codes)) != expect_rates or not all(codes):
        raise ValueError("unexpected rate count")
    if snapshot.get("source") != "bonbast" or not snapshot.get("fetchedAt"):
        raise ValueError("unexpected snapshot shape")
    return len(codes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dist")
    ap.add_argument("--expect-rates", type=int, default=EXPECTED_RATES)
    ap.add_argument("--max-age", type=int, default=MAX_AGE_SECONDS)
    ap.add_argument("--public-key", default=PUBLIC_KEY_B64, help="base64 Ed25519 public key for kid 1 (tests only)")
    args = ap.parse_args()
    raw = os.environ.get("GHEYMAT_PAYLOAD_KEY")
    if not raw:
        print("verify_sealed: GHEYMAT_PAYLOAD_KEY is not set; refusing to deploy an unsealed site", file=sys.stderr)
        return 1
    try:
        payload_key = unb64(raw)
        if len(payload_key) != KEY_LEN:
            raise ValueError("bad key length")
        public_keys = {DEFAULT_KID: Ed25519PublicKey.from_public_bytes(unb64(args.public_key))}
        count = verify(Path(args.dist), payload_key, public_keys, args.expect_rates, args.max_age)
    except Exception:
        print(f"verify_sealed: sealed {LOGICAL} FAILED verification; not deploying", file=sys.stderr)
        return 1
    print(f"verify_sealed: sealed {LOGICAL} ok, {count} rates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
