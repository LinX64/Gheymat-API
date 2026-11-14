import importlib.util
import pathlib
import sys

import pytest
import requests

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import live_guard
import source_libs

SPEC = importlib.util.spec_from_file_location("gheymat_snapshot_source_libs", TOOLS / "gheymat_snapshot.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

from test_sources import bonbast_snapshot

INSTRUMENTS = mod.load_instruments()
NOW_ISO = "2026-11-14T10:00:00Z"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for key in ("GHEYMAT_ORDER", "GHEYMAT_LIVE_FIRST_FROM", "GHEYMAT_SOURCES", "GHEYMAT_LIVE_STATE",
                mod.LIBS_ENV):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mod, "INTRADAY_REPAIRS", tmp_path / "no-repairs.json")
    monkeypatch.setattr(mod, "_LIVE_STATE", live_guard.new_state())
    monkeypatch.setattr(mod, "_LIVE_RUN", {"outcome": None, "kind": None})


def full_raw() -> dict:
    raw = {"last_modified": "November 14, 2026 13:40"}
    value = 1000
    for ins in INSTRUMENTS:
        key = ins.get("bonbast_key")
        if ins.get("computed") or not key:
            continue
        value += 137
        if ins["kind"] == "currency":
            raw[f"{key}1"], raw[f"{key}2"] = str(value + 10), str(value)
        elif ins["kind"] == "coin":
            raw[key], raw[f"{key}2"] = str(value * 1000 + 500), str(value * 1000)
        else:
            raw[key] = str(value * 1000)
    raw["ounce"] = "4094.2"
    raw["bitcoin"] = "0"
    del raw["mithqal"]
    raw["chf1"], raw["chf2"] = "0", "0"
    raw["cad1"], raw["cad2"] = "0", "5000"
    del raw["aud1"], raw["aud2"]
    return raw


def test_parity_with_the_hand_written_snapshot():
    pytest.importorskip("bonbast.parsers")
    import bonbast.parsers
    raw = full_raw()
    prices = bonbast.parsers.parse_prices(raw)
    mine = source_libs.snapshot_from_prices(prices, INSTRUMENTS, NOW_ISO, 7)
    old = mod.build_snapshot(raw, INSTRUMENTS)
    assert mine["rates"] == old["rates"]
    assert [list(r) for r in mine["rates"]] == [list(r) for r in old["rates"]]
    assert mine["sourceModified"] == old["sourceModified"] == "November 14, 2026 13:40"
    assert mine["source"] == "bonbast" and mine["flags"] == ["static"]
    assert mine["seq"] == 7 and mine["fetchedAt"] == NOW_ISO
    codes = {r["code"] for r in mine["rates"]}
    assert "ounce" in codes and "btc" not in codes and "mithqal" not in codes
    assert "chf" not in codes and "aud" not in codes
    cad = next(r for r in mine["rates"] if r["code"] == "cad")
    assert cad["sell"] is None and cad["buy"] == 5000
    assert next(r for r in mine["rates"] if r["code"] == "ounce")["price"] == 4094.2


def test_every_direct_instrument_key_is_in_the_library_catalog():
    pytest.importorskip("bonbast.catalog")
    from bonbast.catalog import ALL_CODES
    keys = [i["bonbast_key"].lower() for i in INSTRUMENTS if i.get("bonbast_key") and not i.get("computed")]
    assert keys
    assert [k for k in keys if k not in ALL_CODES] == []


class FakeClient:
    error = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        FakeClient.last = self

    def prices(self):
        raise FakeClient.error

    def close(self):
        self.closed = True


def _fetch(monkeypatch, error):
    pytest.importorskip("bonbast")
    import bonbast
    FakeClient.error = error
    monkeypatch.setattr(bonbast, "BonbastClient", FakeClient)
    try:
        return source_libs.fetch_bonbast_prices(
            mod.UA, mod.COOKIES, source_error=mod.SourceError, blocked_error=mod.SourceBlocked)
    finally:
        assert FakeClient.last.closed


def _http_error(status, body="", retry_after=None):
    pytest.importorskip("bonbast.errors")
    from bonbast.errors import NetworkError
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    if retry_after is not None:
        resp.headers["Retry-After"] = retry_after
    try:
        raise NetworkError(f"HTTP {status}") from requests.HTTPError(response=resp)
    except NetworkError as e:
        return e


def test_client_is_built_without_retries_and_with_our_headers(monkeypatch):
    pytest.importorskip("bonbast.errors")
    from bonbast.errors import BonbastError
    with pytest.raises(mod.SourceError):
        _fetch(monkeypatch, BonbastError("x"))
    kwargs = FakeClient.last.kwargs
    session = kwargs["session"]
    assert kwargs["timeout"] == 20
    assert kwargs["token_cache"].path is None
    assert session.headers["User-Agent"] == mod.UA
    assert session.headers["Accept-Language"] == "en-US,en;q=0.9"
    assert session.cookies.get("st_bb") == "0"
    assert session.get_adapter("https://x").max_retries.total == 0


