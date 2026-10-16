import importlib.util
import pathlib

import pytest
import requests

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
    assert all(r["computed"] is False for r in snap["rates"])
    assert all(r["buyRaw"] is None and r["sellRaw"] is None for r in snap["rates"])



def test_refuses_thin_payload():
    snap = mod.build_snapshot({"usd1": "1", "usd2": "1"}, mod.load_instruments())
    assert len(snap["rates"]) < 29


def test_build_snapshot_never_produces_computed_rows():
    instruments = mod.load_instruments()
    computed_codes = {i["code"] for i in instruments if i.get("computed")}
    assert computed_codes == {"pln", "nzd", "krw", "mxn", "zar", "idr", "czk", "huf"}
    snap = mod.build_snapshot(RAW, instruments)
    assert {r["code"] for r in snap["rates"]}.isdisjoint(computed_codes)


def test_floor_check_count_is_unaffected_by_computed_instruments_being_in_the_table():
    """main()'s `len(snapshot["rates"]) < 29` floor-check must stay scoped to direct rows, whether or not
    the 8 computed instruments are present in instruments.json."""
    instruments = mod.load_instruments()
    direct_only = [i for i in instruments if not i.get("computed")]
    with_computed = mod.build_snapshot(RAW, instruments)["rates"]
    direct_count = mod.build_snapshot(RAW, direct_only)["rates"]
    assert len(with_computed) == len(direct_count)


def test_parse_converter_table_coerces_and_rejects_non_dict():
    assert mod.parse_converter_table({"EUR": 1, "PLN": "4.36856", "bad": "x", "USD": None}) == {
        "EUR": 1.0, "PLN": 4.36856}
    assert mod.parse_converter_table([1, 2, 3]) is None
    assert mod.parse_converter_table("nope") is None
    assert mod.parse_converter_table(None) is None


class _FakeResponse:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code = status
        self._body = body
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self._json_error:
            raise ValueError("bad json")
        return self._body


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.posts = []

    def post(self, url, headers=None, timeout=None):
        self.posts.append((url, headers, timeout))
        return self._response


def test_fetch_converter_sends_xhr_headers_with_no_token_and_no_content_type():
    session = _FakeSession(_FakeResponse(200, {"EUR": 1, "PLN": 4.36856}))
    table = mod.fetch_converter(session)
    assert table == {"EUR": 1.0, "PLN": 4.36856}
    url, headers, timeout = session.posts[0]
    assert url == f"{mod.BASE}/converter" and timeout == 20
    assert headers["x-requested-with"] == "XMLHttpRequest"
    assert "content-type" not in headers
    # _FakeSession.post(url, headers=None, timeout=None) has no `data` parameter at all - a call that
    # tried to send a form body (like fetch_raw's token POST) would TypeError before we ever get here.
    assert len(session.posts) == 1 and len(session.posts[0]) == 3


def test_fetch_converter_returns_none_and_logs_on_http_error_non_json_or_non_dict_body(capsys):
    assert mod.fetch_converter(_FakeSession(_FakeResponse(403))) is None
    assert mod.fetch_converter(_FakeSession(_FakeResponse(200, json_error=True))) is None
    assert mod.fetch_converter(_FakeSession(_FakeResponse(200, [1, 2, 3]))) is None
    err = capsys.readouterr().err
    assert err.count("converter:") == 3


COMPUTED_INSTRUMENTS = [i for i in mod.load_instruments() if i.get("computed")]


def test_compute_cross_rates_formula_and_per_key_skip():
    table = {"EUR": 1.0, "PLN": 4.36856, "HUF": 0.0, "ZAR": -1.0}  # NZD/KRW/MXN/IDR/CZK absent entirely
    rates = mod.compute_cross_rates(table, 294600, 294800, COMPUTED_INSTRUMENTS)
    by = {r["code"]: r for r in rates}
    assert set(by) == {"pln"}
    assert by["pln"]["computed"] is True and by["pln"]["price"] is None
    assert by["pln"]["buy"] == round(1 * 294600 * (1.0 / 4.36856))
    assert by["pln"]["sell"] == round(1 * 294800 * (1.0 / 4.36856))


