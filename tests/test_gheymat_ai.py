import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

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
