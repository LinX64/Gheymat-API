import base64
import importlib.util
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("gheymat_ai", TOOLS / "gheymat_ai.py")
ai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai)
FSPEC = importlib.util.spec_from_file_location("test_gheymat_forecast", pathlib.Path(__file__).resolve().parent / "test_gheymat_forecast.py")
tf = importlib.util.module_from_spec(FSPEC)
FSPEC.loader.exec_module(tf)

NOW = datetime(2026, 11, 9, 2, 30, tzinfo=timezone.utc)


def daily_from(points_by_code):
    return {"start": "2012-10-09", "codes": {c: {p["date"]: [None, p["price"]] for p in pts}
                                             for c, pts in points_by_code.items()}}


class Store:
    def __init__(self):
        self.docs = {}
        self.writes = []

    def write(self, logical, obj):
        self.docs[logical] = json.loads(json.dumps(obj))
        self.writes.append(logical)

    def load(self, logical):
        return self.docs.get(logical)


def test_publishes_passing_codes_and_lists_them_in_the_brief():
    store = Store()
    daily = daily_from({"usd": tf.walk(seed=7), "gram": tf.walk(years=1)})
    summary = ai.publish(daily, store.write, store.load, NOW)
    assert summary["published"] == ["usd"] and summary["withheld"] == {"gram": "history"}
    assert "v1/ai/forecast/usd" in store.docs and "v1/ai/forecast/gram" not in store.docs
    brief = store.docs["v1/ai/brief"]
    assert brief["forecastCodes"] == ["usd"]
    assert brief["cards"] == [{"kind": "forecast", "code": "usd"}]
    assert brief["en"] and brief["fa"] and "1" not in brief["fa"]
    assert store.docs["v1/ai/forecast/usd"]["generatedAt"] == "2026-11-09T02:30:00Z"


def test_unchanged_close_reseals_the_previous_document_unchanged():
    store = Store()
    daily = daily_from({"usd": tf.walk(seed=7)})
    ai.publish(daily, store.write, store.load, NOW)
    first = store.docs["v1/ai/forecast/usd"]
    first_brief = store.docs["v1/ai/brief"]
    store.writes.clear()
    summary = ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6))
    assert summary["resealed"] == 1 and summary["rebuilt"] == 0
    assert "v1/ai/forecast/usd" in store.writes and "v1/ai/brief" in store.writes
    assert store.docs["v1/ai/forecast/usd"] == first
    assert store.docs["v1/ai/brief"] == first_brief


def test_new_close_rebuilds_the_forecast():
    store = Store()
    pts = tf.walk(seed=7)
    ai.publish(daily_from({"usd": pts[:-1]}), store.write, store.load, NOW - timedelta(days=1))
    summary = ai.publish(daily_from({"usd": pts}), store.write, store.load, NOW)
    assert summary["rebuilt"] == 1
    assert store.docs["v1/ai/forecast/usd"]["basis"]["date"] == pts[-1]["date"]


def test_stale_close_is_not_resealed_forever():
    store = Store()
    daily = daily_from({"usd": tf.walk(seed=7)})
    ai.publish(daily, store.write, store.load, NOW)
    summary = ai.publish(daily, store.write, store.load, NOW + timedelta(days=5))
    assert summary["published"] == [] and summary["withheld"]["usd"] in ("basis-stale", "recent-gap")
    assert store.docs["v1/ai/brief"]["forecastCodes"] == []


def test_budget_stops_work_and_records_it():
    store = Store()
    ticks = iter([0.0, 0.0, 999.0, 999.0, 999.0])
    daily = daily_from({"aaa": tf.walk(seed=7), "bbb": tf.walk(seed=11)})
    summary = ai.publish(daily, store.write, store.load, NOW, budget_seconds=1.0, clock=lambda: next(ticks))
    assert summary["published"] == ["aaa"] and summary["withheld"] == {"bbb": "budget"}


def test_run_step_never_raises(capsys):
    def boom(*_):
        raise RuntimeError("disk full")
    assert ai.run_step(daily_from({"usd": tf.walk(seed=7)}), boom, lambda _: None, NOW) is None
    assert "prices unaffected" in capsys.readouterr().out


def test_tehran_day_rolls_over_at_2030_utc():
    assert ai.tehran_today(datetime(2026, 11, 8, 20, 29, tzinfo=timezone.utc)).isoformat() == "2026-11-08"
    assert ai.tehran_today(datetime(2026, 11, 8, 20, 31, tzinfo=timezone.utc)).isoformat() == "2026-11-09"


