import importlib.util
import pathlib

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("crypto_history", ROOT / "crypto_history.py")
ch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ch)

D1, D2, D3 = 1767225600, 1767312000, 1767398400  # 2026-01-01..03 UTC
KRAKEN = {"error": [], "result": {"XXBTZUSD": [[D1, "1", "2", "0.5", "100.123", "1", "1", 1],
                                                [D2, "1", "2", "0.5", "110", "1", "1", 1],
                                                [D3, "1", "2", "0.5", "120", "1", "1", 1]], "last": D3}}
OKX = {"code": "0", "data": [[str(D3 * 1000), "1", "2", "0", "30", "1", "1", "1", "0"],
                             [str(D2 * 1000), "1", "2", "0", "20", "1", "1", "1", "1"],
                             [str(D1 * 1000), "1", "2", "0", "10", "1", "1", "1", "1"]]}
DAILY = {"start": "2018-03-28", "codes": {"usd": {"2026-01-01": [1000, 1010], "2026-01-03": [None, 1030]}}}


def test_parse_kraken_and_okx_skip_unconfirmed():
    assert ch.parse_kraken(KRAKEN) == [("2026-01-01", 100.123), ("2026-01-02", 110.0), ("2026-01-03", 120.0)]
    assert ch.parse_okx(OKX) == [("2026-01-02", 20.0), ("2026-01-01", 10.0)]


def test_parse_garbage_is_empty():
    for bad in (None, {}, [], {"error": ["EQuery"]}, {"result": {"a": [["x"]]}}, {"data": [[1]]}, "x"):
        assert ch.parse_kraken(bad) == [] and ch.parse_okx(bad) == []


def test_usd_quote_rounds_and_drops_today():
    pts = ch.to_points(ch.parse_kraken(KRAKEN), "usd", {}, "2026-01-03")
    assert [p["price"] for p in pts] == [100.12, 110.0]


def test_toman_conversion_skips_missing_usd_date_and_uses_sell_else_buy():
    pts = ch.to_points(ch.parse_kraken(KRAKEN), "toman", DAILY, "2026-02-01")
    assert pts == [{"date": "2026-01-01", "price": 101124.0, "buy": None, "sell": None},
                   {"date": "2026-01-03", "price": 123600.0, "buy": None, "sell": None}]


def test_weekly_points_end_of_week_and_before_cutoff():
    rows = [("2025-12-29", 100.0), ("2026-01-05", 200.0)]
    assert ch.weekly_points(rows, "usd", {}, "2026-01-05") == [{"date": "2026-01-04", "price": 100.0}]


def test_merge_idempotent_existing_wins():
    new = [{"date": "2026-01-01", "price": 1.0}, {"date": "2026-01-02", "price": 2.0}]
    old = [{"date": "2026-01-01", "price": 9.0}]
    once = ch.merge_points(old, new)
    assert once[0]["price"] == 9.0 and len(once) == 2
    assert ch.merge_points(once, new) == once


class Resp:
    def __init__(self, payload, bad=False):
        self.payload, self.bad = payload, bad

    def raise_for_status(self):
        if self.bad:
            raise requests.HTTPError("500")

    def json(self):
        if self.payload is ValueError:
            raise ValueError("x")
        return self.payload


class Sess:
    def __init__(self, resp):
        self.resp, self.calls = resp, 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if params and params.get("interval") == 10080:
            return Resp({"error": [], "result": {"X": [[1766275200, "1", "2", "0.5", "50", "1", "1", 1]]}})
        return self.resp


def test_fetch_failures_are_skipped():
    for resp in (Resp({}, bad=True), Resp(ValueError), Resp({"error": [], "result": {}})):
        assert ch.fetch_kraken(Sess(resp), "XBTUSD", 1440, 0) == []
        assert ch.fetch_okx(Sess(resp), "BNB-USDT", 0) == []


def test_run_writes_matching_schema_and_is_idempotent():
    store = {}
    insts = [{"code": "btc", "kind": "crypto", "quote": "usd"}, {"code": "usd", "kind": "currency", "quote": "toman"}]
    sess = Sess(Resp(KRAKEN))
    load = lambda k: store.get(k)
    write = lambda k, o: store.__setitem__(k, o)
    assert ch.run(sess, insts, DAILY, load, write, today="2026-01-04", pace=0) == 1
    snap = dict(store)
    assert set(store) == {"v1/history/btc", "v1/longhistory/btc"}
    direct = {"code": "usd", "days": 1, "points": [{"date": "d", "price": 1.0, "buy": 1, "sell": 1}]}
    assert set(store["v1/history/btc"]) == set(direct)
    assert set(store["v1/history/btc"]["points"][0]) == set(direct["points"][0])
    assert store["v1/longhistory/btc"]["source"] == "coarse-archive"
    calls = sess.calls
    assert ch.run(sess, insts, DAILY, load, write, today="2026-01-04", pace=0) == 0
    assert sess.calls == calls and store == snap
    assert ch.run(sess, insts, DAILY, load, write, today="2026-01-09", pace=0) == 1
    assert store["v1/history/btc"]["points"] == snap["v1/history/btc"]["points"]


def test_run_failure_writes_nothing():
    store = {}
    insts = [{"code": "eth", "kind": "crypto", "quote": "toman"}]
    assert ch.run(Sess(Resp({}, bad=True)), insts, DAILY, store.get, store.__setitem__, today="2026-01-04", pace=0) == 0
    assert store == {}
