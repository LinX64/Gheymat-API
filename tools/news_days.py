from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

LOGICAL = "v1/ai/news-archive"
NAME = "news_days"
RETENTION_DAYS = 400
MAX_PER_DAY = 40
MAX_SEALED_BYTES = 3_000_000
SEAL_OVERHEAD = 1024
FIELDS = ("id", "url", "source", "publishedAt", "title", "lang", "en", "fa", "effect", "tagger")
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_key(published) -> str | None:
    if not isinstance(published, str):
        return None
    try:
        moment = datetime.fromisoformat(published.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(TEHRAN).date().isoformat()


def clean_item(raw) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        return None
    if day_key(raw.get("publishedAt")) is None:
        return None
    return {k: raw.get(k) for k in FIELDS}


def sealed_size(doc: dict) -> int:
    plain = len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return plain * 4 // 3 + SEAL_OVERHEAD


def merge(days: dict[str, list[dict]], items) -> dict[str, list[dict]]:
    seen = {i["id"] for rows in days.values() for i in rows}
    out = {d: list(rows) for d, rows in days.items()}
    for raw in items or []:
        item = clean_item(raw)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        out.setdefault(day_key(item["publishedAt"]), []).append(item)
    return out


def build(days: dict[str, list[dict]], now: datetime, generated_at: str) -> dict:
    floor = (now.astimezone(TEHRAN).date() - timedelta(days=RETENTION_DAYS)).isoformat()
    ordered = []
    for day in sorted(days, reverse=True):
        if day < floor:
            continue
        rows = sorted(days[day], key=lambda i: (i["publishedAt"], i["id"]), reverse=True)[:MAX_PER_DAY]
        if rows:
            ordered.append({"day": day, "items": rows})
    doc = {"generatedAt": generated_at, "retentionDays": RETENTION_DAYS, "days": ordered}
    while len(doc["days"]) > 1 and sealed_size(doc) > MAX_SEALED_BYTES:
        doc["days"].pop()
    return doc


def days_of(doc) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    rows = doc.get("days") if isinstance(doc, dict) else None
    for entry in rows if isinstance(rows, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("day"), str) and isinstance(entry.get("items"), list):
            items = [i for i in map(clean_item, entry["items"]) if i is not None]
            if items:
                out[entry["day"]] = items
    return out


def update(write_doc, load_doc, state_dir, news_doc, now: datetime, log=print, store=None) -> dict | None:
    try:
        if store is None:
            import archive_store as store
        previous = load_doc(LOGICAL)
        stored = {r["date"]: r["items"] for r in store.load(state_dir, NAME, log)
                  if isinstance(r.get("items"), list)} if state_dir else {}
        base = stored or days_of(previous)
        items = news_doc.get("items") if isinstance(news_doc, dict) else None
        merged = merge(base, items)
        stamp = _iso(now)
        doc = build(merged, now, stamp)
        if isinstance(previous, dict) and previous.get("days") == doc["days"] and previous.get("generatedAt"):
            doc["generatedAt"] = previous["generatedAt"]
        write_doc(LOGICAL, doc)
        if state_dir:
            records = [{"date": d["day"], "items": d["items"]} for d in sorted(doc["days"], key=lambda d: d["day"])]
            if records != [{"date": k, "items": v} for k, v in sorted(stored.items())]:
                store.write(state_dir, NAME, records, 0, log)
        return doc
    except Exception as e:
        log(f"ai: news archive skipped: {type(e).__name__}")
        return None
