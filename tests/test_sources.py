"""Multi-source publishing (CONTRACT.md "Static publisher sources"): hansha first, bonbast fills and takes over.
No network: hansha rows are a trimmed copy of a live /latest response (2026-11-07), timestamps made relative."""
import importlib.util
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import requests

SPEC = importlib.util.spec_from_file_location(
    "gheymat_snapshot_sources", pathlib.Path(__file__).resolve().parents[1] / "tools" / "gheymat_snapshot.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

INSTRUMENTS = mod.load_instruments()
HANSHA_ONLY = {"eth", "xrp", "bch", "ltc", "bnb", "usdt"}


def iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def hansha_rows(minutes_ago: float = 2) -> list[dict]:
    ts = iso(minutes_ago)
    return [
        {"ab": "usd", "av": "🇺🇸", "en": "US Dollar", "fa": "دلار آمریکا", "ty": "cu",
         "ps": [{"bp": 266400, "sp": 266600, "ts": ts}, {"bp": 266800, "sp": 267000, "ts": iso(60)}]},
        {"ab": "eur", "av": "🇪🇺", "en": "Euro", "fa": "یورو", "ty": "cu",
         "ps": [{"bp": 297100, "sp": 297300, "ts": ts}]},
        {"ab": "gram", "av": "🔸", "en": "Gram", "fa": "گرم", "ty": "go", "ps": [{"sp": 25709865, "ts": ts}]},
        {"ab": "emami", "av": "🌖", "en": "Emami", "fa": "امامی", "ty": "co",
         "ps": [{"bp": 255500000, "sp": 260500000, "ts": ts}]},
        {"ab": "btc", "av": "💰", "en": "Bitcoin", "fa": "بیتکوین", "ty": "cc", "ps": [{"sp": 20352630000, "ts": ts}]},
        {"ab": "eth", "av": "🔊", "en": "Ethereum", "fa": "اتریوم", "ty": "cc", "ps": [{"sp": 600379000, "ts": ts}]},
        {"ab": "usdt", "av": "🪙", "en": "Tether USDT", "fa": "تتر", "ty": "cc", "ps": [{"sp": 267700, "ts": ts}]},
        {"ab": "zzz", "av": "?", "en": "Unknown", "fa": "?", "ty": "cu", "ps": [{"bp": 1, "sp": 2, "ts": ts}]},
        "not a row",
    ]


def bonbast_snapshot() -> dict:
    raw = {"usd1": "265200", "usd2": "265000", "eur1": "294800", "eur2": "294600", "ounce": "4094.2",
           "bitcoin": "81476.39", "gol18": "26136940", "last_modified": "November 7, 2026 15:40"}
    return mod.build_snapshot(raw, INSTRUMENTS)


def test_instrument_table_carries_the_six_hansha_only_crypto_rows():
    rows = {i["code"]: i for i in INSTRUMENTS}
    assert len(INSTRUMENTS) == 51
    for code in HANSHA_ONLY:
        r = rows[code]
        assert r["bonbast_key"] is None and r["kind"] == "crypto" and r["quote"] == "toman" and r["unit"] == 1
        assert r["flag"] and r["en"] and r["fa"]
    assert rows["btc"]["quote"] == "usd" and rows["btc"]["bonbast_key"] == "bitcoin"
    hansha_av = {"eth": "🔊", "ltc": "⚖️", "bnb": "🏦"}
    assert all(rows[c]["flag"] != av for c, av in hansha_av.items())


def test_bonbast_build_skips_hansha_only_instruments():
    codes = {r["code"] for r in bonbast_snapshot()["rates"]}
    assert codes.isdisjoint(HANSHA_ONLY) and {"usd", "ounce", "btc"} <= codes


def test_hansha_snapshot_maps_rows_with_our_names_and_skips_usd_quoted_btc():
    snap = mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)
    by = {r["code"]: r for r in snap["rates"]}
    assert snap["source"] == "hansha"
    assert by["usd"]["buy"] == 266400 and by["usd"]["sell"] == 266600 and by["usd"]["price"] is None
    assert by["gram"]["price"] == 25709865.0 and by["gram"]["buy"] is None
    assert by["emami"]["buy"] == 255500000 and by["emami"]["sell"] == 260500000
    assert by["eth"]["price"] == 600379000.0 and by["eth"]["flag"] == "💎"
    assert by["usdt"]["en"] == "Tether"  # our table's name, not hansha's "Tether USDT"
    assert "btc" not in by and "ounce" not in by and "zzz" not in by
    assert [r["code"] for r in snap["rates"]] == [c for c in (i["code"] for i in INSTRUMENTS) if c in by]
    assert snap["fetchedAt"] == snap["sourceModified"]