def test_default_today_uses_the_tehran_trading_day():
    assert ai.default_today(datetime(2026, 11, 8, 20, 29, tzinfo=timezone.utc)).isoformat() == "2026-11-08"
    assert ai.default_today(datetime(2026, 11, 8, 20, 31, tzinfo=timezone.utc)).isoformat() == "2026-11-09"


def test_run_step_passes_refresh_news_through(monkeypatch):
    seen = []
    monkeypatch.setattr(ai.gheymat_news, "publish", lambda *a, **k: seen.append(k.get("refresh")) or None)
    store = Store()
    ai.run_step(daily_from({}), store.write, store.load, NOW, log=lambda *_: None, env={}, refresh_news=False)
    ai.run_step(daily_from({}), store.write, store.load, NOW, log=lambda *_: None, env={})
    assert seen == [False, True]


def test_a_failing_step_logs_only_the_exception_type():
    def boom(*_args, **_kwargs):
        raise RuntimeError("request to https://example.invalid/secret-path failed")

    logs = []
    assert ai.run_step(daily_from({"usd": tf.walk(seed=7)}), boom, lambda _: None, NOW, log=logs.append, env={}) is None
    assert any("step failed" in line for line in logs)
    assert not any("http" in line or "secret-path" in line for line in logs)


class CsvHttp:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        rows = "\n".join(f"2026-10-{d:02d},{70 + d}" for d in range(1, 29))
        return type("R", (), {"status_code": 200, "text": "DATE,VALUE\n" + rows})()


def run_shadow(env, http, monkeypatch=None):
    store = Store()
    logs = []
    daily = daily_from({"usd": tf.walk(seed=7)})
    summary = ai.run_step(daily, store.write, store.load, NOW, log=logs.append, env=env, signals_http=http)
    return summary, store, logs


def test_shadow_flag_unset_never_touches_signals_http():
    http = CsvHttp()
    _, _, logs = run_shadow({}, http)
    assert http.calls == 0 and not any("signal shadow" in m for m in logs)


def test_shadow_flag_logs_one_line_and_changes_no_document():
    http = CsvHttp()
    off_summary, off_store, _ = run_shadow({}, http)
    on_summary, on_store, logs = run_shadow({"GHEYMAT_SIGNAL_SHADOW": "1"}, http)
    assert http.calls > 0
    assert len([m for m in logs if m.startswith("ai: signal shadow")]) == 1
    assert on_summary == off_summary
    assert on_store.writes == off_store.writes and on_store.docs == off_store.docs


