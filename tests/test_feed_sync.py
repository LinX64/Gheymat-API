import base64
import json
import pathlib
import sys
import types

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

try:
    from r2_store import StoreError
except ImportError:
    class StoreError(Exception):
        def __init__(self, kind):
            super().__init__("store failure")
            self.kind = kind

    stub = types.ModuleType("r2_store")
    stub.StoreError = StoreError
    sys.modules["r2_store"] = stub

import feed_sync as fs
import gheymat_seal as gs
import verify_sealed as vs

MASTER = bytes(range(7, 39))
SIGNING = Ed25519PrivateKey.from_private_bytes(bytes(range(60, 92)))
PUBLIC = {gs.DEFAULT_KID: SIGNING.public_key()}
SEALER = gs.Sealer(MASTER, SIGNING)
CODE = sorted(vs.all_codes())[0]
START = 1_000_000


def make_error(kind):
    try:
        return StoreError(kind)
    except TypeError:
        error = StoreError("failure")
        error.kind = kind
        return error


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


class FakeStore:
    def __init__(self, clock=None, step=0):
        self.calls = []
        self.fail = {}
        self.raise_unexpected = False
        self.clock = clock
        self.step = step

    def put(self, key, body, content_type="application/json", cache_control="", timeout=(5, 30)):
        if self.clock is not None:
            self.clock.now += self.step
        self.calls.append((key, body, content_type, cache_control))
        if self.raise_unexpected:
            raise RuntimeError("secret host detail")
        kind = self.fail.get(key)
        if kind:
            raise make_error(kind)

    def keys(self):
        return [c[0] for c in self.calls]


def name(logical):
    return SEALER.opaque_path(logical)


def write(site, logical, obj, issued, versions=("v1",)):
    env = json.dumps(SEALER.seal(logical, obj, issued=issued), separators=(",", ":"))
    targets = []
    if logical == "health" or logical.startswith("v1/"):
        targets.append(site / name(logical))
    for v in versions:
        if logical.startswith(v + "/"):
            targets.append(site / v / name(logical))
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(env, encoding="utf-8")


def build(site, issued=START, tag=0):
    write(site, "v1/latest", {"rates": [tag]}, issued)
    write(site, "health", {"ok": True, "tag": tag}, issued)
    write(site, "v1/instruments", [tag], issued)
    write(site, f"v1/intraday/{CODE}", {"points": [tag]}, issued)
    write(site, f"v1/history/{CODE}", {"h": 1}, issued)
    write(site, f"v1/longhistory/{CODE}", {"lh": 1}, issued)
    write(site, f"v1/ai/forecast/{CODE}", {"f": 1}, issued)
    write(site, "v1/ai/news", {"n": 1}, issued)
    write(site, "v1/ai/brief", {"b": 1}, issued)
    write(site, f"v2/ai/forecast/{CODE}", {"f": 1}, issued, versions=("v2",))
    write(site, "v2/ai/news", {"n": 1}, issued, versions=("v2",))
    write(site, "v2/ai/brief", {"b": 1}, issued, versions=("v2",))


@pytest.fixture
def site(tmp_path):
    d = tmp_path / "site"
    build(d)
    (d / "v1" / "daily.json").write_text("{}", encoding="utf-8")
    (d / "archive").mkdir()
    (d / "archive" / "x.json").write_text("{}", encoding="utf-8")
    (d / "privacy.html").write_text("p", encoding="utf-8")
    (d / "_headers").write_text("h", encoding="utf-8")
    (d / "versions.json").write_text("{}", encoding="utf-8")
    (d / "d" / "deadbeef").write_text("orphan", encoding="utf-8")
    return d


def syncer(store, clock=None, logs=None, **kw):
    clock = clock or Clock()
    logs = logs if logs is not None else []
    return fs.FeedSync(store, MASTER, PUBLIC, clock=clock, log=logs.append, **kw), clock, logs


