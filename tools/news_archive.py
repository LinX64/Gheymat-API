from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

NAME = "news_tilt"
TEHRAN = timezone(timedelta(hours=3, minutes=30))
TILT_DAYS = 7
MIN_TILT_ITEMS = 3


def _store():
    import archive_store
    return archive_store


def _parse(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def tehran_date(published: datetime) -> str:
    return published.astimezone(TEHRAN).date().isoformat()


def latest_by_date(records) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in records if isinstance(records, list) else []:
        if isinstance(rec, dict) and isinstance(rec.get("date"), str):
            out[rec["date"]] = rec
    return out


TOPICS = ("fx", "gold", "oil", "sanctions", "politics")
DEDUPE_DAYS = 3


def _int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _ids(rec) -> list[str]:
    value = rec.get("ids") if isinstance(rec, dict) else None
    return [i for i in value if isinstance(i, str)] if isinstance(value, list) else []


def _cfg(rec) -> str:
    value = rec.get("cfg") if isinstance(rec, dict) else None
    return value if isinstance(value, str) and value else ""


def _strip(store, archive_root, loaded, record=None) -> None:
    clean = [{k: v for k, v in r.items() if k != "sources"} for r in loaded]
    if record is not None:
        positions = [i for i, r in enumerate(clean) if r.get("date") == record["date"]]
        if positions:
            clean[positions[-1]] = record
        else:
            clean.append(record)
            clean.sort(key=lambda r: r["date"])
    try:
        store.write(archive_root, NAME, clean, len(loaded))
    except (OSError, ValueError, AttributeError, TypeError):
        return


def record_day(archive_root, now: datetime, items, store=None, config_version=None) -> int:
    store = store or _store()
    if not isinstance(now, datetime) or now.tzinfo is None:
        return 0
    day = tehran_date(now)
    today = date.fromisoformat(day)
    loaded = [r for r in store.load(archive_root, NAME) if isinstance(r, dict)]
    existing = latest_by_date(loaded)
    dirty = any("sources" in r for r in loaded)
    prev = existing.get(day) or {}
    seen: set[str] = set(_ids(prev))
    for back in range(1, DEDUPE_DAYS + 1):
        old = existing.get((today - timedelta(days=back)).isoformat()) or {}
        seen.update(_ids(old))
    fresh: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if _parse(item.get("publishedAt")) is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        fresh.append(item)
    if not fresh:
        if dirty:
            _strip(store, archive_root, loaded)
        return 0
    counts = {k: _int(prev.get(k)) for k in ("up", "down", "none", "shadowUp", "shadowDown", "shadowNone",
                                             "shadowUnknown")}
    topics = {t: _int((prev.get("topics") or {}).get(t) if isinstance(prev.get("topics"), dict) else 0)
              for t in TOPICS}
    ids = _ids(prev)
    sources = set()
    for item in fresh:
        effect = item.get("effect")
        counts["up" if effect == "usd_up" else "down" if effect == "usd_down" else "none"] += 1
        shadow = item.get("shadowEffect")
        counts["shadowUp" if shadow == "usd_up" else "shadowDown" if shadow == "usd_down"
               else "shadowUnknown" if shadow == "unknown" else "shadowNone"] += 1
        for topic in item.get("topics") or []:
            if topic in topics:
                topics[topic] += 1
        name = item.get("source")
        if isinstance(name, str) and name:
            sources.add(name)
        ids.append(item["id"])
    cfg = _cfg(prev) or (config_version if isinstance(config_version, str) else "")
    record = {
        "date": day, "up": counts["up"], "down": counts["down"], "none": counts["none"],
        "total": counts["up"] + counts["down"] + counts["none"],
        "shadowUp": counts["shadowUp"], "shadowDown": counts["shadowDown"],
        "shadowNone": counts["shadowNone"], "shadowUnknown": counts["shadowUnknown"],
        "cfg": cfg,
        "recordedAt": now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "topics": topics,
        "sourceCount": max(_int(prev.get("sourceCount")), len(sources)),
        "ids": ids,
    }
    if dirty:
        _strip(store, archive_root, loaded, record)
    else:
        store.append(archive_root, NAME, record)
    return 1


def _as_date(basis_date) -> date | None:
    if isinstance(basis_date, datetime):
        return basis_date.date()
    if isinstance(basis_date, date):
        return basis_date
    try:
        return date.fromisoformat(str(basis_date))
    except ValueError:
        return None


def _dated(records) -> list[tuple[date, dict]]:
    out = []
    for day, rec in latest_by_date(records).items():
        try:
            out.append((date.fromisoformat(day), rec))
        except ValueError:
            continue
    return sorted(out, key=lambda pair: pair[0])


def news_tilt(records, basis_date) -> float:
    basis = _as_date(basis_date)
    if basis is None:
        return 0.0
    floor = basis - timedelta(days=TILT_DAYS)
    window = [(d, r) for d, r in _dated(records) if floor <= d < basis]
    latest = ""
    for _, rec in window:
        if _cfg(rec):
            latest = _cfg(rec)
    up = down = 0
    for _, rec in window:
        try:
            cfg = _cfg(rec)
            if cfg:
                if cfg != latest:
                    continue
                up += _int(rec.get("shadowUp"))
                down += _int(rec.get("shadowDown"))
            else:
                up += _int(rec.get("up"))
                down += _int(rec.get("down"))
        except (AttributeError, TypeError, ValueError):
            continue
    if up + down < MIN_TILT_ITEMS:
        return 0.0
    return max(-1.0, min(1.0, (up - down) / (up + down)))


def _marked_run(records) -> list[date]:
    dated = _dated(records)
    latest = ""
    for _, rec in dated:
        if _cfg(rec):
            latest = _cfg(rec)
    run: list[date] = []
    if not latest:
        return run
    for d, rec in reversed(dated):
        if _cfg(rec) != latest:
            break
        run.append(d)
    run.reverse()
    return run


def first_marked_day(records) -> str | None:
    run = _marked_run(records)
    if not run:
        return None
    return (run[0] + timedelta(days=1)).isoformat()


def marked_days(records) -> int:
    return max(0, len(_marked_run(records)) - 1)