def test_shadow_failure_logs_skip_and_keeps_summary(monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("secret detail")
    monkeypatch.setattr(ai.signal_shadow, "score", boom)
    _, _, logs = run_shadow({"GHEYMAT_SIGNAL_SHADOW": "1"}, CsvHttp())
    assert "ai: signal shadow skipped: ValueError" in logs
    assert not any("secret detail" in m for m in logs)
    assert any(m.startswith("ai: 1 forecasts") for m in logs)


ARCHIVE_FILE = pathlib.Path("forecast-log.bin")
MASTER = bytes(range(32))
KEY_B64 = base64.b64encode(MASTER).decode()


@pytest.fixture(autouse=True)
def key_env(monkeypatch):
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", base64.b64encode(MASTER).decode())
    monkeypatch.setattr(ai.forecast_track, "_warned", False)


def stub_points(end, start=date(2026, 11, 1)):
    out = []
    for i in range((end - start).days + 1):
        out.append({"date": (start + timedelta(days=i)).isoformat(), "price": float(100 + i)})
    return out


def stub_build(low_factor=0.95, high_factor=1.05, withhold=()):
    def build(code, points, today, generated_at, history_close=None, signal_ctx=None):
        if code in withhold:
            return None, "history"
        last = points[-1]
        basis = date.fromisoformat(last["date"])
        price = last["price"]
        return {"code": code, "generatedAt": generated_at, "basis": {"date": last["date"], "price": price},
                "horizonDays": 7, "target": (basis + timedelta(days=7)).isoformat(),
                "likely": round(price, 2), "low": round(price * low_factor, 2), "high": round(price * high_factor, 2),
                "method": "stub-method", "track": [], "signals": []}, None
    return build


def archive_records(root):
    ft = ai.forecast_track
    return ft._decrypt(ft._derive(MASTER), (root / ARCHIVE_FILE).read_bytes())


def published_entry(day):
    target = (date.fromisoformat(day) + timedelta(days=7)).isoformat()
    return {"basisDate": day, "target": target, "likely": 100.0, "low": 90.0, "high": 110.0,
            "actual": 101.0, "hit": True}


def test_a_target_close_resolves_into_the_published_track(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    store = Store()
    first = daily_from({"usd": stub_points(date(2026, 11, 8))})
    ai.publish(first, store.write, store.load, NOW, archive_root=tmp_path, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["track"] == []
    assert archive_records(tmp_path)[0]["codes"]["usd"]["actual"] is None
    second = daily_from({"usd": stub_points(date(2026, 11, 16))})
    ai.publish(second, store.write, store.load, NOW + timedelta(days=7), archive_root=tmp_path, log=lambda *_: None)
    doc = store.docs["v1/ai/forecast/usd"]
    assert doc["basis"]["date"] == "2026-11-16"
    assert doc["track"] == [{"basisDate": "2026-11-08", "target": "2026-11-15", "likely": 107.0, "low": 101.65,
                             "high": 112.35, "actual": 114.0, "hit": False}]
    saved = {r["date"]: r for r in archive_records(tmp_path)}
    assert saved["2026-11-08"]["codes"]["usd"]["actualDate"] == "2026-11-15"
    assert saved["2026-11-16"]["codes"]["usd"]["actual"] is None


def test_restated_history_leaves_the_entry_and_the_published_track_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    store = Store()
    quiet = lambda *_: None
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW,
               archive_root=tmp_path, log=quiet)
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 16))}), store.write, store.load,
               NOW + timedelta(days=7), archive_root=tmp_path, log=quiet)
    track = store.docs["v1/ai/forecast/usd"]["track"]
    entry_before = archive_records(tmp_path)[0]
    restated = stub_points(date(2026, 11, 17))
    for p in restated:
        if p["date"] == "2026-11-15":
            p["price"] = 108.0
    ai.publish(daily_from({"usd": restated}), store.write, store.load, NOW + timedelta(days=8),
               archive_root=tmp_path, log=quiet)
    assert store.docs["v1/ai/forecast/usd"]["basis"]["date"] == "2026-11-17"
    assert store.docs["v1/ai/forecast/usd"]["track"] == track
    assert archive_records(tmp_path)[0] == entry_before


def test_same_basis_rebuild_keeps_the_first_published_values_and_skips_the_write(tmp_path, monkeypatch):
    store = Store()
    daily = daily_from({"usd": stub_points(date(2026, 11, 8))})
    quiet = lambda *_: None
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    ai.publish(daily, store.write, store.load, NOW, archive_root=tmp_path, log=quiet)
    first = archive_records(tmp_path)
    calls = []
    real = ai.forecast_track._write_atomic
    monkeypatch.setattr(ai.forecast_track, "_write_atomic", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build(0.5, 2.0))
    summary = ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6), archive_root=tmp_path, log=quiet)
    assert summary["rebuilt"] == 1
    assert store.docs["v1/ai/forecast/usd"]["low"] == 53.5
    assert calls == [] and archive_records(tmp_path) == first


def test_archive_is_written_once_per_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    calls = []
    real = ai.forecast_track._write_atomic
    monkeypatch.setattr(ai.forecast_track, "_write_atomic", lambda *a, **k: calls.append(1) or real(*a, **k))
    store = Store()
    pts = stub_points(date(2026, 11, 8))
    ai.publish(daily_from({"aaa": pts, "bbb": pts, "ccc": pts}), store.write, store.load, NOW,
               archive_root=tmp_path, log=lambda *_: None)
    assert len(calls) == 1
    assert sorted(archive_records(tmp_path)[0]["codes"]) == ["aaa", "bbb", "ccc"]


def test_withheld_code_logs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build(withhold=("bad",)))
    store = Store()
    pts = stub_points(date(2026, 11, 8))
    summary = ai.publish(daily_from({"bad": pts}), store.write, store.load, NOW, archive_root=tmp_path,
                         log=lambda *_: None)
    assert summary["withheld"] == {"bad": "history"}
    assert not (tmp_path / ARCHIVE_FILE).exists()
    ai.publish(daily_from({"bad": pts, "good": pts}), store.write, store.load, NOW, archive_root=tmp_path,
               log=lambda *_: None)
    assert list(archive_records(tmp_path)[0]["codes"]) == ["good"]


