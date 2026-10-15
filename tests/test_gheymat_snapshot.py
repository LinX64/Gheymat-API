import importlib.util
import pathlib

SPEC = importlib.util.spec_from_file_location(
    "gheymat_snapshot", pathlib.Path(__file__).resolve().parents[1] / "tools" / "gheymat_snapshot.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

RAW = {
    "usd1": "265200", "usd2": "265000", "eur1": "294800", "eur2": "294600", "jpy1": "17750", "jpy2": "17700",
    "emami1": "268000000", "emami12": "265000000", "azadi1": "258000000", "azadi12": "253000000",
    "gol18": "26136940", "mithqal": "113220000", "ounce": "4094.2", "bitcoin": "81476.39",
    "last_modified": "October 14, 2026 19:06", "created": "x", "hour": "22", "minute": "36",
}


def test_build_snapshot_maps_currency_coin_gold_and_crypto():
    snap = mod.build_snapshot(RAW, mod.load_instruments())
    by = {r["code"]: r for r in snap["rates"]}
    assert by["usd"]["buy"] == 265000 and by["usd"]["sell"] == 265200
    assert by["jpy"]["unit"] == 10
    assert by["emami"]["buy"] == 265000000 and by["emami"]["sell"] == 268000000
    assert by["gram"]["price"] == 26136940 and by["gram"]["buy"] is None
    assert by["ounce"]["quote"] == "usd" and by["btc"]["price"] == 81476.39
    assert snap["sourceModified"] == "October 14, 2026 19:06"
    assert "gbp" not in by



def test_refuses_thin_payload():
    snap = mod.build_snapshot({"usd1": "1", "usd2": "1"}, mod.load_instruments())
    assert len(snap["rates"]) < 29


def test_intraday_appends_and_trims(tmp_path):
    snap = mod.build_snapshot(RAW, mod.load_instruments())
    old = {"code": "usd", "days": 7, "points": [
        {"ts": "2026-09-01T00:00:00Z", "buy": 1, "sell": 2, "price": None},
        {"ts": "2026-10-14T20:00:00Z", "buy": 264000, "sell": 264200, "price": None},
    ]}
    (tmp_path / "v1" / "intraday").mkdir(parents=True)
    (tmp_path / "v1" / "intraday" / "usd").write_text(__import__("json").dumps(old), encoding="utf-8")
    assert mod.append_intraday(tmp_path, snap) == len(snap["rates"])
    usd = __import__("json").loads((tmp_path / "v1" / "intraday" / "usd").read_text(encoding="utf-8"))
    assert [p["ts"] for p in usd["points"]][0] == "2026-10-14T20:00:00Z"
    assert usd["points"][-1]["sell"] == 265200
    assert mod.append_intraday(tmp_path, snap) == 0


FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "archive-2020-03-20.html"


def test_parse_archive_fixture():
    shown, values = mod.parse_archive(FIXTURE.read_text(encoding="utf-8"))
    assert shown == "2020-03-20"
    assert values["usd"] == (16000, 16100)
    assert values["emami"] == (6000000, 6200000)
    assert "half" in values and "quarter" in values and "gerami" in values
    assert len(values) >= 30


def test_fill_days_stops_on_identical_payload_run():
    daily = {"start": "2012-10-09", "codes": {}}
    same = {"usd": (1, 2), **{f"c{i}": (i, i + 1) for i in range(25)}}
    dates = [f"2020-01-{d:02d}" for d in range(10, 0, -1)]
    calls = []

    def fake(date):
        calls.append(date)
        return date, same

    got = mod.fill_days(None, daily, dates, pace=0, fetcher=fake)
    assert got == 0 and len(calls) == mod.BLOCK_RUN + 1
    assert daily["codes"] == {}


def test_backfill_dates_walk_back_from_earliest_known():
    daily = {"start": "2012-10-09", "codes": {"usd": {"2020-03-20": [1, 2], "2020-03-19": [1, 2]}}}
    assert mod.backfill_dates(daily, 3) == ["2020-03-18", "2020-03-17", "2020-03-16"]
    daily["start"] = "2020-03-18"
    assert mod.backfill_dates(daily, 5) == ["2020-03-18"]


def test_history_files_from_daily(tmp_path):
    daily = {"start": "2012-10-09", "codes": {"usd": {"2020-03-20": [16000, 16100], "2020-03-19": [15900, 16000]}}}
    assert mod.write_history_files(tmp_path, daily) == 1
    h = __import__("json").loads((tmp_path / "v1" / "history" / "usd").read_text(encoding="utf-8"))
    assert [p["date"] for p in h["points"]] == ["2020-03-19", "2020-03-20"] and h["points"][-1]["price"] == 16100.0


def test_seal_roundtrip_and_tamper():
    import base64, os, pytest
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
    import gheymat_seal as gs
    priv = Ed25519PrivateKey.generate()
    sealer = gs.Sealer(os.urandom(32), priv)
    env = sealer.seal("v1/latest", {"seq": 1, "rates": []}, issued=1000)
    assert env["v"] == 2 and env["kid"] == 1 and "path" not in env
    assert gs.open_envelope(env, sealer.payload_key, priv.public_key(), "v1/latest", max_age=None) == {"seq": 1, "rates": []}
    with pytest.raises(gs.EnvelopeError):
        gs.open_envelope(env, sealer.payload_key, priv.public_key(), "v1/instruments", max_age=None)
    bad = dict(env, ciphertext=base64.b64encode(b"x" + base64.b64decode(env["ciphertext"])[1:]).decode())
    with pytest.raises(gs.EnvelopeError):
        gs.open_envelope(bad, sealer.payload_key, priv.public_key(), "v1/latest", max_age=None)
    with pytest.raises(gs.EnvelopeError):
        gs.open_envelope(env, sealer.payload_key, priv.public_key(), "v1/latest", max_age=10)
    p = sealer.opaque_path("v1/latest")
    assert p.startswith("d/") and len(p) == 34 and p == sealer.opaque_path("v1/latest") and p != sealer.opaque_path("v1/health")


def test_write_seals_at_the_opaque_path_and_the_state_reads_back(tmp_path):
    import os
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import gheymat_seal as gs
    sealer = gs.Sealer(os.urandom(32), Ed25519PrivateKey.generate())
    mod._DIST_ROOT, mod.SEALER, mod.PLAIN_ALSO = tmp_path, sealer, False
    try:
        daily = {"start": "2012-10-09", "codes": {"usd": {"2020-03-20": [16000, 16100]}}}
        mod.save_daily(tmp_path, daily)
        assert not (tmp_path / "v1" / "daily.json").exists()
        assert (tmp_path / sealer.opaque_path("v1/daily.json")).exists()
        assert gs.load_published(tmp_path, "v1/daily.json", sealer) == daily
        assert mod.load_daily(tmp_path) == daily
        snap = mod.build_snapshot(RAW, mod.load_instruments())
        assert mod.append_intraday(tmp_path, snap) == len(snap["rates"])
        assert not (tmp_path / "v1" / "intraday" / "usd").exists()
        assert mod.append_intraday(tmp_path, snap) == 0
        later = dict(snap, fetchedAt="2026-10-15T09:00:00Z")
        assert mod.append_intraday(tmp_path, later) == len(snap["rates"])
        usd = gs.load_published(tmp_path, "v1/intraday/usd", sealer)
        assert [p["ts"] for p in usd["points"]] == [snap["fetchedAt"], "2026-10-15T09:00:00Z"]
        mod.SEALER = gs.Sealer(os.urandom(32), Ed25519PrivateKey.generate())
        assert mod.load_daily(tmp_path) == {"start": mod.ARCHIVE_START, "codes": {}}
    finally:
        mod._DIST_ROOT, mod.SEALER, mod.PLAIN_ALSO = None, None, True


def test_stale_plain_state_is_removed_once_plain_files_are_off(tmp_path):
    import json, os
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import gheymat_seal as gs
    sealer = gs.Sealer(os.urandom(32), Ed25519PrivateKey.generate())
    stale = {"start": "2012-10-09", "codes": {"usd": {"2020-03-20": [1, 2]}}}
    fresh = {"start": "2012-10-09", "codes": {"usd": {"2020-03-20": [1, 2], "2020-03-21": [3, 4]}}}
    plain = tmp_path / "v1" / "daily.json"
    plain.parent.mkdir(parents=True)
    plain.write_text(json.dumps(stale), encoding="utf-8")
    mod._DIST_ROOT, mod.SEALER, mod.PLAIN_ALSO = tmp_path, sealer, False
    try:
        assert mod.load_daily(tmp_path) == stale
        mod.save_daily(tmp_path, fresh)
        assert not plain.exists()
        assert mod.load_daily(tmp_path) == fresh
        mod.save_daily(tmp_path, stale)
        assert mod.load_daily(tmp_path) == stale and not plain.exists()
    finally:
        mod._DIST_ROOT, mod.SEALER, mod.PLAIN_ALSO = None, None, True


def test_archive_guard_refuses_a_shrunken_state(tmp_path):
    import os
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import gheymat_seal as gs
    sealer = gs.Sealer(os.urandom(32), Ed25519PrivateKey.generate())
    mod._DIST_ROOT, mod.SEALER, mod.PLAIN_ALSO = tmp_path, sealer, False
    try:
        small = {"start": "2012-10-09", "codes": {"usd": {f"2020-01-{d:02d}": [1, 2] for d in range(1, 10)}}}
        assert mod.archive_shrank(tmp_path, small) is None
        mod.write(tmp_path / "health", {"ok": True, "archiveDays": 999})
        assert mod.archive_shrank(tmp_path, small) is None
        mod.write(tmp_path / "health", {"ok": True, "archiveDays": 4000})
        assert mod.archive_shrank(tmp_path, small) == (4000, 9)
        assert mod.archive_shrank(tmp_path, {"start": "2012-10-09", "codes": {}}) == (4000, 0)
        big = {"start": "2012-10-09", "codes": {"usd": {f"d{i}": [1, 2] for i in range(2000)}}}
        assert mod.archive_shrank(tmp_path, big) is None
        mod.write(tmp_path / "health", {"ok": True, "archiveDays": "4000"})
        assert mod.archive_shrank(tmp_path, small) is None
    finally:
        mod._DIST_ROOT, mod.SEALER, mod.PLAIN_ALSO = None, None, True