def test_hansha_row_far_behind_the_feed_is_dropped_so_it_cannot_age_the_snapshot():
    rows = hansha_rows(minutes_ago=1)
    rows[1]["ps"][0]["ts"] = iso(90)  # eur frozen 90 min behind the rest
    snap = mod.build_hansha_snapshot(rows, INSTRUMENTS)
    codes = {r["code"] for r in snap["rates"]}
    assert "eur" not in codes and "usd" in codes
    assert mod.age_seconds(snap["fetchedAt"]) < 5 * 60


def test_hansha_point_without_a_usable_timestamp_or_value_is_skipped():
    rows = hansha_rows()
    rows[0]["ps"][0]["ts"] = "yesterday"
    rows[2]["ps"][0]["sp"] = "0"
    rows[3]["ps"] = []
    by = {r["code"] for r in mod.build_hansha_snapshot(rows, INSTRUMENTS)["rates"]}
    assert not {"usd", "gram", "emami"} & by and "eur" in by


def test_normalize_ts_accepts_iso_variants_and_rejects_garbage_and_the_future():
    assert mod.normalize_ts("2026-11-07T12:11:07Z") == "2026-11-07T12:11:07Z"
    assert mod.normalize_ts("2026-11-07T12:11:07.912Z") == "2026-11-07T12:11:07Z"
    assert mod.normalize_ts("2026-11-07T15:41:07+03:30") == "2026-11-07T12:11:07Z"
    assert mod.normalize_ts("2026-11-07T12:11:07") == "2026-11-07T12:11:07Z"
    for bad in (None, "", "now", 1730000000, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()):
        assert mod.normalize_ts(bad) is None


def test_source_order_parses_env_and_falls_back_to_the_default(monkeypatch):
    monkeypatch.delenv(mod.SOURCES_ENV, raising=False)
    assert mod.source_order() == ["hansha", "bonbast"]
    assert mod.source_order("bonbast, Hansha ,bonbast") == ["bonbast", "hansha"]
    assert mod.source_order("bonbast") == ["bonbast"]
    assert mod.source_order("nope,,") == ["hansha", "bonbast"]
    monkeypatch.setenv(mod.SOURCES_ENV, "bonbast,hansha")
    assert mod.source_order() == ["bonbast", "hansha"]


def test_combine_takes_hansha_first_and_fills_ounce_and_btc_from_bonbast():
    bon = bonbast_snapshot()
    snap, counts = mod.combine_sources([mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS), bon], INSTRUMENTS)
    by = {r["code"]: r for r in snap["rates"]}
    assert by["usd"]["sell"] == 266600 and by["gram"]["price"] == 25709865.0  # hansha wins
    assert by["ounce"]["price"] == 4094.2 and by["btc"]["price"] == 81476.39  # only bonbast has them
    assert "eth" in by and "usdt" in by
    assert counts == {"hansha": 6, "bonbast": 2} and snap["source"] == "hansha"
    assert snap["fetchedAt"] == min(bon["fetchedAt"], snap["sourceModified"])  # oldest observation used
    assert [r["code"] for r in snap["rates"]] == [i["code"] for i in INSTRUMENTS if i["code"] in by]


