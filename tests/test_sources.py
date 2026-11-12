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


@pytest.fixture(autouse=True)
def no_repairs(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "INTRADAY_REPAIRS", tmp_path / "no-repairs.json")


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
        {"ab": "jpy", "av": "🇯🇵", "en": "Japanese Yen", "fa": "ین ژاپن", "ty": "cu",
         "ps": [{"bp": 1670.0, "sp": 1680.0, "ts": ts}]},
        {"ab": "amd", "av": "🇦🇲", "en": "Armenian Dram", "fa": "درام ارمنستان", "ty": "cu",
         "ps": [{"bp": 737.0, "sp": 737.5, "ts": ts}]},
        {"ab": "iqd", "av": "🇮🇶", "en": "Iraqi Dinar", "fa": "دینار عراق", "ty": "cu",
         "ps": [{"bp": 174.5, "sp": 175.5, "ts": ts}]},
        {"ab": "zzz", "av": "?", "en": "Unknown", "fa": "?", "ty": "cu", "ps": [{"bp": 1, "sp": 2, "ts": ts}]},
        "not a row",
    ]


def bonbast_snapshot() -> dict:
    raw = {"usd1": "265200", "usd2": "265000", "eur1": "294800", "eur2": "294600", "ounce": "4094.2",
           "bitcoin": "81476.39", "gol18": "26136940", "jpy1": "16800", "jpy2": "16700", "amd1": "7375",
           "amd2": "7370", "iqd1": "17550", "iqd2": "17450", "last_modified": "November 7, 2026 15:40"}
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
    assert by["usdt"]["en"] == "Tether"
    assert "btc" not in by and "ounce" not in by and "zzz" not in by
    assert [r["code"] for r in snap["rates"]] == [c for c in (i["code"] for i in INSTRUMENTS) if c in by]
    assert snap["fetchedAt"] == snap["sourceModified"]


def test_hansha_row_far_behind_the_feed_is_dropped_so_it_cannot_age_the_snapshot():
    rows = hansha_rows(minutes_ago=1)
    rows[1]["ps"][0]["ts"] = iso(90)
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
    snap, counts, _ = mod.combine_sources([mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS), bon], INSTRUMENTS)
    by = {r["code"]: r for r in snap["rates"]}
    assert by["usd"]["sell"] == 266600 and by["gram"]["price"] == 25709865.0
    assert by["ounce"]["price"] == 4094.2 and by["btc"]["price"] == 81476.39
    assert "eth" in by and "usdt" in by
    assert counts == {"hansha": 9, "bonbast": 2} and snap["source"] == "hansha"
    assert snap["fetchedAt"] == min(bon["fetchedAt"], snap["sourceModified"])
    assert [r["code"] for r in snap["rates"]] == [i["code"] for i in INSTRUMENTS if i["code"] in by]


def test_combine_in_bonbast_first_order_keeps_bonbast_values_and_adds_hansha_only_rows():
    bon = bonbast_snapshot()
    snap, counts, _ = mod.combine_sources([bon, mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)], INSTRUMENTS)
    by = {r["code"]: r for r in snap["rates"]}
    assert by["usd"]["sell"] == 265200 and by["eth"]["price"] == 600379000.0
    assert counts == {"bonbast": 8, "hansha": 3} and snap["source"] == "bonbast"
    assert snap["sourceModified"] == "November 7, 2026 15:40"


def test_combine_with_nothing_yields_an_empty_snapshot_main_refuses():
    snap, counts, observed = mod.combine_sources([], INSTRUMENTS)
    assert snap["rates"] == [] and counts == {} and observed == {}


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
    assert len(snap["rates"]) == 9
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


def _stamps(tmp_path, code) -> list[str]:
    return [p["ts"] for p in json.loads((tmp_path / "v1" / "intraday" / code).read_text(encoding="utf-8"))["points"]]


