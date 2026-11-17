import base64
import json
import pathlib
import sys
import threading
import time
from datetime import datetime, timezone

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import lead_samples as ls

KEY = base64.b64encode(bytes(range(32))).decode()
OTHER = base64.b64encode(bytes(range(1, 33))).decode()
NOW = datetime(2026, 11, 9, 12, 0, 30, tzinfo=timezone.utc)
NOW_S = NOW.timestamp()


class Resp:
    def __init__(self, body, status=200, headers=None):
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status
        self.headers = headers or {}

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass


class Http:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        r = self.routes[url]
        if isinstance(r, Exception):
            raise r
        return r


def src(i="alpha", **kw):
    base = {"id": i, "url": f"https://{i}.example.invalid/q", "value_path": ["p"]}
    base.update(kw)
    return base


def env(*sources, key=KEY, state=None):
    e = {ls.ENV_SOURCES: json.dumps(list(sources))}
    if key:
        e[ls.ENV_KEY] = key
    if state:
        e[ls.ENV_STATE] = str(state)
    return e


def run(sources, routes, reference=None, now=NOW, key=KEY):
    logs = []
    out = ls.sample(env(*sources, key=key), now, log=logs.append, http=Http(routes), reference=reference)
    return out, logs


@pytest.fixture(autouse=True)
def fresh():
    ls._warned = False
    yield


def test_config_shapes():
    assert ls.load_config({}) is None
    assert ls.load_config({ls.ENV_SOURCES: ""}) is None
    assert ls.load_config({ls.ENV_SOURCES: "nope"}) is None
    assert ls.load_config({ls.ENV_SOURCES: "{}"}) is None
    assert ls.load_config({ls.ENV_SOURCES: "[]"}) is None
    bad = [src("a", url="http://x.example.invalid"), src("b", ts_path=["t"], ts_unit="s"), src("c", scale=0),
           src("d", value_path=[]), {"id": "_marker", "url": "https://x.example.invalid", "value_path": ["p"]}]
    assert ls.load_config(env(*bad)) is None
    good = ls.load_config(env(src("alpha"), src("bad", url="ftp://x"), src("beta", unknown=1)))
    assert [s["id"] for s in good] == ["alpha", "beta"]
    many = ls.load_config(env(*[src(f"s{i}") for i in range(9)]))
    assert len(many) == 6


def test_scale_ten_times_larger_feed():
    large = src("alpha", scale=0.1)
    plain = src("beta")
    out, _ = run([large, plain], {large["url"]: Resp({"p": 1_000_000}), plain["url"]: Resp({"p": 100_000})})
    by = {r["series"]: r["value"] for r in out}
    assert by["alpha"] == pytest.approx(100_000)
    assert by["beta"] == pytest.approx(100_000)


def test_factor_multiplies():
    s = src(scale=0.1, factor=2)
    out, _ = run([s], {s["url"]: Resp({"p": 500_000})})
    assert out[0]["value"] == pytest.approx(100_000)


def ts_src(unit="s", age=600, **kw):
    return src(ts_path=["ts"], ts_unit=unit, max_age_seconds=age, **kw)


def test_timestamp_rules():
    s = ts_src()
    ok, _ = run([s], {s["url"]: Resp({"p": 5, "ts": NOW_S - 100})})
    assert ok[0]["t"] == int(NOW_S - 100) and ok[0]["got"] == int(NOW_S)
    stale, _ = run([s], {s["url"]: Resp({"p": 5, "ts": NOW_S - 601})})
    assert stale == []
    future, _ = run([s], {s["url"]: Resp({"p": 5, "ts": NOW_S + 121})})
    assert future == []
    slack, _ = run([s], {s["url"]: Resp({"p": 5, "ts": NOW_S + 100})})
    assert len(slack) == 1
    for body in ({"p": 5}, {"p": 5, "ts": "garbage"}, {"p": 5, "ts": None}, {"p": 5, "ts": -1}):
        assert run([s], {s["url"]: Resp(body)})[0] == []