def test_whitelist_excludes_non_documents(site):
    s, _, _ = syncer(FakeStore())
    keys = {u.key for u in s.plan(site, True)}
    assert keys
    for key in keys:
        assert key.startswith(("d/", "v2/d/"))
    assert "d/deadbeef" not in keys
    assert not any("daily" in u.logical for u in s.plan(site, True))
    assert not any(k.startswith(("archive", "v1/")) or "html" in k or "headers" in k for k in keys)


def test_v1_dedups_to_root_key(site):
    s, _, _ = syncer(FakeStore())
    plan = s.plan(site, True)
    assert name("v1/latest") in {u.key for u in plan}
    assert f"v1/{name('v1/latest')}" not in {u.key for u in plan}
    assert len({u.key for u in plan}) == len(plan)


def test_v2_only_with_include_v2(site):
    on, _, _ = syncer(FakeStore(), include_v2=True)
    off, _, _ = syncer(FakeStore(), include_v2=False)
    v2_key = "v2/" + name("v2/ai/brief")
    assert v2_key in {u.key for u in on.plan(site, True)}
    assert not any(u.key.startswith("v2/") for u in off.plan(site, True))


def test_missing_file_skipped(site):
    (site / name("v1/ai/brief")).unlink()
    s, _, _ = syncer(FakeStore())
    result = s.sync(site, True)
    assert result.skipped >= 1
    assert name("v1/ai/brief") not in s._store.keys()


def test_tier_order_hot_first_sequential(site):
    store = FakeStore()
    s, _, _ = syncer(store, workers=1)
    result = s.sync(site, True)
    keys = store.keys()
    assert keys[:2] == [name("v1/latest"), name("health")]
    warm = {name("v1/instruments"), name(f"v1/intraday/{CODE}")}
    assert set(keys[2:4]) == warm
    assert result.hot_ok and result.uploaded == len(keys) == 12


def test_hot_deadline_stops_hot_puts(site):
    clock = Clock()
    store = FakeStore(clock, step=25)
    s, _, _ = syncer(store, clock=clock, hot_deadline=20.0)
    result = s.sync(site, True)
    assert store.keys()[0] == name("v1/latest")
    assert name("health") not in store.keys()
    assert result.hot_ok is False


def test_hot_ok_false_on_failing_latest(site):
    store = FakeStore()
    store.fail[name("v1/latest")] = "status"
    s, _, _ = syncer(store)
    result = s.sync(site, False)
    assert result.hot_ok is False
    assert result.keys_failed_kinds == {"status": 1}
    assert name("health") in store.keys()


def test_hot_ok_true_when_both_stored(site):
    s, _, _ = syncer(FakeStore())
    assert s.sync(site, False).hot_ok is True


def test_plaintext_skip_and_change(site):
    store = FakeStore()
    s, clock, _ = syncer(store)
    s.sync(site, True)
    store.calls.clear()
    clock.now += 60
    build(site, issued=clock.now)
    result = s.sync(site, True)
    assert store.keys() == [name("v1/latest"), name("health")]
    assert result.skipped >= 10
    store.calls.clear()
    clock.now += 60
    build(site, issued=clock.now, tag=1)
    s.sync(site, False)
    assert name("v1/instruments") in store.keys()


def test_instruments_age_threshold(site):
    store = FakeStore()
    s, clock, _ = syncer(store, instruments_max_age=3300)
    s.sync(site, True)
    store.calls.clear()
    clock.now += 3299
    build(site, issued=clock.now)
    s.sync(site, False)
    assert name("v1/instruments") not in store.keys()
    store.calls.clear()
    clock.now += 1
    build(site, issued=clock.now)
    s.sync(site, False)
    assert name("v1/instruments") in store.keys()