def test_combine_in_bonbast_first_order_keeps_bonbast_values_and_adds_hansha_only_rows():
    bon = bonbast_snapshot()
    snap, counts = mod.combine_sources([bon, mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)], INSTRUMENTS)
    by = {r["code"]: r for r in snap["rates"]}
    assert by["usd"]["sell"] == 265200 and by["eth"]["price"] == 600379000.0
    assert counts == {"bonbast": 5, "hansha": 3} and snap["source"] == "bonbast"
    assert snap["sourceModified"] == "November 7, 2026 15:40"


def test_combine_with_nothing_yields_an_empty_snapshot_main_refuses():
    snap, counts = mod.combine_sources([], INSTRUMENTS)
    assert snap["rates"] == [] and counts == {}


def test_collect_sources_skips_a_failed_source_and_keeps_order():
    def fetch(name, session, instruments):
        if name == "hansha":
            raise requests.ConnectionError("down")
        return bonbast_snapshot()
    results = mod.collect_sources(None, INSTRUMENTS, ["hansha", "bonbast"], fetch=fetch)
    assert [r["source"] for r in results] == ["bonbast"]

    def broken(name, session, instruments):
        raise mod.SourceError(f"{name}: challenge page")
    assert mod.collect_sources(None, INSTRUMENTS, ["hansha", "bonbast"], fetch=broken) == []


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class _Session:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_fetch_source_hansha_end_to_end_and_its_failure_modes():
    s = _Session(_Resp(hansha_rows()))
    snap = mod.fetch_source("hansha", s, INSTRUMENTS)
    assert s.calls[0][0] == "https://hansha.online/latest" and "data" not in s.calls[0][1]
    assert len(snap["rates"]) == 6
    with pytest.raises(mod.SourceError, match="min old"):
        mod.fetch_source("hansha", _Session(_Resp(hansha_rows(minutes_ago=45))), INSTRUMENTS)
    with pytest.raises(mod.SourceError, match="not a JSON array"):
        mod.fetch_source("hansha", _Session(_Resp({"rows": []})), INSTRUMENTS)
    with pytest.raises(mod.SourceError, match="did not return JSON"):
        mod.fetch_source("hansha", _Session(_Resp(ValueError("x"))), INSTRUMENTS)
    with pytest.raises(mod.SourceError, match="no usable rows"):
        mod.fetch_source("hansha", _Session(_Resp([])), INSTRUMENTS)
    with pytest.raises(requests.HTTPError):
        mod.fetch_source("hansha", _Session(_Resp([], status=429)), INSTRUMENTS)


def test_rates_fingerprint_ignores_timestamps_and_tracks_values():
    a = mod.build_hansha_snapshot(hansha_rows(minutes_ago=2), INSTRUMENTS)["rates"]
    b = mod.build_hansha_snapshot(hansha_rows(minutes_ago=8), INSTRUMENTS)["rates"]
    assert mod.rates_fingerprint(a) == mod.rates_fingerprint(b)
    b[0] = dict(b[0], sell=b[0]["sell"] + 100)
    assert mod.rates_fingerprint(a) != mod.rates_fingerprint(b)


def test_intraday_adds_no_point_for_an_unchanged_or_older_observation(tmp_path):
    rates = [{"code": "usd", "buy": 1, "sell": 2, "price": None, "computed": False}]
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T12:11:07Z", "rates": rates}) == 1
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T12:11:07Z", "rates": rates}) == 0
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T12:05:00Z", "rates": rates}) == 0
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T12:17:30Z", "rates": rates}) == 1
    usd = json.loads((tmp_path / "v1" / "intraday" / "usd").read_text(encoding="utf-8"))
    assert [p["ts"] for p in usd["points"]] == ["2026-11-07T12:11:07Z", "2026-11-07T12:17:30Z"]