def test_parse_errors_become_blocked_token_or_format(monkeypatch):
    pytest.importorskip("bonbast.errors")
    from bonbast.errors import ParseError
    with pytest.raises(mod.SourceBlocked) as e:
        _fetch(monkeypatch, ParseError("could not find the access token on the site"))
    assert e.value.kind == "token"
    with pytest.raises(mod.SourceBlocked) as e:
        _fetch(monkeypatch, ParseError("returned no prices"))
    assert e.value.kind == "format"


def test_http_errors_are_classified_by_the_shared_guard(monkeypatch):
    with pytest.raises(mod.SourceBlocked) as e:
        _fetch(monkeypatch, _http_error(429, retry_after="120"))
    assert e.value.kind == "status" and e.value.retry_after == 120
    with pytest.raises(mod.SourceBlocked) as e:
        _fetch(monkeypatch, _http_error(200, body="Just a moment"))
    assert e.value.kind == "challenge"
    with pytest.raises(mod.SourceError) as e:
        _fetch(monkeypatch, _http_error(500))
    assert not isinstance(e.value, mod.SourceBlocked)


def test_transport_errors_are_reraised_as_requests_errors(monkeypatch):
    pytest.importorskip("bonbast.errors")
    from bonbast.errors import NetworkError
    try:
        raise NetworkError("slow") from requests.Timeout("t")
    except NetworkError as err:
        timeout = err
    with pytest.raises(requests.Timeout):
        _fetch(monkeypatch, timeout)
    try:
        raise NetworkError("down") from requests.ConnectionError("c")
    except NetworkError as err:
        down = err
    with pytest.raises(requests.ConnectionError):
        _fetch(monkeypatch, down)
    with pytest.raises(mod.SourceError):
        _fetch(monkeypatch, NetworkError("plain"))


class Clock:
    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def _patch_prices(monkeypatch, currency=None, metal=None):
    pytest.importorskip("gheymat.currency")
    pytest.importorskip("gheymat.metal")
    from gheymat import currency as c, metal as m
    calls = []

    def make(fn, tag):
        def get_price(key, toman=True):
            calls.append((tag, key, toman))
            return fn(key)
        return get_price
    monkeypatch.setattr(c, "get_price", make(currency or (lambda k: 2_700_000), "currency"))
    monkeypatch.setattr(m, "get_price", make(metal or (lambda k: 2_000_000), "metal"))
    return calls


def test_third_snapshot_maps_rows_without_inventing_a_buy(monkeypatch):
    calls = _patch_prices(monkeypatch)
    snap = source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 9, mod.SourceError)
    assert snap["source"] == "third" and snap["sourceModified"] is None
    assert snap["flags"] == ["static"] and snap["seq"] == 9 and snap["fetchedAt"] == NOW_ISO
    assert len(calls) == len(source_libs.THIRD_MAP) and all(t for _, _, t in calls)
    by = {r["code"]: r for r in snap["rates"]}
    assert set(by) == set(source_libs.THIRD_MAP)
    assert by["usd"]["sell"] == 2_700_000 and by["usd"]["buy"] is None and by["usd"]["price"] is None
    assert by["gram"]["price"] == 2_000_000.0 and isinstance(by["gram"]["price"], float)
    assert by["gram"]["buy"] is None and by["gram"]["sell"] is None
    assert by["emami"]["sell"] == 2_000_000 and by["emami"]["buy"] is None
    for r in snap["rates"]:
        assert r["computed"] is False and r["buyRaw"] is None and r["sellRaw"] is None


def test_third_snapshot_only_covers_instruments_given(monkeypatch):
    calls = _patch_prices(monkeypatch)
    only = [i for i in INSTRUMENTS if i["code"] in ("usd", "gram", "jpy")]
    snap = source_libs.third_snapshot(only, NOW_ISO, 1, mod.SourceError)
    assert [r["code"] for r in snap["rates"]] == ["usd", "gram"]
    assert len(calls) == 2


def test_third_snapshot_skips_failures_and_fails_when_nothing_is_usable(monkeypatch):
    def flaky(key):
        if key in ("eur", "gold18"):
            raise RuntimeError("boom")
        if key == "gbp":
            return 0
        return 1234

    _patch_prices(monkeypatch, currency=flaky, metal=flaky)
    snap = source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError)
    codes = {r["code"] for r in snap["rates"]}
    assert "eur" not in codes and "gram" not in codes and "gbp" not in codes and "usd" in codes

    def boom(key):
        raise ValueError("x")

    _patch_prices(monkeypatch, currency=boom, metal=boom)
    with pytest.raises(mod.SourceError):
        source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError)


