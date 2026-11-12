"""Live-first ordering, block classification, quiet periods and the live-first guards. No network."""
import importlib.util
import json
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import live_guard  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "gheymat_snapshot_live_first", pathlib.Path(__file__).resolve().parents[1] / "tools" / "gheymat_snapshot.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

from test_sources import bonbast_snapshot, hansha_rows, iso  # noqa: E402

INSTRUMENTS = mod.load_instruments()
HANSHA_ONLY = {"eth", "xrp", "bch", "ltc", "bnb", "usdt"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for key in ("GHEYMAT_ORDER", "GHEYMAT_LIVE_FIRST_FROM", "GHEYMAT_SOURCES", "GHEYMAT_LIVE_STATE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mod, "INTRADAY_REPAIRS", tmp_path / "no-repairs.json")
    monkeypatch.setattr(mod, "_LIVE_STATE", live_guard.new_state())
    monkeypatch.setattr(mod, "_LIVE_RUN", {"outcome": None, "kind": None})


NOW = time.time()


# --- (i) default mode unchanged

def test_default_mode_order_and_freshness_are_unchanged():
    assert mod.plan_sources(NOW, live_guard.new_state()) == ["hansha", "bonbast"]
    assert mod.source_order() == ["hansha", "bonbast"]
    assert mod.live_first_active(NOW) is False
    rows = hansha_rows()
    old = iso(20)
    next(r for r in rows if r["ab"] == "eth")["ps"][0]["ts"] = old
    results = [mod.build_hansha_snapshot(rows, INSTRUMENTS), bonbast_snapshot()]
    snap, _, _ = mod.combine_sources(results, INSTRUMENTS)
    assert snap["fetchedAt"] == old  # oldest over everything, as before
    again, _, _ = mod.combine_sources(results, INSTRUMENTS, live_first=False)
    assert again["fetchedAt"] == old


# --- (ii) modes

def test_live_first_mode_and_primary_only(monkeypatch):
    state = live_guard.new_state()
    monkeypatch.setenv("GHEYMAT_ORDER", "live-first")
    assert mod.plan_sources(NOW, state) == ["bonbast", "hansha"]
    assert mod.live_first_active(NOW)
    monkeypatch.setenv("GHEYMAT_ORDER", "primary-only")
    assert mod.plan_sources(NOW, state) == ["hansha"]
    assert not mod.live_first_active(NOW)
    monkeypatch.setenv("GHEYMAT_ORDER", "nonsense")
    assert mod.plan_sources(NOW, state) == ["hansha", "bonbast"]


def test_live_first_from_date(monkeypatch):
    state = live_guard.new_state()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setenv("GHEYMAT_LIVE_FIRST_FROM", past)
    assert mod.effective_mode(NOW) == "live-first"
    assert mod.plan_sources(NOW, state) == ["bonbast", "hansha"]
    monkeypatch.setenv("GHEYMAT_LIVE_FIRST_FROM", future)
    assert mod.effective_mode(NOW) == "default"
    monkeypatch.setenv("GHEYMAT_LIVE_FIRST_FROM", "not a date")
    assert mod.effective_mode(NOW) == "default"
    monkeypatch.setenv("GHEYMAT_LIVE_FIRST_FROM", past)
    monkeypatch.setenv("GHEYMAT_ORDER", "primary-only")  # an explicit mode is not overridden by the date
    assert mod.effective_mode(NOW) == "primary-only"


def test_explicit_sources_win(monkeypatch):
    monkeypatch.setenv("GHEYMAT_ORDER", "live-first")
    monkeypatch.setenv("GHEYMAT_SOURCES", "bonbast,hansha")
    assert mod.plan_sources(NOW, live_guard.new_state()) == ["bonbast", "hansha"]
    monkeypatch.setenv("GHEYMAT_SOURCES", "hansha,bonbast")
    assert mod.plan_sources(NOW, live_guard.new_state()) == ["hansha", "bonbast"]
    assert mod.live_first_active(NOW) is False


# --- (iii) classification wiring

class Resp:
    def __init__(self, status=200, text="", headers=None, body=None, bad_json=False):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self._body, self._bad = body, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if self._bad:
            raise ValueError("bad")
        return self._body


class Session:
    def __init__(self, get=None, post=None):
        self._get, self._post = get, post
        self.gets = self.posts = 0

    def get(self, url, **kw):
        self.gets += 1
        return self._get

    def post(self, url, **kw):
        self.posts += 1
        return self._post


TOKEN_PAGE = Resp(200, 'var param = "abc";')


def _neutral(e):
    text = str(e).lower()
    assert "bonbast" not in text and "http" not in text and ".com" not in text


def test_token_page_403_is_blocked_status():
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.get_token(Session(get=Resp(403)))
    assert ei.value.kind == "status" and ei.value.retry_after is None
    _neutral(ei.value)


def test_429_carries_retry_after():
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.get_token(Session(get=Resp(429, headers={"Retry-After": "120"})))
    assert (ei.value.kind, ei.value.retry_after) == ("status", 120)


def test_challenge_page_and_missing_token():
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.get_token(Session(get=Resp(200, "<html>Just a moment...</html>")))
    assert ei.value.kind == "challenge"
    _neutral(ei.value)
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.get_token(Session(get=Resp(200, "<html>nothing here</html>")))
    assert ei.value.kind == "token"


def test_server_error_is_a_plain_failure_not_a_block():
    with pytest.raises(mod.SourceError) as ei:
        mod.get_token(Session(get=Resp(500)))
    assert not isinstance(ei.value, mod.SourceBlocked)
    assert str(ei.value) == "live source failed"


def test_fetch_raw_format_and_reset(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.fetch_raw(Session(get=TOKEN_PAGE, post=Resp(200, bad_json=True)))
    assert ei.value.kind == "format"
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.fetch_raw(Session(get=TOKEN_PAGE, post=Resp(200, body=[1, 2])))
    assert ei.value.kind == "format"
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.fetch_raw(Session(get=TOKEN_PAGE, post=Resp(200, body={"reset": 1})))
    assert ei.value.kind == "token"
    with pytest.raises(mod.SourceBlocked) as ei:
        mod.fetch_raw(Session(get=TOKEN_PAGE, post=Resp(403)))
    assert ei.value.kind == "status"
    _neutral(ei.value)
    assert mod.fetch_raw(Session(get=TOKEN_PAGE, post=Resp(200, body={"usd1": "1"}))) == {"usd1": "1"}


def test_converter_block_is_recorded_and_returns_none():
    assert mod.fetch_converter(Session(post=Resp(429, headers={"Retry-After": "60"}))) is None
    assert live_guard.is_quiet(mod._LIVE_STATE, time.time())


def test_collect_sources_notes_a_live_block_and_continues():
    def fetch(name, session, instruments):
        if name == "bonbast":
            raise mod.SourceBlocked("challenge")
        return {"source": name, "rates": [{"code": "usd"}], "fetchedAt": iso(1)}
    out = mod.collect_sources(None, INSTRUMENTS, ["bonbast", "hansha"], fetch=fetch)
    assert [s["source"] for s in out] == ["hansha"]
    assert live_guard.is_quiet(mod._LIVE_STATE, time.time())
    assert mod._LIVE_RUN == {"outcome": "blocked", "kind": "challenge"}


# --- main harness

def run_main(monkeypatch, tmp_path, collect, args=(), min_direct=1):
    calls = {"collect": [], "converter": 0, "fill": []}

    def fake_collect(session, instruments, order):
        calls["collect"].append(list(order))
        return collect(order)

    def fake_converter(session, rates, instruments):
        calls["converter"] += 1
        return []

    def fake_fill(session, daily, dates, pace, fetcher=None):
        calls["fill"].append(list(dates))
        return 0

    monkeypatch.setattr(mod, "collect_sources", fake_collect)
    monkeypatch.setattr(mod, "fetch_computed_rates", fake_converter)
    monkeypatch.setattr(mod, "fill_days", fake_fill)
    monkeypatch.setattr(mod, "recent_missing_dates", lambda daily, days: ["2026-11-01"])
    monkeypatch.setattr(mod, "backfill_dates", lambda daily, n: ["2026-10-01"])
    monkeypatch.setattr(mod, "MIN_DIRECT", min_direct)
    for name in ("SEALER", "PLAIN_ALSO", "_DIST_ROOT"):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    for key in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "GHEYMAT_PLAIN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mod.sys, "argv", ["gheymat_snapshot.py", "--out", str(tmp_path / "out"), *args])
    return calls


def quiet_state_file(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    state = live_guard.record_block(live_guard.new_state(), time.time(), "status", None)
    assert live_guard.save_state(str(path), state)
    monkeypatch.setenv("GHEYMAT_LIVE_STATE", str(path))
    return path


def both(order):
    by = {"hansha": mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS), "bonbast": bonbast_snapshot()}
    return [by[n] for n in order]


# --- (iv) quiet

def test_quiet_skips_live_converter_and_archive(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GHEYMAT_ORDER", "live-first")
    quiet_state_file(tmp_path, monkeypatch)
    calls = run_main(monkeypatch, tmp_path, both, args=("--history", "--backfill", "5"))
    assert mod.main() == 0
    assert calls["collect"] == [["hansha"]]
    assert calls["converter"] == 0
    assert calls["fill"] == [[]]
    assert capsys.readouterr().out.count("live: quiet") == 1


def test_quiet_failover_when_primary_alone_is_short(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GHEYMAT_ORDER", "live-first")
    quiet_state_file(tmp_path, monkeypatch)
    calls = run_main(monkeypatch, tmp_path, lambda order: [] if order == ["hansha"] else both(order))
    assert mod.main() == 0
    assert calls["collect"] == [["hansha"], ["bonbast"]]
    assert calls["converter"] == 0
    out = capsys.readouterr().out
    assert out.count("live: ") == 1 and "live: ok fp=" in out


def test_not_quiet_default_order_and_converter(monkeypatch, tmp_path, capsys):
    calls = run_main(monkeypatch, tmp_path, both)
    assert mod.main() == 0
    assert calls["collect"] == [["hansha", "bonbast"]] and calls["converter"] == 1
    assert capsys.readouterr().out.count("live: ok fp=") == 1


def test_default_mode_ignores_a_persisted_quiet_state(monkeypatch, tmp_path, capsys):
    quiet_state_file(tmp_path, monkeypatch)
    assert mod.plan_sources(NOW, mod.live_guard.load_state(str(tmp_path / "state.json"), NOW)) == ["hansha", "bonbast"]
    calls = run_main(monkeypatch, tmp_path, both, args=("--history", "--backfill", "5"))
    assert mod.main() == 0
    assert calls["collect"] == [["hansha", "bonbast"]]
    assert calls["converter"] == 1
    assert calls["fill"] == [["2026-11-01", "2026-10-01"]]
    assert "live: quiet" not in capsys.readouterr().out


def test_default_mode_block_is_just_a_skipped_source(monkeypatch, tmp_path, capsys):
    quiet_state_file(tmp_path, monkeypatch)

    def only_primary(order):
        mod._note_block("status", None)
        return [mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)]
    calls = run_main(monkeypatch, tmp_path, only_primary)
    assert mod.main() == 0
    assert calls["collect"] == [["hansha", "bonbast"]] and calls["converter"] == 1


def test_default_mode_prints_divergence_count_to_stderr_only(monkeypatch, tmp_path, capsys):
    run_main(monkeypatch, tmp_path, both)
    assert mod.main() == 0
    cap = capsys.readouterr()
    assert "live: 0 codes 3% apart" in cap.err
    assert "codes" not in cap.out


# --- (v) guards

def snap(source, sells, mark=None):
    rates = [{"code": c, "buy": s - 10, "sell": s, "price": None} for c, s in sells.items()]
    return {"source": source, "rates": rates, "fetchedAt": iso(1), "sourceModified": mark}


BASE_SELLS = {c: 100000 + i * 1000 for i, c in enumerate(["usd", "eur", "gbp", "chf", "cad", "aud", "jpy"])}


def scaled(factor_by_code):
    return {c: round(v * factor_by_code.get(c, 1.0)) for c, v in BASE_SELLS.items()}


def test_divergence_five_codes_drops_live():
    primary = snap("hansha", BASE_SELLS)
    live = snap("bonbast", scaled({c: 1.04 for c in list(BASE_SELLS)[:5]}))
    kept, replaced = mod.check_divergence(live, primary)
    assert kept is None and replaced == 0
    results, _ = mod.apply_live_first_guards([live, primary], NOW)
    assert [s["source"] for s in results] == ["hansha"]
    assert mod._LIVE_RUN == {"outcome": "blocked", "kind": "diverge"}
    assert live_guard.is_quiet(mod._LIVE_STATE, time.time())


def test_divergence_one_big_code_takes_primary_row(capsys):
    primary = snap("hansha", BASE_SELLS)
    live = snap("bonbast", scaled({"gbp": 1.06}))
    results, replaced = mod.apply_live_first_guards([live, primary], NOW)
    assert replaced == 1
    assert "gbp" not in {r["code"] for r in results[0]["rates"]}
    assert len(results[0]["rates"]) == len(BASE_SELLS) - 1
    assert "gbp" not in capsys.readouterr().err


def test_small_differences_keep_live_untouched():
    primary = snap("hansha", BASE_SELLS)
    live = snap("bonbast", scaled({c: 1.02 for c in BASE_SELLS}))
    results, replaced = mod.apply_live_first_guards([live, primary], NOW)
    assert replaced == 0 and results[0] is live


def test_frozen_desk_drops_live():
    live = snap("bonbast", BASE_SELLS)
    results = None
    for step in range(4):
        moved = {c: v + step for c, v in BASE_SELLS.items()}  # core primary values change, live does not
        results, _ = mod.apply_live_first_guards([live, snap("hansha", moved)], NOW + step * 700)
    assert [s["source"] for s in results] == ["hansha"]
    assert mod._LIVE_RUN["kind"] == "frozen"


def test_primary_only_codes_ticking_do_not_freeze_the_desk():
    live = snap("bonbast", BASE_SELLS)
    for step in range(4):
        primary = snap("hansha", {**BASE_SELLS, **{c: 500 + step for c in HANSHA_ONLY}}, f"stamp-{step}")
        results, _ = mod.apply_live_first_guards([live, primary], NOW + step * 420, INSTRUMENTS)
        assert [s["source"] for s in results] == ["bonbast", "hansha"]
    assert mod._LIVE_RUN["kind"] is None


def test_frozen_check_receives_live_fingerprint_and_core_primary_mark(monkeypatch):
    seen = []

    def fake(state, fp, mark, now):
        seen.append((fp, mark))
        return False, state
    monkeypatch.setattr(mod.live_guard, "frozen_check", fake)
    live, primary = snap("bonbast", BASE_SELLS), snap("hansha", BASE_SELLS, "mark-1")
    mod.apply_live_first_guards([live, primary], NOW)
    primary_rows = snap("hansha", {**BASE_SELLS, "eth": 7})["rates"]
    mod.apply_live_first_guards([live, dict(primary, rates=primary_rows)], NOW, INSTRUMENTS)
    assert seen[0] == (mod.rates_fingerprint(live["rates"]), mod.rates_fingerprint(primary["rates"]))
    assert seen[1] == seen[0]  # an extra primary-only row leaves the mark unchanged


def test_freshness_excludes_primary_only_codes_in_live_first_only():
    rows = hansha_rows()
    old = iso(20)
    for r in rows:
        if isinstance(r, dict) and r["ab"] in HANSHA_ONLY:
            r["ps"][0]["ts"] = old
    results = [bonbast_snapshot(), mod.build_hansha_snapshot(rows, INSTRUMENTS)]
    assert HANSHA_ONLY & {r["code"] for r in results[1]["rates"]}
    default, _, _ = mod.combine_sources(results, INSTRUMENTS)
    first, _, _ = mod.combine_sources(results, INSTRUMENTS, live_first=True)
    assert default["fetchedAt"] == old
    assert first["fetchedAt"] > old


def test_freshness_falls_back_when_no_core_rows():
    only = {"source": "hansha", "fetchedAt": iso(3), "sourceModified": iso(3),
            "rates": [r for r in mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS)["rates"]
                      if r["code"] in HANSHA_ONLY]}
    out, _, _ = mod.combine_sources([only], INSTRUMENTS, live_first=True)
    assert out["fetchedAt"] == only["fetchedAt"]


# --- (vi) / (vii) one line, before the exit-2 check, state saved

def test_live_line_once_before_exit_2_and_state_saved(monkeypatch, tmp_path, capsys):
    path = tmp_path / "state.json"
    monkeypatch.setenv("GHEYMAT_LIVE_STATE", str(path))
    monkeypatch.setattr(mod.sys, "stderr", sys.stdout)  # one stream, so order is observable

    def blocked(session):
        raise mod.SourceBlocked("challenge")

    def gone(session):
        raise mod.SourceError("down")

    monkeypatch.setattr(mod, "fetch_raw", blocked)
    monkeypatch.setattr(mod, "fetch_hansha", gone)
    monkeypatch.setattr(mod, "SEALER", None)
    monkeypatch.setattr(mod.sys, "argv", ["gheymat_snapshot.py", "--out", str(tmp_path / "out")])
    assert mod.main() == 2
    out = capsys.readouterr().out
    assert out.count("live: ") == 1 and "live: blocked challenge" in out
    assert out.index("live: blocked") < out.index("refusing to publish")
    saved = live_guard.load_state(str(path), time.time())
    assert live_guard.is_quiet(saved, time.time())


def test_unreachable_live_source_prints_failed(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(mod, "fetch_raw", lambda s: (_ for _ in ()).throw(requests.ConnectionError("x")))
    monkeypatch.setattr(mod, "fetch_hansha", lambda s: (_ for _ in ()).throw(mod.SourceError("down")))
    monkeypatch.setattr(mod.sys, "argv", ["gheymat_snapshot.py", "--out", str(tmp_path / "out")])
    assert mod.main() == 2
    assert capsys.readouterr().out.count("live: failed") == 1


# --- (viii) intraday density

def _points(out, code):
    return json.loads((out / "v1" / "intraday" / code).read_text(encoding="utf-8"))["points"]


def _intraday_snap(ts):
    return {"fetchedAt": ts, "rates": [{"code": "usd", "buy": 1, "sell": 2, "price": None, "computed": False}]}


def test_intraday_density_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "SEALER", None)
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)

    def stamp(seconds):
        return (t0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert mod.append_intraday(tmp_path, _intraday_snap(stamp(0)), None, stamp(0)) == 1
    assert mod.append_intraday(tmp_path, _intraday_snap(stamp(60)), None, stamp(60)) == 0  # too soon
    assert mod.append_intraday(tmp_path, _intraday_snap(stamp(149)), None, stamp(149)) == 0
    assert mod.append_intraday(tmp_path, _intraday_snap(stamp(150)), None, stamp(150)) == 1
    assert [p["ts"] for p in _points(tmp_path, "usd")] == [stamp(0), stamp(150)]
    # without a live stamp (a row's own observation) nothing changes
    assert mod.append_intraday(tmp_path, _intraday_snap(stamp(160)), None, None) == 1
    assert mod.append_intraday(tmp_path, _intraday_snap(stamp(170)), {"usd": stamp(170)}, stamp(999)) == 1


def test_default_mode_keeps_a_point_per_build_for_a_live_filled_row(monkeypatch, tmp_path):
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=10)
    stamps = iter([t0, t0 + timedelta(seconds=45)])
    current = {}

    def collect(order):
        stamp = next(stamps).strftime("%Y-%m-%dT%H:%M:%SZ")
        current["stamp"] = stamp
        live = dict(bonbast_snapshot(), fetchedAt=stamp)
        return [mod.build_hansha_snapshot(hansha_rows(), INSTRUMENTS), live]

    run_main(monkeypatch, tmp_path, collect)
    assert mod.main() == 0
    assert mod.main() == 0
    assert len(_points(tmp_path / "out", "ounce")) == 2