def test_intraday_samples_are_keyed_by_each_rows_own_observation(tmp_path):
    usd_ts, eur_ts = iso(2), iso(9)
    rows = hansha_rows()
    rows[0]["ps"][0]["ts"], rows[1]["ps"][0]["ts"] = usd_ts, eur_ts
    bon = bonbast_snapshot()
    snap, _, observed = mod.combine_sources([mod.build_hansha_snapshot(rows, INSTRUMENTS), bon], INSTRUMENTS)
    assert (observed["usd"], observed["eur"], observed["ounce"]) == (usd_ts, eur_ts, bon["fetchedAt"])
    assert set(observed) == {r["code"] for r in snap["rates"]}
    assert snap["fetchedAt"] == eur_ts
    mod.append_intraday(tmp_path, snap, observed)
    assert [_stamps(tmp_path, c) for c in ("usd", "eur", "ounce")] == [[usd_ts], [eur_ts], [bon["fetchedAt"]]]


def test_a_hansha_run_after_a_bonbast_only_run_ticks_every_code_whose_own_stamp_advanced(tmp_path):
    bonbast_ts, lagging_ts, fresh_ts, bonbast_now = iso(10), iso(20), iso(2), iso(0)
    first, _, observed = mod.combine_sources([dict(bonbast_snapshot(), fetchedAt=bonbast_ts)], INSTRUMENTS)
    mod.append_intraday(tmp_path, first, observed)
    rows = [row for row in hansha_rows() if isinstance(row, dict)]
    for row in rows:
        row["ps"][0]["ts"] = fresh_ts
    rows[1]["ps"][0]["ts"] = lagging_ts
    second, _, observed = mod.combine_sources(
        [mod.build_hansha_snapshot(rows, INSTRUMENTS), dict(bonbast_snapshot(), fetchedAt=bonbast_now)], INSTRUMENTS)
    assert second["fetchedAt"] == lagging_ts < bonbast_ts
    assert mod.append_intraday(tmp_path, second, observed) == len(second["rates"]) - 1
    assert _stamps(tmp_path, "usd") == _stamps(tmp_path, "jpy") == [bonbast_ts, fresh_ts]
    assert _stamps(tmp_path, "ounce") == [bonbast_ts, bonbast_now]
    assert _stamps(tmp_path, "eur") == [bonbast_ts]


SNAPSHOT_KEYS = {"seq", "fetchedAt", "sourceModified", "source", "flags", "rates"}
RATE_KEYS = {"code", "kind", "unit", "quote", "buy", "sell", "price", "en", "fa", "flag", "computed", "buyRaw", "sellRaw"}


def test_published_latest_keeps_exactly_the_old_keys(tmp_path, monkeypatch):
    rows = hansha_rows()
    usd_ts, eur_ts = rows[0]["ps"][0]["ts"], iso(9)
    rows[1]["ps"][0]["ts"] = eur_ts
    sources = [mod.build_hansha_snapshot(rows, INSTRUMENTS), bonbast_snapshot()]
    monkeypatch.setattr(mod, "collect_sources", lambda session, instruments, order: sources)
    monkeypatch.setattr(mod, "fetch_computed_rates", lambda session, rates, instruments: [])
    monkeypatch.setattr(mod, "MIN_DIRECT", 1)
    for name in ("SEALER", "PLAIN_ALSO", "_DIST_ROOT"):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    for key in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "GHEYMAT_PLAIN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mod.sys, "argv", ["gheymat_snapshot.py", "--out", str(tmp_path)])
    assert mod.main() == 0
    latest = json.loads((tmp_path / "v1" / "latest").read_text(encoding="utf-8"))
    assert set(latest) == SNAPSHOT_KEYS and latest["fetchedAt"] == eur_ts
    assert len(latest["rates"]) == 11 and all(set(r) == RATE_KEYS for r in latest["rates"])
    assert _stamps(tmp_path, "usd") == [usd_ts]


def test_hansha_per_one_quotes_are_scaled_to_our_unit():
    by = {r["code"]: r for r in mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)["rates"]}
    assert (by["jpy"]["unit"], by["jpy"]["buy"], by["jpy"]["sell"]) == (10, 16700, 16800)
    assert (by["amd"]["unit"], by["amd"]["buy"], by["amd"]["sell"]) == (10, 7370, 7375)
    assert (by["iqd"]["unit"], by["iqd"]["buy"], by["iqd"]["sell"]) == (100, 17450, 17550)
    assert (by["usd"]["buy"], by["usd"]["sell"]) == (266400, 266600)


