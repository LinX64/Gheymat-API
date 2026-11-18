import json
import pathlib
import sys
from datetime import datetime, timezone

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import archive_store
import gheymat_seal as gs
import news_days as nd

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def item(i, at, **kw):
    return {"id": i, "url": f"https://x/{i}", "source": "S", "publishedAt": at, "title": "t", "lang": "fa",
            "en": "e", "fa": "f", "effect": kw.get("effect"), "tagger": kw.get("tagger"), "extra": "drop"}


class Disk:
    def __init__(self):
        self.docs = {}

    def write(self, logical, obj):
        self.docs[logical] = json.loads(json.dumps(obj))

    def load(self, logical):
        return self.docs.get(logical)


def test_dedupe_by_id_and_fields_kept():
    days = nd.merge({}, [item("a", "2026-11-18T10:00:00Z"), item("a", "2026-11-18T10:00:00Z"), item("b", "bad")])
    assert [i["id"] for i in days["2026-11-18"]] == ["a"]
    assert "extra" not in days["2026-11-18"][0] and days["2026-11-18"][0]["effect"] is None
    again = nd.merge(days, [item("a", "2026-11-18T10:00:00Z", effect="usd_up")])
    assert again["2026-11-18"][0]["effect"] is None


def test_tehran_day_and_ordering():
    days = nd.merge({}, [item("a", "2026-11-17T20:30:00Z"), item("b", "2026-11-17T10:00:00Z"),
                         item("c", "2026-11-18T09:00:00Z")])
    assert sorted(days) == ["2026-11-17", "2026-11-18"]
    doc = nd.build(days, NOW, "2026-11-18T12:00:00Z")
    assert [d["day"] for d in doc["days"]] == ["2026-11-18", "2026-11-17"]
    assert [i["id"] for i in doc["days"][0]["items"]] == ["c", "a"]
    assert [i["id"] for i in doc["days"][1]["items"]] == ["b"]
    assert doc["retentionDays"] == 400


def test_retention_and_per_day_cap():
    old = item("old", "2025-09-01T10:00:00Z")
    rows = [item(f"n{n:02d}", f"2026-11-18T{n % 20:02d}:{n // 20:02d}:00Z") for n in range(50)]
    doc = nd.build(nd.merge({}, [old] + rows), NOW, "g")
    assert [d["day"] for d in doc["days"]] == ["2026-11-18"]
    assert len(doc["days"][0]["items"]) == nd.MAX_PER_DAY


def test_size_bound_drops_oldest_days(monkeypatch):
    monkeypatch.setattr(nd, "MAX_SEALED_BYTES", 2500)
    rows = [item(f"i{n}", f"2026-11-{10 + n:02d}T10:00:00Z") for n in range(8)]
    doc = nd.build(nd.merge({}, rows), NOW, "g")
    assert 1 <= len(doc["days"]) < 8
    assert doc["days"][0]["day"] == "2026-11-17"
    assert nd.sealed_size(doc) <= 2500


def test_update_accumulates_and_keeps_generated_at(tmp_path):
    disk = Disk()
    news = {"items": [item("a", "2026-11-18T10:00:00Z")]}
    first = nd.update(disk.write, disk.load, str(tmp_path), news, NOW, log=lambda *_: None)
    assert first["generatedAt"] == "2026-11-18T12:00:00Z"
    later = datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc)
    same = nd.update(disk.write, disk.load, str(tmp_path), news, later, log=lambda *_: None)
    assert same["generatedAt"] == "2026-11-18T12:00:00Z"
    news2 = {"items": [item("b", "2026-11-19T10:00:00Z")]}
    grown = nd.update(disk.write, disk.load, str(tmp_path), news2, later, log=lambda *_: None)
    assert grown["generatedAt"] == "2026-11-18T13:00:00Z"
    assert [d["day"] for d in grown["days"]] == ["2026-11-19", "2026-11-18"]
    assert len(archive_store.load(str(tmp_path), nd.NAME)) == 2


def test_update_seeds_from_published_when_state_missing(tmp_path):
    disk = Disk()
    nd.update(disk.write, disk.load, None, {"items": [item("a", "2026-11-18T10:00:00Z")]}, NOW, log=lambda *_: None)
    out = nd.update(disk.write, disk.load, None, {"items": [item("b", "2026-11-18T11:00:00Z")]}, NOW,
                    log=lambda *_: None)
    assert [i["id"] for i in out["days"][0]["items"]] == ["b", "a"]


def test_update_never_raises():
    def boom(*_):
        raise OSError("x")
    assert nd.update(boom, lambda _l: None, None, {"items": []}, NOW, log=lambda *_: None) is None


def test_sealing_round_trip_and_registration():
    import verify_sealed as vs
    assert "ai/news-archive" in vs.AI_DOCS
    assert "ai/news-archive" in vs.relative_logicals(["ai"], {"usd"})
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    master = bytes(range(32))
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(100, 132)))
    sealer = gs.Sealer(master, key)
    doc = nd.build(nd.merge({}, [item("a", "2026-11-18T10:00:00Z")]), NOW, "2026-11-18T12:00:00Z")
    env = sealer.seal(nd.LOGICAL, doc)
    assert gs.open_envelope(env, master, key.public_key(), nd.LOGICAL, max_age=None) == doc


def test_real_seal_stays_under_envelope_cap():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sealer = gs.Sealer(bytes(range(32)), Ed25519PrivateKey.from_private_bytes(bytes(range(100, 132))))
    rows = []
    for n in range(3000):
        r = item(f"i{n}", f"2026-{1 + n % 12:02d}-{1 + n % 28:02d}T{n % 24:02d}:{n % 60:02d}:00Z")
        r["en"] = r["fa"] = "x" * 1200
        rows.append(r)
    doc = nd.build(nd.merge({}, rows), datetime(2026, 12, 31, tzinfo=timezone.utc), "g")
    assert nd.MAX_SEALED_BYTES < gs.MAX_ENVELOPE_BYTES
    assert len(json.dumps(sealer.seal(nd.LOGICAL, doc))) <= gs.MAX_ENVELOPE_BYTES


def test_clean_item_rejects_malformed_fields():
    good = item("a", "2026-11-18T10:00:00Z")
    assert nd.clean_item(good) is not None
    assert nd.clean_item({**good, "url": None}) is None
    assert nd.clean_item({**good, "fa": 3}) is None
    assert nd.clean_item({**good, "effect": "sideways"}) is None
    assert nd.clean_item({**good, "effect": "usd_up"})["effect"] == "usd_up"


def test_update_unions_state_and_published(tmp_path):
    disk = Disk()
    nd.update(disk.write, disk.load, None, {"items": [item("a", "2026-11-17T10:00:00Z")]}, NOW, log=lambda *_: None)
    archive_store.write(str(tmp_path), nd.NAME, [{"date": "2026-11-18", "items": [item("b", "2026-11-18T10:00:00Z")]}], 0)
    out = nd.update(disk.write, disk.load, str(tmp_path), {"items": []}, NOW, log=lambda *_: None)
    assert {i["id"] for d in out["days"] for i in d["items"]} == {"a", "b"}