def test_without_an_archive_root_the_previous_track_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    store = Store()
    store.docs["v1/ai/forecast/usd"] = {"method": "old", "basis": {"date": "2026-11-01", "price": 100.0},
                                        "track": [published_entry("2026-10-25")]}
    logs = []
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW, log=logs.append)
    assert store.docs["v1/ai/forecast/usd"]["track"] == [published_entry("2026-10-25")]
    assert logs == []
    assert not (tmp_path / "archive").exists()


def test_corrupt_archive_never_shrinks_the_published_track(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    (tmp_path / ARCHIVE_FILE).write_bytes(b"garbage")
    store = Store()
    previous = [published_entry("2026-11-01"), published_entry("2026-10-25")]
    store.docs["v1/ai/forecast/usd"] = {"method": "old", "basis": {"date": "2026-11-01", "price": 100.0},
                                        "track": previous}
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW,
               archive_root=tmp_path, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["track"] == previous


def test_a_track_failure_still_publishes_the_forecast(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())

    def boom(*_args):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(ai.forecast_track, "resolve_pending", boom)
    store = Store()
    logs = []
    pts = stub_points(date(2026, 11, 8))
    summary = ai.publish(daily_from({"aaa": pts, "bbb": pts}), store.write, store.load, NOW, archive_root=tmp_path,
                         log=logs.append)
    assert summary["published"] == ["aaa", "bbb"] and summary["rebuilt"] == 2
    assert store.docs["v1/ai/forecast/aaa"]["likely"] == 107.0 and store.docs["v1/ai/forecast/aaa"]["track"] == []
    assert logs == ["ai: track skipped: RuntimeError"] * 2
    assert set(archive_records(tmp_path)[0]["codes"]) == {"aaa", "bbb"}


def test_run_step_keeps_the_log_out_of_the_published_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    monkeypatch.setattr(ai.gheymat_news, "publish", lambda *a, **k: None)
    store = Store()
    state = tmp_path / "state"
    out = tmp_path / "out"
    ai.run_step(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW,
                log=lambda *_: None, env={"GHEYMAT_STATE_DIR": str(state), "GHEYMAT_PAYLOAD_KEY": KEY_B64}, archive_root=out)
    assert (state / ARCHIVE_FILE).exists()
    assert not (out / ARCHIVE_FILE).exists()


def test_run_step_threads_the_archive_root_and_log_into_the_track(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    monkeypatch.setattr(ai.gheymat_news, "publish", lambda *a, **k: None)
    store = Store()
    logs = []
    ai.run_step(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW, log=logs.append,
                env={"GHEYMAT_STATE_DIR": str(tmp_path), "GHEYMAT_PAYLOAD_KEY": KEY_B64}, archive_root=tmp_path / "out")
    assert archive_records(tmp_path)[0]["codes"]["usd"]["target"] == "2026-11-15"


def seed_forecast(store, monkeypatch, basis_end=date(2026, 11, 8), **build_kwargs):
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build(**build_kwargs))
    monkeypatch.setattr(ai.gheymat_blend, "expected_methods", lambda ctx: {"stub-method"})
    daily = daily_from({"usd": stub_points(basis_end)})
    ai.publish(daily, store.write, store.load, NOW, log=lambda *_: None)
    return daily


def test_rebuild_publishes_confidence_from_live_price(monkeypatch):
    store = Store()
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW,
               live_prices={"usd": 150.0}, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["confidence"] == {"level": "low", "reasons": ["band-broken"]}


def test_rebuild_without_live_prices_is_normal(monkeypatch):
    store = Store()
    seed_forecast(store, monkeypatch)
    assert store.docs["v1/ai/forecast/usd"]["confidence"] == {"level": "normal", "reasons": []}


def test_reuse_changes_only_confidence(monkeypatch):
    store = Store()
    daily = seed_forecast(store, monkeypatch)
    before = store.docs["v1/ai/forecast/usd"]
    summary = ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6),
                         live_prices={"usd": 150.0}, log=lambda *_: None)
    after = store.docs["v1/ai/forecast/usd"]
    assert summary["resealed"] == 1 and summary["rebuilt"] == 0
    assert after["generatedAt"] == before["generatedAt"]
    assert after["confidence"] == {"level": "low", "reasons": ["band-broken"]}
    assert {k: v for k, v in after.items() if k != "confidence"} == {k: v for k, v in before.items() if k != "confidence"}