def test_every_code_both_sources_carry_agrees_within_five_percent():
    hansha = {r["code"]: r for r in mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)["rates"]}
    bonbast = {r["code"]: r for r in bonbast_snapshot()["rates"]}
    both = sorted(set(hansha) & set(bonbast))
    assert {"usd", "eur", "gram", "jpy", "amd", "iqd"} <= set(both)
    for code in both:
        h = hansha[code]["sell"] or hansha[code]["price"]
        b = bonbast[code]["sell"] or bonbast[code]["price"]
        assert 0.95 <= h / b <= 1.05, (code, h, b)


def _intraday(tmp_path, code, points):
    path = tmp_path / "v1" / "intraday" / code
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"code": code, "days": 7, "points": points}), encoding="utf-8")
    return path


UNIT_REPAIR = {"codes": ["amd", "jpy", "iqd"], "from": "2026-11-07T12:00:00Z", "to": "2026-11-08T00:00:00Z",
               "belowFactor": 3, "note": "hansha per-1 quotes published unscaled until 4e02873d7"}
DAY = 24 * 60


def _repairs(tmp_path, monkeypatch, body):
    path = tmp_path / "repairs.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(mod, "INTRADAY_REPAIRS", path)
    return path


def test_committed_repairs_file_parses_entry_for_entry(capsys):
    path = mod.HERE / "intraday_repairs.json"
    entries = mod.load_repairs(path)
    assert capsys.readouterr().err == ""
    assert len(entries) == len(json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])


def test_intraday_repair_drops_only_the_unscaled_jpy_points_in_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "INTRADAY_DAYS", 100_000)
    _repairs(tmp_path, monkeypatch, [UNIT_REPAIR])
    good_before = {"ts": "2026-11-07T11:55:00Z", "buy": 16650, "sell": 16750, "price": None}
    bad = [{"ts": f"2026-11-07T1{h}:20:00Z", "buy": 1670, "sell": 1680, "price": None} for h in (2, 4, 6)]
    jpy = _intraday(tmp_path, "jpy", [good_before, *bad])
    usd_points = [{"ts": "2026-11-07T12:20:00Z", "buy": 266400, "sell": 266600, "price": None}]
    usd = _intraday(tmp_path, "usd", usd_points)
    rates = [{"code": "jpy", "buy": 16700, "sell": 16800, "price": None, "computed": False},
             {"code": "usd", "buy": 266400, "sell": 266600, "price": None, "computed": False}]
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T17:00:00Z", "rates": rates}) == 2
    pts = json.loads(jpy.read_text(encoding="utf-8"))["points"]
    assert [p["sell"] for p in pts] == [16750, 16800]
    assert len(json.loads(usd.read_text(encoding="utf-8"))["points"]) == 2


def test_intraday_repair_writes_even_when_the_observation_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "INTRADAY_DAYS", 100_000)
    _repairs(tmp_path, monkeypatch, [UNIT_REPAIR])
    jpy = _intraday(tmp_path, "jpy", [{"ts": "2026-11-07T12:20:00Z", "buy": 1670, "sell": 1680, "price": None},
                                      {"ts": "2026-11-07T17:00:00Z", "buy": 16700, "sell": 16800, "price": None}])
    rates = [{"code": "jpy", "buy": 16700, "sell": 16800, "price": None, "computed": False}]
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T17:00:00Z", "rates": rates}) == 1
    assert [p["sell"] for p in json.loads(jpy.read_text(encoding="utf-8"))["points"]] == [16800]
    assert mod.append_intraday(tmp_path, {"fetchedAt": "2026-11-07T17:00:00Z", "rates": rates}) == 0


def test_intraday_repair_ignores_points_outside_the_window_or_codes(tmp_path, monkeypatch):
    repairs = mod.load_repairs(_repairs(tmp_path, monkeypatch, [UNIT_REPAIR]))
    early = {"ts": "2026-11-06T12:20:00Z", "buy": 1670, "sell": 1680, "price": None}
    assert mod.drop_repaired_points("jpy", [early], 16800.0, repairs) == [early]
    inside = {"ts": "2026-11-07T12:20:00Z", "buy": 1, "sell": 2, "price": None}
    assert mod.drop_repaired_points("usd", [inside], 266600.0, repairs) == [inside]
    assert mod.drop_repaired_points("jpy", [inside], None, repairs) == [inside]