def test_cold_age_thresholds_include_history(site):
    store = FakeStore()
    s, clock, _ = syncer(store, slow_max_age=1500)
    s.sync(site, True)
    cold = [name("v1/ai/news"), name(f"v1/history/{CODE}"), name(f"v1/longhistory/{CODE}"),
            "v2/" + name("v2/ai/news")]
    clock.now += 1499
    build(site, issued=clock.now)
    store.calls.clear()
    s.sync(site, True)
    assert not set(cold) & set(store.keys())
    clock.now += 1
    build(site, issued=clock.now)
    store.calls.clear()
    s.sync(site, True)
    assert set(cold) <= set(store.keys())


def test_non_slow_build_refreshes_stale_cold_with_newer_issued(site):
    store = FakeStore()
    s, clock, _ = syncer(store, slow_max_age=1500)
    s.sync(site, True)
    clock.now += 1500
    store.calls.clear()
    s.sync(site, False)
    assert name("v1/ai/news") not in store.keys()
    build(site, issued=clock.now)
    s.sync(site, False)
    assert name("v1/ai/news") in store.keys()
    assert name(f"v1/history/{CODE}") in store.keys()


def test_failed_cold_put_retried_on_next_non_slow_build(site):
    store = FakeStore()
    store.fail[name("v1/ai/brief")] = "status"
    s, clock, _ = syncer(store)
    s.sync(site, True)
    store.fail.clear()
    store.calls.clear()
    clock.now += 300
    build(site, issued=clock.now)
    s.sync(site, False)
    assert store.keys().count(name("v1/ai/brief")) == 1
    assert name("v1/ai/news") not in store.keys()


def test_wall_clock_cap_with_hanging_store(site):
    clock = Clock()
    timeouts = []

    class Hanging(FakeStore):
        def put(self, key, body, content_type="", cache_control="", timeout=(5, 30)):
            timeouts.append(timeout)
            clock.now += 18
            super().put(key, body, content_type, cache_control, timeout)

    s, _, _ = syncer(Hanging(), clock=clock, hot_deadline=20, rest_deadline=100, workers=1)
    result = s.sync(site, True)
    assert clock.now - START <= 20 + 100 + 15
    assert result.over_budget is True
    assert all(1 <= t[1] <= 30 for t in timeouts)
    assert timeouts[0][1] == 20


def test_defaults_are_short():
    s, _, _ = syncer(FakeStore())
    assert s._instruments_max_age == 1500 and s._slow_max_age == 1500


def test_cold_changed_plaintext_uploaded_early(site):
    store = FakeStore()
    s, clock, _ = syncer(store)
    s.sync(site, True)
    clock.now += 10
    build(site, issued=clock.now)
    write(site, "v1/ai/news", {"n": 2}, clock.now)
    store.calls.clear()
    s.sync(site, True)
    assert name("v1/ai/news") in store.keys()
    assert name("v1/ai/brief") not in store.keys()


def test_intraday_spacing_and_first_upload(site):
    store = FakeStore()
    s, clock, _ = syncer(store, intraday_spacing=300)
    key = name(f"v1/intraday/{CODE}")
    s.sync(site, False)
    assert key in store.keys()
    store.calls.clear()
    clock.now += 100
    write(site, f"v1/intraday/{CODE}", {"points": [1, 2]}, clock.now)
    s.sync(site, False)
    assert key not in store.keys()
    clock.now += 200
    write(site, f"v1/intraday/{CODE}", {"points": [1, 2]}, clock.now)
    s.sync(site, False)
    assert key in store.keys()
    store.calls.clear()
    clock.now += 400
    write(site, f"v1/intraday/{CODE}", {"points": [1, 2]}, clock.now)
    s.sync(site, False)
    assert key not in store.keys()


def test_non_slow_lane_uploads_no_unchanged_cold(site):
    store = FakeStore()
    s, clock, _ = syncer(store)
    s.sync(site, True)
    store.calls.clear()
    clock.now += 60
    build(site, issued=clock.now)
    s.sync(site, False)
    assert set(store.keys()) == {name("v1/latest"), name("health")}


