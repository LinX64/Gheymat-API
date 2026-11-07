#!/usr/bin/env python3
"""Integrity gate for the sealed static channel (run in CI after gheymat_snapshot.py, before deploy).

Opens the sealed `v1/latest` envelope in the dist directory using only the Ed25519 PUBLIC key for
signature verification and the master payload key (GHEYMAT_PAYLOAD_KEY) for the opaque path and the
decryption subkey. The signing secret is never read. Prints a single fixed line and never any key, path
or exception text.

Usage: python tools/verify_sealed.py dist [--expect-rates 37] [--max-age 900] [--public-key <b64>]
Exit 0 only when the envelope verifies, decrypts, matches the logical path and carries acceptable rates.
Without --expect-rates (the normal, workflow-invoked path): every present code must be a known code from
tools/instruments.json and appear once, at least MIN_DIRECT (29) of the direct codes (those with a bonbast key)
must be present, and `source` must be one of the publisher's sources (CONTRACT.md "Static publisher sources"):
a source outage may drop a few direct codes (hansha has no ounce or usd-quoted btc), so a full 37 is no longer
required, but a thin publish or an unrecognized code still fails closed. --expect-rates stays as a legacy
exact-count override (tests only).
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

HERE = Path(__file__).resolve().parent
PUBLIC_KEY_B64 = "W4Sr3k2r9u76QrRcY94/Npv7Z9JolJjrrW25Z45y5J8="
LOGICAL = "v1/latest"
MAX_AGE_SECONDS = 900


MIN_DIRECT = 29  # same floor gheymat_snapshot.py publishes at
SOURCES = {"hansha", "bonbast"}


def load_instrument_codes() -> tuple[set[str], set[str]]:
    """(direct codes, optional codes) from tools/instruments.json.

    Direct = the free-market quotes every source combination aims to carry (they have a bonbast key);
    optional = computed cross-rates plus the hansha-only rows, which may be absent from any given publish."""
    data = json.loads((HERE / "instruments.json").read_text(encoding="utf-8"))
    direct = {d["code"] for d in data if not d.get("computed") and d.get("bonbast_key")}
    optional = {d["code"] for d in data} - direct
    return direct, optional


def verify(dist: Path, payload_key: bytes, public_keys: dict[int, Ed25519PublicKey],
           expect_rates: int | None, max_age: int) -> int:
    sealed = dist / opaque_path(payload_key, LOGICAL)
    text = sealed.read_text(encoding="utf-8")
    if len(text) > MAX_ENVELOPE_BYTES:
        raise ValueError("envelope too large")
    snapshot = open_envelope(json.loads(text), payload_key, public_keys, LOGICAL, max_age=max_age)
    rates = snapshot.get("rates")
    if not isinstance(rates, list):
        raise ValueError("no rates")
    codes = [r.get("code") for r in rates if isinstance(r, dict)]
    if len(codes) != len(rates) or not all(codes) or len(set(codes)) != len(codes):
        raise ValueError("bad rate codes")
    if expect_rates is not None:
        if len(codes) != expect_rates:
            raise ValueError("unexpected rate count")
    else:
        direct, optional = load_instrument_codes()
        code_set = set(codes)
        if len(code_set & direct) < MIN_DIRECT or not code_set.issubset(direct | optional):
            raise ValueError("unexpected rate codes")
    if snapshot.get("source") not in SOURCES or not snapshot.get("fetchedAt"):
        raise ValueError("unexpected snapshot shape")
    return len(codes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dist")
    ap.add_argument("--expect-rates", type=int, default=None,
                     help="legacy exact-count override; default is the instrument-table-driven check "
                          "described above")
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