def test_third_snapshot_respects_the_call_and_time_budgets(monkeypatch):
    calls = _patch_prices(monkeypatch)
    snap = source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError, max_calls=3)
    assert len(calls) == 3 and len(snap["rates"]) == 3
    calls.clear()
    snap = source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError,
                                      budget_seconds=25.0, clock=Clock(10.0))
    assert len(calls) == 2 and len(snap["rates"]) == 2


def test_third_snapshot_sleeps_between_calls_only_when_asked(monkeypatch):
    _patch_prices(monkeypatch)
    slept = []
    monkeypatch.setattr(source_libs.time, "sleep", slept.append)
    source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError, max_calls=3)
    assert slept == []
    source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError, max_calls=3, sleep_between=0.5)
    assert slept == [0.5, 0.5]


def test_mapped_codes_all_exist_as_instruments():
    codes = {i["code"] for i in INSTRUMENTS}
    assert source_libs.THIRD_CODES <= codes


class Boom:
    def __getattr__(self, name):
        raise AssertionError("source_libs must not be touched")


def test_defaults_are_unchanged(monkeypatch):
    assert mod.DEFAULT_SOURCES == ("hansha", "bonbast")
    assert not hasattr(mod, "KNOWN_SOURCES")
    assert mod.source_order() == ["hansha", "bonbast"]
    monkeypatch.setenv("GHEYMAT_SOURCES", "hansha,bonbast,third")
    assert mod.source_order() == ["hansha", "bonbast"]
    monkeypatch.setenv("GHEYMAT_SOURCES", "third")
    assert mod.source_order() == ["hansha", "bonbast"]


def test_third_env_appends_third_last_and_unset_changes_nothing(monkeypatch):
    now = 1_800_000_000.0
    state = live_guard.new_state()
    base = mod.plan_sources(now, state)
    assert base == ["hansha", "bonbast"]
    for value in ("", "off", "1"):
        monkeypatch.setenv(mod.THIRD_ENV, value)
        assert mod.plan_sources(now, state) == base
    monkeypatch.setenv(mod.THIRD_ENV, " On ")
    assert mod.plan_sources(now, state) == ["hansha", "bonbast", "third"]
    monkeypatch.setenv("GHEYMAT_ORDER", "live-first")
    assert mod.plan_sources(now, state) == ["bonbast", "hansha", "third"]
    monkeypatch.setenv("GHEYMAT_ORDER", "primary-only")
    assert mod.plan_sources(now, state) == ["hansha", "third"]
    monkeypatch.setenv("GHEYMAT_SOURCES", "bonbast")
    assert mod.plan_sources(now, state) == ["bonbast", "third"]


def test_third_never_becomes_the_published_source_when_others_contributed():
    bon = fake_snap("bonbast", ["usd"])
    third = fake_snap("third", ["eur", "gbp", "try"])
    snap, counts, _ = mod.combine_sources([bon, third], INSTRUMENTS)
    assert snap["source"] == "bonbast" and counts == {"bonbast": 1, "third": 3}
    snap, _, _ = mod.combine_sources([third], INSTRUMENTS)
    assert snap["source"] == "third"


def test_missing_library_raises_a_plain_source_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "bonbast", None)
    with pytest.raises(mod.SourceError) as e:
        source_libs.fetch_bonbast_prices(
            mod.UA, mod.COOKIES, source_error=mod.SourceError, blocked_error=mod.SourceBlocked)
    assert not isinstance(e.value, mod.SourceBlocked)


def test_missing_third_library_raises_a_plain_source_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "gheymat", None)
    with pytest.raises(mod.SourceError):
        source_libs.third_snapshot(INSTRUMENTS, NOW_ISO, 1, mod.SourceError)