def test_oversized_and_unopenable_counted_failed(site):
    big = site / name(f"v1/history/{CODE}")
    big.write_bytes(b" " * (gs.MAX_ENVELOPE_BYTES + 1))
    (site / name("v1/ai/news")).write_text("not json", encoding="utf-8")
    other = json.loads((site / name("v1/ai/brief")).read_text())
    other["sig"] = base64.b64encode(bytes(64)).decode()
    (site / name("v1/ai/brief")).write_text(json.dumps(other), encoding="utf-8")
    store = FakeStore()
    s, _, _ = syncer(store)
    result = s.sync(site, True)
    assert result.failed == 3
    for logical in (f"v1/history/{CODE}", "v1/ai/news", "v1/ai/brief"):
        assert name(logical) not in store.keys()


def test_symlink_not_followed(site, tmp_path):
    target = site / name("v1/ai/brief")
    target.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    target.symlink_to(outside)
    store = FakeStore()
    s, _, _ = syncer(store)
    s.sync(site, True)
    assert name("v1/ai/brief") not in store.keys()


def test_put_headers(site):
    store = FakeStore()
    s, _, _ = syncer(store)
    s.sync(site, True)
    assert store.calls
    for _, _, content_type, cache_control in store.calls:
        assert content_type == "application/json"
        assert cache_control == "public, max-age=0, must-revalidate"


def test_failed_put_does_not_update_manifest(site):
    store = FakeStore()
    store.fail[name("v1/instruments")] = "timeout"
    s, clock, _ = syncer(store)
    result = s.sync(site, False)
    assert result.failed == 1 and result.keys_failed_kinds == {"timeout": 1}
    store.fail.clear()
    store.calls.clear()
    s.sync(site, False)
    assert name("v1/instruments") in store.keys()


def test_budget_guard_warmup_and_spacing(site):
    store = FakeStore()
    s, clock, logs = syncer(store, monthly_put_budget=10, intraday_spacing=300)
    s.sync(site, True)
    assert s.projected_monthly_puts() is None
    clock.now += 1000
    s.sync(site, False)
    assert s.projected_monthly_puts() is None
    assert not any("projected" in line for line in logs)
    clock.now += 1000
    s.sync(site, False)
    assert s.projected_monthly_puts() > 10
    assert s._spacing == 600
    for _ in range(4):
        clock.now += 2000
        s.sync(site, False)
    assert s._spacing == 1800
    assert [line for line in logs if "projected writes high" in line] == [
        "feed sync: projected writes high, intraday spacing 600 s"]


def test_guard_none_without_cold_sync(site):
    s, clock, _ = syncer(FakeStore())
    s.sync(site, False)
    clock.now += 5000
    s.sync(site, False)
    assert s.projected_monthly_puts() is None


def test_nothing_sensitive_in_logs_or_repr(site):
    store = FakeStore()
    store.raise_unexpected = True
    s, _, logs = syncer(store)
    result = s.sync(site, True)
    assert result.keys_failed_kinds == {"unknown": result.failed}
    text = "\n".join(logs) + repr(s) + repr(fs.Upload("k", b"b", "l", "hot")) + repr(result)
    assert "secret" not in text and name("v1/latest") not in text
    assert all(line.startswith("feed sync: uploaded") for line in logs)
    assert base64.b64encode(MASTER).decode() not in text


def test_sync_never_raises(tmp_path):
    s, _, logs = syncer(FakeStore())
    result = s.sync(tmp_path / "missing", True)
    assert result.hot_ok is False and result.uploaded == 0
    assert logs and logs[0].startswith("feed sync: uploaded 0")


def test_result_counts_and_rest_deadline(site):
    clock = Clock()
    store = FakeStore(clock, step=40)
    s, _, logs = syncer(store, clock=clock, hot_deadline=100, rest_deadline=100, workers=1)
    result = s.sync(site, True)
    assert result.over_budget is True
    assert result.uploaded == len(store.calls) and result.uploaded < 12
    assert logs == [f"feed sync: uploaded {result.uploaded}, skipped {result.skipped}, failed 0"]
