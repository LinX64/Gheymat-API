#!/usr/bin/env python3
"""Assemble the versioned static site from a publisher output directory.

    python tools/assemble_site.py --src dist --out site

The legacy layout (root `d/`, pages) is copied unchanged. Each version in tools/site_versions.py then gets its
own `<id>/d/` folder: a version that derives from none gets byte-identical copies of the root documents,
a derived version gets the documents read back (verified), transformed and sealed again for its own logical
paths. `versions.json` and `_headers` are generated from the registry. Needs GHEYMAT_PAYLOAD_KEY and
GHEYMAT_SIGNING_KEY; never prints key material.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_versions  # noqa: E402
import verify_sealed  # noqa: E402
from gheymat_seal import EnvelopeError, MAX_STATE_BYTES, Sealer, open_envelope  # noqa: E402

ROOT_ONLY = ("health",)  # published at the root only, claimed so they are not reported as orphans
DROP = (".git", ".nojekyll", "_headers", "versions.json", "archive")


def read_sealed(src: Path, logical: str, sealer: Sealer):
    """(document, issued) from a sealed copy, verified for its logical path; None when absent or unreadable."""
    path = src / sealer.opaque_path(logical)
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > MAX_STATE_BYTES:
            return None
        envelope = json.loads(text)
        doc = open_envelope(envelope, sealer.payload_key, sealer.signing_key.public_key(), logical,
                            max_age=None, max_future=None)
        return doc, int(envelope["issued"])
    except (OSError, ValueError, TypeError, KeyError, EnvelopeError):
        return None


def check_paths(src: Path, out: Path) -> None:
    src, out = src.resolve(), out.resolve()
    if not src.is_dir():
        raise SystemExit("assemble_site: source directory not found")
    if out == src or src in out.parents or out in src.parents:
        raise SystemExit("assemble_site: output must be separate from the source (not equal, inside or containing it)")


def has_symlink(root: Path) -> bool:
    for base, dirs, files in os.walk(root, followlinks=False):
        if any(os.path.islink(os.path.join(base, n)) for n in dirs + files):
            return True
    return False


def assemble(src: Path, out: Path, sealer: Sealer, registry: list[dict] | None = None, now_iso: str | None = None,
             log=print) -> dict:
    registry = site_versions.VERSIONS if registry is None else registry
    site_versions.validate(registry)
    check_paths(src, out)
    if has_symlink(src):
        raise SystemExit("assemble_site: source contains a symbolic link")
    if out.exists():
        if out.is_symlink() or not out.is_dir():
            raise SystemExit("assemble_site: output exists and is not a directory")
        if any(out.iterdir()) and not (out / "versions.json").is_file():
            raise SystemExit("assemble_site: output is not empty and is not an earlier site; refusing to delete it")
        shutil.rmtree(out)
    shutil.copytree(src, out, symlinks=True, ignore=shutil.ignore_patterns(*DROP))
    codes = verify_sealed.all_codes()
    counts: dict[str, int] = {}
    claimed = {Path(sealer.opaque_path(p)).name for p in ROOT_ONLY}
    for v in registry:
        vid, source = v["id"], v.get("derivesFrom")
        target = out / vid / "d"
        transform = site_versions.transform_for(vid)
        written = 0
        for rel in verify_sealed.relative_logicals(v["docs"], codes):
            logical = f"{vid}/{rel}"
            if source is None:
                name = Path(sealer.opaque_path(logical)).name
                claimed.add(name)
                file = src / "d" / name
                if file.is_file():
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(file, target / name)
                    written += 1
                continue
            source_logical = f"{source}/{rel}"
            # Versions are processed in order, so a derived source is already assembled under out/<source>/d.
            got = read_sealed(out / source, source_logical, sealer)
            if got is None:
                if rel in ("ai/news", "ai/brief"):
                    log(f"{vid}: {rel} not available, skipped")
                continue
            doc, issued = got
            sealed = sealer.seal(logical, transform(logical, doc), issued=issued)
            target.mkdir(parents=True, exist_ok=True)
            (target / Path(sealer.opaque_path(logical)).name).write_text(
                json.dumps(sealed, separators=(",", ":")), encoding="utf-8")
            written += 1
        counts[vid] = written
        had = counts[source] > 0 if source else (src / "d").is_dir() and any((src / "d").iterdir())
        if had and written == 0 and v["docs"]:
            raise SystemExit(f"assemble_site: {vid} expects documents but none were written")
    root_d = src / "d"
    orphans = [f for f in root_d.iterdir() if f.is_file() and f.name not in claimed] if root_d.is_dir() else []
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (out / "versions.json").write_text(
        json.dumps(site_versions.registry_document(now_iso, registry), separators=(",", ":")), encoding="utf-8")
    (out / "_headers").write_text(site_versions.headers_text(registry), encoding="utf-8")
    return {"counts": counts, "orphans": len(orphans)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    check_paths(src, out)
    try:
        sealer = Sealer.from_env()
    except (EnvelopeError, ValueError, SystemExit):
        sealer = None
    if sealer is None:
        print("assemble_site: GHEYMAT_PAYLOAD_KEY / GHEYMAT_SIGNING_KEY missing or invalid", file=sys.stderr)
        return 2
    result = assemble(src, out, sealer)
    counts = result["counts"]
    print("assemble_site: " + ", ".join(f"{k} {n} files" for k, n in counts.items())
          + f"; legacy files left at root: {result['orphans']}")
    first = site_versions.VERSIONS[0]["id"]
    if not (out / first / "d" / Path(sealer.opaque_path(f"{first}/latest")).name).is_file():
        print(f"assemble_site: {first}/latest is missing", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
