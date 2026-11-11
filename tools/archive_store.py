from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ARCHIVE_DIR = "archive"


def _path(root, name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("bad archive name")
    return Path(root) / ARCHIVE_DIR / f"{name}.json"


def load(root, name: str, log=print) -> list[dict]:
    path = _path(root, name)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log(f"archive {name}: unreadable, treated as empty")
        return []
    if not isinstance(data, list):
        log(f"archive {name}: not a list, treated as empty")
        return []
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("date"), str)]


def _write_atomic(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, separators=(",", ":"), sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append(root, name: str, record: dict, log=print) -> bool:
    if not isinstance(record, dict) or not isinstance(record.get("date"), str):
        raise ValueError("record needs a string date")
    path = _path(root, name)
    existing = load(root, name, log)
    if path.is_file() and not existing:
        raw = path.read_bytes()
        if raw.strip() not in (b"", b"[]"):
            backup = path.with_name(path.name + ".corrupt")
            try:
                backup.write_bytes(raw)
            except OSError:
                pass
            log(f"archive {name}: unreadable file kept as backup, starting empty")
    merged = {r["date"]: r for r in existing}
    merged[record["date"]] = record
    out = [merged[d] for d in sorted(merged)]
    return write(root, name, out, len(existing), log)


def write(root, name: str, records: list[dict], loaded: int, log=print) -> bool:
    if len(records) < loaded:
        log(f"archive {name}: refusing to shrink")
        return False
    _write_atomic(_path(root, name), records)
    return True
