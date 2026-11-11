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


def record_day(archive_root, now: datetime, items, store=None) -> int:
    store = store or _store()
    by_day: dict[str, list[dict]] = {}
    for item in items or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        published = _parse(item.get("publishedAt"))
        if published is None:
            continue
        by_day.setdefault(tehran_date(published), []).append(item)
    if not by_day:
        return 0
    existing = latest_by_date(store.load(archive_root, NAME))
    written = 0
    for day in sorted(by_day):
        prev = existing.get(day) or {}
        seen = set(prev.get("ids") or [])
        fresh = [i for i in by_day[day] if i["id"] not in seen]
        if not fresh:
            continue
        counts = {"up": int(prev.get("up", 0)), "down": int(prev.get("down", 0)), "none": int(prev.get("none", 0))}
        sources = {k: int(v) for k, v in (prev.get("sources") or {}).items()}
        ids = list(prev.get("ids") or [])
        for item in fresh:
            effect = item.get("effect")
            counts["up" if effect == "usd_up" else "down" if effect == "usd_down" else "none"] += 1
            name = item.get("source")
            if isinstance(name, str) and name:
                sources[name] = sources.get(name, 0) + 1
            ids.append(item["id"])
        store.append(archive_root, NAME, {"date": day, **counts, "total": sum(counts.values()),
                                          "sources": sources, "ids": ids})
        written += 1
    return written


def _as_date(basis_date) -> date | None:
    if isinstance(basis_date, datetime):
        return basis_date.date()
    if isinstance(basis_date, date):
        return basis_date
    try:
        return date.fromisoformat(str(basis_date))
    except ValueError:
        return None


def news_tilt(records, basis_date) -> float:
    basis = _as_date(basis_date)
    if basis is None:
        return 0.0
    floor = basis - timedelta(days=TILT_DAYS)
    up = down = 0
    for day, rec in latest_by_date(records).items():
        try:
            d = date.fromisoformat(day)
            if not floor <= d < basis:
                continue
            up += max(0, int(rec.get("up", 0)))
            down += max(0, int(rec.get("down", 0)))
        except (ValueError, TypeError):
            continue
    if up + down < MIN_TILT_ITEMS:
        return 0.0
    return max(-1.0, min(1.0, (up - down) / (up + down)))
