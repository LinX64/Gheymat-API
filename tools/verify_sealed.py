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
import site_versions  # noqa: E402
from gheymat_seal import DEFAULT_KID, KEY_LEN, MAX_ENVELOPE_BYTES, MAX_STATE_BYTES, open_envelope, opaque_path, unb64  # noqa: E402

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


CORE_DOCS = ("latest", "instruments", "daily.json", "history/{c}", "longhistory/{c}", "intraday/{c}")
AI_DOCS = ("ai/forecast/{c}", "ai/news", "ai/brief")


def relative_logicals(groups, codes) -> list[str]:
    """Logical paths below a version prefix for the given document groups (core, ai), per instrument code."""
    templates = {"core": CORE_DOCS, "ai": AI_DOCS}
    out: list[str] = []
    for group in groups:
        for t in templates[group]:
            out.extend([t.format(c=c) for c in sorted(codes)] if "{c}" in t else [t])
    return out


def all_codes() -> set[str]:
    direct, optional = load_instrument_codes()
    return direct | optional


def verify_site(site: Path, payload_key: bytes, public_keys: dict[int, Ed25519PublicKey]) -> dict[str, int]:
    """Check an assembled site: every file under /<id>/d verifies for its logical path, /v1-style
    (non-derived) copies are byte-equal to the root copies, versions.json and _headers exist."""
    for base, dirs, files in os.walk(site, followlinks=False):
        if any(os.path.islink(os.path.join(base, n)) for n in dirs + files):
            raise ValueError("symbolic link in site")
    codes = all_codes()
    counts: dict[str, int] = {}
    for v in site_versions.VERSIONS:
        names = {opaque_path(payload_key, f"{v['id']}/{rel}"): f"{v['id']}/{rel}"
                 for rel in relative_logicals(v["docs"], codes)}
        folder = site / v["id"] / "d"
        files = sorted(folder.iterdir()) if folder.is_dir() else []
        for f in files:
            logical = names.get("d/" + f.name)
            if logical is None:
                raise ValueError("unclaimed file")
            data = f.read_bytes()
            if len(data) > MAX_STATE_BYTES:  # same bound as load_published: the daily archive is several MB
                raise ValueError("envelope too large")
            open_envelope(json.loads(data), payload_key, public_keys, logical, max_age=None)
            if v.get("derivesFrom") is None and (site / "d" / f.name).read_bytes() != data:
                raise ValueError("copy differs from root")
        counts[v["id"]] = len(files)
        source = v.get("derivesFrom")
        if v["docs"] and not files and (counts[source] > 0 if source else (site / "d").is_dir()
                                        and any((site / "d").iterdir())):
            raise ValueError("version has no documents")
    if json.loads((site / "versions.json").read_text(encoding="utf-8")).get("schema") != site_versions.SCHEMA:
        raise ValueError("bad registry")
    if not (site / "_headers").is_file():
        raise ValueError("no headers file")
    return counts


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
    ap.add_argument("dist", nargs="?")
    ap.add_argument("--site", default=None, help="verify an assembled versioned site instead of a dist directory")
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
        if args.site:
            counts = verify_site(Path(args.site), payload_key, public_keys)
            print("verify_sealed: site ok, " + ", ".join(f"{k} {n} files" for k, n in counts.items()))
            return 0
        if not args.dist:
            raise ValueError("no dist")
        count = verify(Path(args.dist), payload_key, public_keys, args.expect_rates, args.max_age)
    except Exception:
        what = "site" if args.site else f"sealed {LOGICAL}"
        print(f"verify_sealed: {what} FAILED verification; not deploying", file=sys.stderr)
        return 1
    print(f"verify_sealed: sealed {LOGICAL} ok, {count} rates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