@pytest.mark.parametrize("value", [None, "", "off", "0", "yes"])
def test_bonbast_uses_the_old_path_unless_libs_are_on(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(mod.LIBS_ENV, value)
    raw = {"usd1": "265200", "usd2": "265000", "last_modified": "x"}
    seen = []
    monkeypatch.setattr(mod, "fetch_raw", lambda session: seen.append(session) or raw)
    monkeypatch.setitem(sys.modules, "source_libs", Boom())
    snap = mod.fetch_source("bonbast", "sess", INSTRUMENTS)
    assert seen == ["sess"]
    assert snap["rates"] == mod.build_snapshot(raw, INSTRUMENTS)["rates"]


def test_bonbast_uses_the_library_when_switched_on(monkeypatch):
    monkeypatch.setenv(mod.LIBS_ENV, " ON ")
    monkeypatch.setattr(mod, "fetch_raw", lambda session: pytest.fail("old path used"))
    pytest.importorskip("bonbast.parsers")
    import bonbast.parsers
    prices = bonbast.parsers.parse_prices({"usd1": "265200", "usd2": "265000", "last_modified": "x"})
    seen = {}

    def fake(ua, cookies, *, source_error, blocked_error, timeout=20):
        seen.update(ua=ua, cookies=cookies, source_error=source_error, blocked_error=blocked_error)
        return prices

    monkeypatch.setattr(source_libs, "fetch_bonbast_prices", fake)
    snap = mod.fetch_source("bonbast", None, INSTRUMENTS)
    assert seen == {"ua": mod.UA, "cookies": mod.COOKIES, "source_error": mod.SourceError,
                    "blocked_error": mod.SourceBlocked}
    assert [r["code"] for r in snap["rates"]] == ["usd"] and snap["sourceModified"] == "x"


def test_third_source_is_dispatched_by_fetch_source(monkeypatch):
    calls = _patch_prices(monkeypatch)
    snap = mod.fetch_source("third", None, [i for i in INSTRUMENTS if i["code"] == "usd"])
    assert snap["source"] == "third" and len(calls) == 1


def test_importing_the_snapshot_module_does_not_import_the_libraries():
    def names():
        return [n for n in sys.modules if n in ("bonbast", "gheymat") or n.startswith(("bonbast.", "gheymat."))]

    saved = {n: sys.modules.pop(n) for n in names()}
    try:
        assert names() == []
        spec = importlib.util.spec_from_file_location("gheymat_snapshot_fresh", TOOLS / "gheymat_snapshot.py")
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        assert names() == []
    finally:
        for n in names():
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def fake_snap(source, codes):
    return {"source": source, "fetchedAt": NOW_ISO, "sourceModified": None, "flags": ["static"],
            "rates": [{"code": c} for c in codes]}


def test_third_is_skipped_when_earlier_sources_cover_its_codes(capsys):
    seen = []

    def fetch(name, session, instruments):
        seen.append(name)
        return fake_snap(name, source_libs.THIRD_CODES)

    results = mod.collect_sources(None, INSTRUMENTS, ["hansha", "bonbast", "third"], fetch=fetch)
    assert seen == ["hansha", "bonbast"] and len(results) == 2
    assert "source 3: not needed" in capsys.readouterr().err


def test_third_gets_only_the_uncovered_instruments(capsys):
    given = {}

    def fetch(name, session, instruments):
        given[name] = [i["code"] for i in instruments]
        if name == "third":
            return fake_snap("third", ["gbp"])
        return fake_snap(name, ["usd", "eur"])

    results = mod.collect_sources(None, INSTRUMENTS, ["hansha", "bonbast", "third"], fetch=fetch)
    assert [r["source"] for r in results] == ["hansha", "bonbast", "third"]
    assert given["hansha"] == given["bonbast"] == [i["code"] for i in INSTRUMENTS]
    assert given["third"] == [i["code"] for i in INSTRUMENTS if i["code"] not in ("usd", "eur")]
    assert "not needed" not in capsys.readouterr().err


def test_third_is_skipped_when_nothing_mapped_is_left(capsys):
    def fetch(name, session, instruments):
        if name == "third":
            pytest.fail("third must not run")
        return fake_snap(name, source_libs.THIRD_CODES)

    mod.collect_sources(None, INSTRUMENTS, ["bonbast", "third"], fetch=fetch)
    assert "not needed" in capsys.readouterr().err


def test_a_failing_first_source_does_not_stop_the_rest(capsys):
    given = {}

    def fetch(name, session, instruments):
        given[name] = [i["code"] for i in instruments]
        if name == "hansha":
            raise mod.SourceError("hansha: down")
        if name == "bonbast":
            return fake_snap("bonbast", ["usd"])
        return fake_snap("third", ["eur"])

    results = mod.collect_sources(None, INSTRUMENTS, ["hansha", "bonbast", "third"], fetch=fetch)
    assert [r["source"] for r in results] == ["bonbast", "third"]
    assert "usd" not in given["third"]
    err = capsys.readouterr().err
    assert "source 1: skipped" in err and "hansha" not in err


def test_collect_sources_without_third_is_unchanged():
    given = []

    def fetch(name, session, instruments):
        given.append(len(instruments))
        return bonbast_snapshot()

    mod.collect_sources(None, INSTRUMENTS, ["hansha", "bonbast"], fetch=fetch)
    assert given == [len(INSTRUMENTS)] * 2
