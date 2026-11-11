#!/usr/bin/env python3
"""Registry of the static site's API versions, as data, plus the files generated from it.

Each version is served under its own URL prefix (`/<id>/`). Adding a version is one entry in VERSIONS and,
only when its documents differ from the ones they derive from, one function in TRANSFORMS.

Entry fields
  id          URL prefix and logical-path prefix (`v1`, `v2`, ...)
  status      current | stable | deprecated | sunset
  deprecatedAt / sunsetAt   optional ISO dates; surfaced as response headers and in the registry document
  docs        document groups the version carries ("core", "ai"; see verify_sealed.relative_logicals)
  derivesFrom None: the documents are the publisher's own output, copied as they are.
              "<id>": every document is read back from that version's copy, passed through the version's
              transform and sealed again under this version's logical path.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Callable

SCHEMA = 1
STATUSES = ("current", "stable", "deprecated", "sunset")
ID_RE = re.compile(r"^v[1-9][0-9]{0,2}$")

VERSIONS: list[dict] = [
    {"id": "v1", "status": "stable", "docs": ["core", "ai"], "derivesFrom": None},
    {"id": "v2", "status": "current", "docs": ["ai"], "derivesFrom": "v1"},
]


def v2_transform(logical: str, doc):
    """Hook for v2 documents. Identity today: the wire shapes are unchanged."""
    return doc


# version id -> transform(logical, doc) -> doc. A version without an entry gets the identity.
TRANSFORMS: dict[str, Callable] = {"v2": v2_transform}


def transform_for(version_id: str) -> Callable:
    return TRANSFORMS.get(version_id, lambda logical, doc: doc)


def validate(registry: list[dict]) -> None:
    seen: set[str] = set()
    for v in registry:
        if not ID_RE.match(v["id"]) or v["id"] in seen:
            raise ValueError("bad or duplicate version id")
        seen.add(v["id"])
        if v["status"] not in STATUSES:
            raise ValueError("bad version status")
        source = v.get("derivesFrom")
        if source is not None and (source == v["id"] or source not in seen):
            raise ValueError("derivesFrom must name an earlier version")
        for key, needed in (("deprecatedAt", v["status"] in ("deprecated", "sunset")), ("sunsetAt", v["status"] == "sunset")):
            if v.get(key):
                datetime.fromisoformat(v[key])  # ValueError when not ISO
            elif needed:
                raise ValueError(f"{key} is required for status {v['status']}")


def latest_id(registry: list[dict]) -> str:
    current = [v["id"] for v in registry if v["status"] == "current"]
    if not current:
        raise ValueError("no current version")
    return current[-1]


def registry_document(now_iso: str, registry: list[dict] | None = None) -> dict:
    registry = VERSIONS if registry is None else registry
    validate(registry)
    versions = []
    for v in registry:
        entry = {"id": v["id"], "status": v["status"], "base": f"/{v['id']}/"}
        for key in ("deprecatedAt", "sunsetAt"):
            if v.get(key):
                entry[key] = v[key]
        versions.append(entry)
    return {"schema": SCHEMA, "generatedAt": now_iso, "latest": latest_id(registry), "versions": versions}


def _epoch(date: str) -> int:
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


def _http_date(date: str) -> str:
    return format_datetime(datetime.fromisoformat(date).replace(tzinfo=timezone.utc), usegmt=True)


def _block(path: str, lines: list[str]) -> str:
    return path + "\n" + "".join(f"  {line}\n" for line in lines)


def headers_text(registry: list[dict] | None = None) -> str:
    """The Cloudflare Pages `_headers` file for the site."""
    registry = VERSIONS if registry is None else registry
    validate(registry)
    doc_headers = ["Content-Type: application/json", "X-Robots-Tag: noindex, nofollow", "Access-Control-Allow-Origin: *"]
    blocks = [_block("/*", ["X-Content-Type-Options: nosniff", "Referrer-Policy: no-referrer"]),
              _block("/d/*", doc_headers)]
    for v in registry:
        blocks.append(_block(f"/{v['id']}/d/*", doc_headers))
        notices = []
        if v["status"] in ("deprecated", "sunset"):
            notices.append(f"Deprecation: @{_epoch(v['deprecatedAt'])}")
            if v.get("sunsetAt"):
                notices.append(f"Sunset: {_http_date(v['sunsetAt'])}")
        if notices:
            blocks.append(_block(f"/{v['id']}/*", notices))
    blocks.append(_block("/versions.json", ["Cache-Control: public, max-age=60", "Content-Type: application/json",
                                           "Access-Control-Allow-Origin: *"]))
    return "\n".join(blocks)