def test_compute_cross_rates_carries_unrounded_buy_raw_sell_raw():
    # CONTRACT.md "Numeric accuracy": round once, at the point of display - buyRaw/sellRaw must be the
    # unrounded per-unit value behind buy/sell, not just a duplicate of the rounded int.
    table = {"EUR": 1.0, "PLN": 4.36856}
    rates = mod.compute_cross_rates(table, 294600, 294800, COMPUTED_INSTRUMENTS)
    pln = next(r for r in rates if r["code"] == "pln")
    k = 1.0 / 4.36856
    assert pln["buyRaw"] == pytest.approx(294600 * k)
    assert pln["sellRaw"] == pytest.approx(294800 * k)
    assert round(pln["buyRaw"]) == pln["buy"]
    assert round(pln["sellRaw"]) == pln["sell"]
    assert pln["buyRaw"] != pln["buy"]  # genuinely fractional, not coincidentally an integer


def test_compute_cross_rates_skips_non_finite_rate_without_crashing():
    # A bad /converter value (nan/inf, or a string like "1e999" that parse_converter_table happily
    # coerces to inf) must drop only that one row, never raise - round(nan)/round(inf) would otherwise
    # kill the whole publish run (the github actions step runs under set -euo pipefail).
    table = {"EUR": 1.0, "PLN": float("nan"), "HUF": float("inf")}
    rates = mod.compute_cross_rates(table, 294600, 294800, COMPUTED_INSTRUMENTS)
    assert rates == []


def test_compute_cross_rates_drops_everything_without_a_eur_quote_or_a_good_pivot():
    table = {"EUR": 1.0, "PLN": 4.36856}
    assert mod.compute_cross_rates(table, None, 294800, COMPUTED_INSTRUMENTS) == []
    assert mod.compute_cross_rates(table, 294600, None, COMPUTED_INSTRUMENTS) == []
    rebased = {"EUR": 0.9, "PLN": 4.36856}  # bonbast re-based the feed
    assert mod.compute_cross_rates(rebased, 294600, 294800, COMPUTED_INSTRUMENTS) == []


def test_fetch_computed_rates_skips_the_network_call_when_eur_quote_is_unusable():
    instruments = mod.load_instruments()
    calls = []

    def fake(session):
        calls.append(1)
        return {"EUR": 1.0, "PLN": 4.36856}

    no_eur = [{"code": "usd", "buy": 1, "sell": 2}]
    assert mod.fetch_computed_rates(None, no_eur, instruments, fetcher=fake) == [] and calls == []
    thin_eur = [{"code": "eur", "buy": None, "sell": None}]
    assert mod.fetch_computed_rates(None, thin_eur, instruments, fetcher=fake) == [] and calls == []


def test_fetch_computed_rates_end_to_end_with_an_injected_table():
    instruments = mod.load_instruments()
    direct = [{"code": "eur", "buy": 294600, "sell": 294800}]
    table = {"EUR": 1.0, "PLN": 4.36856}
    rates = mod.fetch_computed_rates(None, direct, instruments, fetcher=lambda session: table)
    assert [r["code"] for r in rates] == ["pln"]
    assert mod.fetch_computed_rates(None, direct, instruments, fetcher=lambda session: None) == []


def test_merge_rates_reorders_to_instrument_table_order_and_is_a_noop_when_empty():
    instruments = mod.load_instruments()
    direct = [{"code": "usd"}, {"code": "qar"}, {"code": "btc"}]
    computed = [{"code": "huf"}, {"code": "pln"}]
    merged = mod.merge_rates(direct, computed, instruments)
    assert [r["code"] for r in merged] == ["usd", "qar", "pln", "huf", "btc"]
    assert mod.merge_rates(direct, [], instruments) is direct


def test_intraday_skips_computed_rows(tmp_path):
    snap = {"fetchedAt": "2026-10-15T09:00:00Z", "rates": [
        {"code": "usd", "buy": 1, "sell": 2, "price": None, "computed": False},
        {"code": "pln", "buy": 3, "sell": 4, "price": None, "computed": True},
    ]}
    assert mod.append_intraday(tmp_path, snap) == 1
    assert (tmp_path / "v1" / "intraday" / "usd").exists()
    assert not (tmp_path / "v1" / "intraday" / "pln").exists()


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
