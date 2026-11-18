import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import live_notify as ln

ENV = {"LIVE_NOTIFY_SECRET": "s3cret-value"}
DAILY = {"codes": {"usd": {"2026-11-17": [100, 100]}}}


class Resp:
    def __init__(self, code=200):
        self.status_code = code


class Post:
    def __init__(self, code=200):
        self.code = code
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        return Resp(self.code)


def rows(n, sell=100.0):
    return [{"code": f"c{i:02d}", "sell": sell + i, "price": None, "buy": None} for i in range(n)]


def go(tmp, rates, post, env=ENV, logs=None):
    log = (logs if logs is not None else []).append
    return ln.run(env, str(tmp), rates, DAILY, "2026-11-18", "2026-11-18T10:00:00Z", log, post)


def test_posts_payload_with_bearer_and_change_percent(tmp_path):
    post = Post()
    assert go(tmp_path, [{"code": "usd", "sell": 110.0, "buy": 109.0, "price": None}], post)
    url, kw = post.calls[0]
    assert url == ln.DEFAULT_URL and kw["headers"] == {"Authorization": "Bearer s3cret-value"}
    assert kw["json"] == {"asOf": "2026-11-18T10:00:00Z", "rates": [{"code": "usd", "sell": 110.0, "changePercent": 10.0}]}


def test_only_changed_and_capped_at_twenty(tmp_path):
    post = Post()
    go(tmp_path, rows(30), post)
    assert len(post.calls[0][1]["json"]["rates"]) == 20
    go(tmp_path, rows(30), post)
    assert len(post.calls[1][1]["json"]["rates"]) == 10
    assert len(post.calls) == 2


def test_unchanged_sends_nothing(tmp_path):
    post = Post()
    go(tmp_path, rows(3), post)
    assert go(tmp_path, rows(3), post) is False
    assert len(post.calls) == 1


def test_failure_never_raises_and_does_not_record(tmp_path):
    logs = []
    assert go(tmp_path, rows(2), Post(401), logs=logs) is False
    assert not (tmp_path / ln.STATE_FILE).exists()

    def boom(*a, **k):
        raise OSError("down")
    assert go(tmp_path, rows(2), boom, logs=logs) is False
    assert all("s3cret" not in line for line in logs)


def test_no_secret_means_no_call(tmp_path):
    post = Post()
    assert go(tmp_path, rows(2), post, env={}) is False
    assert post.calls == []


def test_intraday_baseline_beats_history_close(tmp_path):
    intraday = {"points": [{"ts": "2026-11-17T08:00:00Z", "sell": 105.0, "buy": 1, "price": None},
                           {"ts": "2026-11-18T08:00:00Z", "sell": 108.0, "buy": 1, "price": None}]}
    post = Post()
    load = lambda logical: intraday if logical == "v1/intraday/usd" else None
    ln.run(ENV, str(tmp_path), [{"code": "usd", "sell": 110.0, "buy": 109.0, "price": None}], DAILY,
           "2026-11-18", "t", [].append, post, load)
    assert post.calls[0][1]["json"]["rates"][0]["changePercent"] == 4.76


def test_history_close_used_without_intraday(tmp_path):
    post = Post()
    ln.run(ENV, str(tmp_path), [{"code": "usd", "sell": 110.0, "buy": 109.0, "price": None}], DAILY,
           "2026-11-18", "t", [].append, post, lambda _l: None)
    assert post.calls[0][1]["json"]["rates"][0]["changePercent"] == 10.0


def test_non_https_url_override_is_ignored(tmp_path):
    post = Post()
    env = {**ENV, "LIVE_NOTIFY_URL": "http://evil.example/x"}
    go(tmp_path, [{"code": "usd", "sell": 110.0, "buy": 109.0, "price": None}], post, env)
    assert post.calls[0][0] == ln.DEFAULT_URL