def test_intraday_repair_without_below_factor_drops_every_window_point_of_its_codes_only(tmp_path, monkeypatch):
    t400, lo, t200, hi, t60, now = iso(400), iso(300), iso(200), iso(120), iso(60), iso(1)
    _repairs(tmp_path, monkeypatch, [{"codes": ["usd", "eur"], "from": lo, "to": hi, "note": "a bad source window"}])
    rates = []
    for code in ("usd", "eur", "jpy"):
        _intraday(tmp_path, code, [{"ts": ts, "buy": 1, "sell": 2, "price": None} for ts in (t400, lo, t200, hi, t60)])
        rates.append({"code": code, "buy": 1, "sell": 2, "price": None, "computed": False})
    assert mod.append_intraday(tmp_path, {"fetchedAt": now, "rates": rates}) == 3
    assert _stamps(tmp_path, "usd") == _stamps(tmp_path, "eur") == [t400, hi, t60, now]
    assert _stamps(tmp_path, "jpy") == [t400, lo, t200, hi, t60, now]


def test_intraday_repair_whose_window_left_the_retention_is_a_no_op(tmp_path, monkeypatch):
    _repairs(tmp_path, monkeypatch, [{"codes": ["usd"], "from": iso(20 * DAY), "to": iso(10 * DAY), "note": "old"}])
    last = {"ts": iso(1), "buy": 3, "sell": 4, "price": None}
    usd = _intraday(tmp_path, "usd", [{"ts": iso(15 * DAY), "buy": 1, "sell": 2, "price": None}, last])
    before = usd.read_text(encoding="utf-8")
    rates = [{"code": "usd", "buy": 3, "sell": 4, "price": None, "computed": False}]
    assert mod.append_intraday(tmp_path, {"fetchedAt": last["ts"], "rates": rates}) == 0
    assert usd.read_text(encoding="utf-8") == before


WIDE = {"codes": ["usd"], "from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"}


@pytest.mark.parametrize("body", [
    "{not json",
    json.dumps({"repairs": [WIDE]}),
    json.dumps([WIDE, "usd"]),
    json.dumps([WIDE, dict(WIDE, codes="usd")]),
    json.dumps([WIDE, dict(WIDE, to="tomorrow")]),
    json.dumps([WIDE, {"codes": ["usd"], "from": WIDE["from"]}]),
    json.dumps([WIDE, dict(WIDE, belowFactor=True)]),
    json.dumps([WIDE, dict(WIDE, belowFactor=0)]),
])
def test_malformed_repairs_file_is_logged_and_ignored_whole(tmp_path, monkeypatch, capsys, body):
    _repairs(tmp_path, monkeypatch, body)
    old, now = iso(30), iso(1)
    _intraday(tmp_path, "usd", [{"ts": old, "buy": 1, "sell": 2, "price": None}])
    rates = [{"code": "usd", "buy": 1, "sell": 2, "price": None, "computed": False}]
    assert mod.append_intraday(tmp_path, {"fetchedAt": now, "rates": rates}) == 1
    assert _stamps(tmp_path, "usd") == [old, now]
    assert "intraday repairs:" in capsys.readouterr().err


def test_long_history_is_scaled_to_our_unit(tmp_path):
    archive = tmp_path / "all.json"
    series = [{"sp": 150.5, "ts": f"2024-01-{d:02d}T00:00:00Z"} for d in range(1, 12)]
    archive.write_text(json.dumps([{"ab": "jpy", "ps": series}, {"ab": "usd", "ps": series}]), encoding="utf-8")
    assert mod.write_long_history(tmp_path, archive, {i["code"]: i["unit"] for i in INSTRUMENTS}) == 2
    jpy = json.loads((tmp_path / "v1" / "longhistory" / "jpy").read_text(encoding="utf-8"))
    usd = json.loads((tmp_path / "v1" / "longhistory" / "usd").read_text(encoding="utf-8"))
    assert jpy["points"][0]["price"] == 1505.0 and usd["points"][0]["price"] == 150.5