def test_reuse_with_unchanged_confidence_republishes_identical_doc(monkeypatch):
    store = Store()
    daily = seed_forecast(store, monkeypatch)
    before = store.docs["v1/ai/forecast/usd"]
    ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6), live_prices={"usd": 107.0}, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"] == before


def test_reuse_keeps_sticky_reason_after_price_returns(monkeypatch):
    store = Store()
    daily = seed_forecast(store, monkeypatch)
    ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6), live_prices={"usd": 150.0}, log=lambda *_: None)
    ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=12), live_prices={"usd": 107.0}, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["confidence"]["reasons"] == ["band-broken"]
    ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=18), log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["confidence"]["reasons"] == ["band-broken"]


def test_new_basis_starts_clean(monkeypatch):
    store = Store()
    seed_forecast(store, monkeypatch)
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW + timedelta(minutes=6),
               live_prices={"usd": 150.0}, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["confidence"]["reasons"] == ["band-broken"]
    ai.publish(daily_from({"usd": stub_points(date(2026, 11, 9))}), store.write, store.load, NOW + timedelta(days=1),
               live_prices={"usd": 110.0}, log=lambda *_: None)
    assert store.docs["v1/ai/forecast/usd"]["confidence"] == {"level": "normal", "reasons": []}


def test_previous_document_without_confidence_gains_it_without_a_rebuild(monkeypatch):
    store = Store()
    daily = seed_forecast(store, monkeypatch)
    legacy = dict(store.docs["v1/ai/forecast/usd"])
    del legacy["confidence"]
    store.docs["v1/ai/forecast/usd"] = legacy
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build(0.5, 2.0))
    summary = ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6), log=lambda *_: None)
    after = store.docs["v1/ai/forecast/usd"]
    assert summary["resealed"] == 1 and summary["rebuilt"] == 0
    assert after["confidence"] == {"level": "normal", "reasons": []}
    assert after["low"] == legacy["low"] and after["generatedAt"] == legacy["generatedAt"]


def test_confidence_failure_still_publishes(monkeypatch):
    store = Store()
    logs = []
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    monkeypatch.setattr(ai.gheymat_blend, "expected_methods", lambda ctx: {"stub-method"})
    monkeypatch.setattr(ai.forecast_confidence, "build_confidence", lambda *a, **k: 1 / 0)
    daily = daily_from({"usd": stub_points(date(2026, 11, 8))})
    ai.publish(daily, store.write, store.load, NOW, live_prices={"usd": 150.0}, log=logs.append)
    assert store.docs["v1/ai/forecast/usd"]["confidence"] == {"level": "normal", "reasons": []}
    assert "ai: confidence skipped: ZeroDivisionError" in logs
    before = dict(store.docs["v1/ai/forecast/usd"])
    summary = ai.publish(daily, store.write, store.load, NOW + timedelta(minutes=6), live_prices={"usd": 150.0}, log=logs.append)
    assert summary["resealed"] == 1 and store.docs["v1/ai/forecast/usd"] == before


def test_brief_and_summary_are_unchanged_by_confidence(monkeypatch):
    store = Store()
    monkeypatch.setattr(ai.fc, "build_forecast", stub_build())
    summary = ai.publish(daily_from({"usd": stub_points(date(2026, 11, 8))}), store.write, store.load, NOW,
                         live_prices={"usd": 150.0}, log=lambda *_: None)
    assert set(summary) == {"published", "rebuilt", "resealed", "withheld"}
    assert set(store.docs["v1/ai/brief"]) == {"generatedAt", "en", "fa", "cards", "forecastCodes"}


def test_run_step_passes_live_prices_through(monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "publish", lambda *a, **k: seen.append(k.get("live_prices")) or
                        {"published": [], "rebuilt": 0, "resealed": 0, "withheld": {}})
    monkeypatch.setattr(ai.gheymat_news, "publish", lambda *a, **k: None)
    ai.run_step({"codes": {}}, lambda *_: None, lambda *_: None, NOW, log=lambda *_: None, live_prices={"usd": 1.0})
    assert seen == [{"usd": 1.0}]