def test_timestamp_units():
    ms = ts_src("ms")
    out, _ = run([ms], {ms["url"]: Resp({"p": 5, "ts": int((NOW_S - 10) * 1000)})})
    assert out[0]["t"] == int(NOW_S - 10)
    iso = ts_src("iso")
    stamp = datetime.fromtimestamp(NOW_S - 10, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, _ = run([iso], {iso["url"]: Resp({"p": 5, "ts": stamp})})
    assert len(out) == 1
    assert run([iso], {iso["url"]: Resp({"p": 5, "ts": "2026-11-09T11:59:00"})})[0] == []


def test_no_timestamp_uses_fetch_minute():
    s = src()
    out, _ = run([s], {s["url"]: Resp({"p": 5})})
    assert out[0]["t"] == int(NOW_S // 60 * 60)


def test_reference_band_and_unchecked():
    s = src(check={"against": "ref_a", "min_ratio": 0.8, "max_ratio": 1.2})
    inside, _ = run([s], {s["url"]: Resp({"p": 100})}, reference={"ref_a": 100})
    assert len(inside) == 1 and "unchecked" not in inside[0]
    assert run([s], {s["url"]: Resp({"p": 130})}, reference={"ref_a": 100})[0] == []
    assert run([s], {s["url"]: Resp({"p": 70})}, reference={"ref_a": 100})[0] == []
    none, _ = run([s], {s["url"]: Resp({"p": 130})})
    assert none[0]["unchecked"] is True
    bad_ref, _ = run([s], {s["url"]: Resp({"p": 130})}, reference={"ref_a": 0})
    assert bad_ref[0]["unchecked"] is True
    other, _ = run([s], {s["url"]: Resp({"p": 130})}, reference={"ref_b": 100})
    assert other[0]["unchecked"] is True


def range_src(**kw):
    s = src(lo_path=["lo"], hi_path=["hi"], **kw)
    del s["value_path"]
    return s


def test_range_rules():
    s = range_src()
    out, _ = run([s], {s["url"]: Resp({"lo": 100, "hi": 102})})
    assert out[0]["value"] == pytest.approx(101)
    for body in ({"lo": 102, "hi": 100}, {"lo": 0, "hi": 10}, {"lo": -1, "hi": 10}, {"lo": 100, "hi": 110},
                 {"lo": "x", "hi": 10}, {"lo": 100}, {"lo": float("nan"), "hi": 10}):
        assert run([s], {s["url"]: Resp(json.dumps(body).encode())})[0] == [], body
    equal, _ = run([s], {s["url"]: Resp({"lo": 100, "hi": 100})})
    assert len(equal) == 1


def test_value_must_be_finite_positive():
    s = src()
    for raw in (b'{"p": NaN}', b'{"p": Infinity}', b'{"p": 0}', b'{"p": -4}', b'{"p": true}', b'{"p": null}',
                b'{"p": "abc"}', b'{"p": [1]}', b'[]', b'{}'):
        assert run([s], {s["url"]: Resp(raw)})[0] == [], raw
    nested = src(value_path=["d", 1, "v"])
    out, _ = run([nested], {nested["url"]: Resp({"d": [{"v": 1}, {"v": "42.5"}]})})
    assert out[0]["value"] == 42.5


def test_dedupe_by_series_and_t():
    s = src()
    t = src("beta")
    out, _ = run([s, dict(s), t], {s["url"]: Resp({"p": 5}), t["url"]: Resp({"p": 5})})
    assert sorted(r["series"] for r in out) == ["alpha", "beta"]


def test_response_too_large():
    s = src()
    big = b'{"p": 5, "x": "' + b"a" * (ls.MAX_BODY + 10) + b'"}'
    assert run([s], {s["url"]: Resp(big)})[0] == []
    assert run([s], {s["url"]: Resp({"p": 5}, headers={"Content-Length": str(ls.MAX_BODY + 1)})})[0] == []


def test_https_only_and_redirect_refused():
    assert ls.load_config(env(src(url="http://a.example.invalid/q"))) is None
    s = src()
    http = Http({s["url"]: Resp({"p": 5}, status=302, headers={"Location": "https://z.example.invalid"})})
    out = ls.sample(env(s), NOW, log=lambda m: None, http=http)
    assert out == []
    assert http.calls[0][1]["allow_redirects"] is False
    assert http.calls[0][1]["timeout"] <= 5
    assert run([s], {s["url"]: Resp({"p": 5}, status=500)})[0] == []


def test_failure_isolation_and_log_hygiene():
    a, b, c = src("alpha"), src("beta"), src("gamma")
    routes = {a["url"]: TimeoutError("https://secret.example.invalid/x 12345"), b["url"]: Resp({"p": 777.5}),
              c["url"]: Resp(b"not json")}
    out, logs = run([a, b, c], routes)
    assert [r["series"] for r in out] == ["beta"]
    text = "\n".join(logs)
    assert "1 of 3 series answered" in text
    for needle in ("example.invalid", "777", "12345", "alpha", "beta", "https"):
        assert needle not in text
    assert "TimeoutError" in text


def test_wall_clock_deadline(monkeypatch):
    monkeypatch.setattr(ls, "TOTAL_BUDGET", 0.4)
    a, b = src("alpha"), src("beta")
    gate = threading.Event()

    class Hang(Http):
        def get(self, url, **kw):
            if url == a["url"]:
                gate.wait(10)
            return super().get(url, **kw)

    http = Hang({a["url"]: Resp({"p": 5}), b["url"]: Resp({"p": 5})})
    logs = []
    started = time.monotonic()
    out = ls.sample(env(a, b), NOW, log=logs.append, http=http)
    elapsed = time.monotonic() - started
    gate.set()
    assert elapsed < 2
    assert [r["series"] for r in out] == ["beta"]
    assert "Deadline" in logs[0]


def test_no_key_logs_once():
    s = src()
    logs = []
    http = Http({s["url"]: Resp({"p": 5})})
    assert ls.sample(env(s, key=None), NOW, log=logs.append, http=http) == []
    assert ls.sample(env(s, key=None), NOW, log=logs.append, http=http) == []
    assert logs == ["lead: off (no key)"]
    assert http.calls == []
    assert ls.append("x", "f", [], None) == 0


def rows(n=3, base=1000, series="alpha", value=123456.75):
    return [{"series": series, "t": base + i, "got": base + i, "value": value + i} for i in range(n)]


def test_round_trip_and_ciphertext(tmp_path):
    key = ls.derive_key({ls.ENV_KEY: KEY})
    assert ls.append(tmp_path, "f.bin", rows(), key) == 3
    assert ls.append(tmp_path, "f.bin", rows(), key) == 0
    assert ls.append(tmp_path, "f.bin", rows(2, base=5000) + [{"series": "alpha", "t": 1, "value": -1}], key) == 2
    back = ls.read(tmp_path, "f.bin", key)
    assert len(back) == 5 and back[0]["value"] == 123456.75
    raw = (tmp_path / "f.bin").read_bytes()
    raw.decode("ascii")
    assert b"alpha" not in raw and b"123456" not in raw and b"series" not in raw
    assert b"alpha" not in base64.b64decode(raw.splitlines()[0])
    assert not list(tmp_path.glob("*.tmp"))
    unchecked = [{"series": "beta", "t": 9, "got": 9, "value": 5.0, "unchecked": True}]
    ls.append(tmp_path, "f.bin", unchecked, key)
    assert ls.summary(ls.read(tmp_path, "f.bin", key)) == {"series": 2, "total": 6, "unchecked": 1}


def test_fresh_nonce_each_write(tmp_path):
    key = ls.derive_key({ls.ENV_KEY: KEY})
    ls.append(tmp_path, "f.bin", rows(1), key)
    first = (tmp_path / "f.bin").read_text()
    ls.append(tmp_path, "f.bin", rows(1, base=9), key)
    lines = (tmp_path / "f.bin").read_text().splitlines()
    assert lines[0] != first.strip()


def test_wrong_key_backup_kept_never_overwritten(tmp_path):
    key = ls.derive_key({ls.ENV_KEY: KEY})
    other = ls.derive_key({ls.ENV_KEY: OTHER})
    ls.append(tmp_path, "f.bin", rows(), key)
    original = (tmp_path / "f.bin").read_bytes()
    assert ls.append(tmp_path, "f.bin", rows(2, base=77), other) == 0
    backup = tmp_path / "f.bin.unreadable"
    assert backup.read_bytes() == original
    assert (tmp_path / "f.bin").read_bytes() == original
    backup.write_bytes(b"sentinel")
    assert ls.append(tmp_path, "f.bin", rows(2, base=88), other) == 0
    assert backup.read_bytes() == b"sentinel"
    assert ls.read(tmp_path, "f.bin", other) == []
    assert len(ls.read(tmp_path, "f.bin", key)) == 3


def test_corrupt_file_kept(tmp_path):
    key = ls.derive_key({ls.ENV_KEY: KEY})
    (tmp_path / "f.bin").write_bytes(b"\xff\xfe garbage")
    assert ls.append(tmp_path, "f.bin", rows(), key) == 0
    assert (tmp_path / "f.bin.unreadable").read_bytes() == b"\xff\xfe garbage"
    assert (tmp_path / "f.bin").read_bytes() == b"\xff\xfe garbage"


def test_cap_drops_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "MAX_SAMPLES", 5)
    key = ls.derive_key({ls.ENV_KEY: KEY})
    ls.append(tmp_path, "f.bin", rows(5), key)
    assert ls.append(tmp_path, "f.bin", rows(3, base=100), key) == 3
    back = ls.read(tmp_path, "f.bin", key)
    assert [r["t"] for r in back] == [1003, 1004, 100, 101, 102]


def test_cap_and_nothing_added(tmp_path, monkeypatch):
    key = ls.derive_key({ls.ENV_KEY: KEY})
    ls.append(tmp_path, "f.bin", rows(4), key)
    before = (tmp_path / "f.bin").read_bytes()
    monkeypatch.setattr(ls, "MAX_SAMPLES", 2)
    assert ls.append(tmp_path, "f.bin", rows(1, base=500), key) == 1
    assert len(ls.read(tmp_path, "f.bin", key)) == 2
    monkeypatch.setattr(ls, "MAX_SAMPLES", 20000)
    ls.append(tmp_path, "f.bin", rows(4, base=900), key)
    before = (tmp_path / "f.bin").read_bytes()
    assert ls.append(tmp_path, "f.bin", rows(4, base=900), key) == 0
    assert (tmp_path / "f.bin").read_bytes() == before


def test_day_run_throttle_marker_and_reference(tmp_path, monkeypatch):
    s = src(check={"against": "ref_a", "min_ratio": 0.5, "max_ratio": 2})
    e = env(s, state=tmp_path)
    logs = []
    http = Http({s["url"]: Resp({"p": 100})})
    monkeypatch.setattr(ls, "_default_http", lambda: http)
    ls.day_run(e, NOW, {"ref_a": 100.0}, logs.append)
    key = ls.derive_key(e)
    assert len(ls.read(tmp_path, ls.DAY_FILE, key)) == 1
    assert "unchecked" not in ls.read(tmp_path, ls.DAY_FILE, key)[0]
    raw = (tmp_path / ls.DAY_FILE).read_bytes()
    assert b"_marker" not in raw
    n = len(http.calls)
    later = datetime.fromtimestamp(NOW_S + 600, timezone.utc)
    ls.day_run(e, later, {"ref_a": 100.0}, logs.append)
    assert len(http.calls) == n
    after = datetime.fromtimestamp(NOW_S + 1801, timezone.utc)
    ls.day_run(e, after, None, logs.append)
    assert len(http.calls) == n + 1
    rows_ = ls.read(tmp_path, ls.DAY_FILE, key)
    assert len(rows_) == 2 and rows_[1]["unchecked"] is True
    text = "\n".join(logs)
    assert "example.invalid" not in text and "100" not in text


def test_day_run_marker_set_even_when_nothing_answers(tmp_path, monkeypatch):
    s = src()
    e = env(s, state=tmp_path)
    http = Http({s["url"]: Resp(b"junk")})
    monkeypatch.setattr(ls, "_default_http", lambda: http)
    ls.day_run(e, NOW, {}, lambda m: None)
    ls.day_run(e, NOW, {}, lambda m: None)
    assert len(http.calls) == 1


def test_day_run_swallows_everything(tmp_path, monkeypatch):
    s = src()
    e = env(s, state=tmp_path)

    def boom(*a, **k):
        raise RuntimeError("https://secret.example.invalid 999")

    monkeypatch.setattr(ls, "sample", boom)
    logs = []
    ls.day_run(e, NOW, {}, logs.append)
    assert logs == ["lead: skipped (RuntimeError)"]
    ls.day_run({}, NOW, {}, logs.append)
    ls.day_run(None, NOW, {}, logs.append)
    ls.day_run(e, NOW, {}, lambda m: 1 / 0)


def test_snapshot_does_not_use_sampler():
    text = (TOOLS / "gheymat_snapshot.py").read_text()
    assert "lead_samples" not in text and "day_run" not in text
