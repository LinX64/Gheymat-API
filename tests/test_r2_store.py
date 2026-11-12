import hashlib
import hmac
import logging
import re
import sys
import threading
from pathlib import Path

import pytest
import requests
from requests.structures import CaseInsensitiveDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import r2_store
from r2_store import R2Store, StoreError, sign_v4

ACCOUNT = "acct123abc"
BUCKET = "feed-bucket"
KEY_ID = "KEYIDEXAMPLE01"
SECRET = "s3cr3t/Value+Example"
FIXED_CLOCK = 1440938160.0
FIXED_DATE = "20150830T123600Z"
SENSITIVE = [ACCOUNT, BUCKET, KEY_ID, SECRET, "cloudflarestorage", "https://", "localhost"]


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})
        self.text = f"body mentioning {ACCOUNT} {BUCKET} {SECRET}"


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_store(script, sleeps=None, **kwargs):
    sleeps = sleeps if sleeps is not None else []
    session = FakeSession(script)
    store = R2Store(
        ACCOUNT, BUCKET, KEY_ID, SECRET,
        session=session, clock=lambda: FIXED_CLOCK, sleep=sleeps.append, **kwargs,
    )
    return store, session, sleeps


def independent_signature(method, path, headers, payload_hash, amz_date, region, service, secret):
    lowered = {k.lower(): v for k, v in headers.items() if k.lower() != "authorization"}
    names = sorted(lowered)
    canonical = (
        f"{method}\n{path}\n\n"
        + "".join(f"{n}:{lowered[n].strip()}\n" for n in names)
        + f"\n{';'.join(names)}\n{payload_hash}"
    )
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    key = ("AWS4" + secret).encode()
    for part in (day, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()


def test_suite_vector_get_vanilla_signature():
    headers = {"host": "example.amazonaws.com", "x-amz-date": FIXED_DATE}
    empty = hashlib.sha256(b"").hexdigest()
    auth = r2_store.authorization_header(
        "GET", "/", "", headers, empty,
        "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", FIXED_DATE, "us-east-1", "service",
    )
    assert "SignedHeaders=host;x-amz-date" in auth
    assert "Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request" in auth
    assert auth.endswith("Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31")


def test_suite_vector_intermediate_steps():
    headers = {"host": "example.amazonaws.com", "x-amz-date": FIXED_DATE}
    empty = hashlib.sha256(b"").hexdigest()
    canonical = r2_store.canonical_request("GET", "/", "", headers, empty)
    assert canonical == (
        "GET\n/\n\nhost:example.amazonaws.com\nx-amz-date:20150830T123600Z\n\n"
        "host;x-amz-date\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == (
        "bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63"
    )
    to_sign = r2_store.string_to_sign(canonical, FIXED_DATE, "us-east-1", "service")
    assert to_sign == (
        "AWS4-HMAC-SHA256\n20150830T123600Z\n20150830/us-east-1/service/aws4_request\n"
        "bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63"
    )
    key = r2_store.signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20150830", "us-east-1", "service")
    assert hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest() == (
        "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


def test_sign_v4_adds_amz_headers_and_signs_all():
    out = sign_v4(
        "GET", "example.amazonaws.com", "/", "", {"Host-Extra": "x"}, hashlib.sha256(b"").hexdigest(),
        "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", FIXED_DATE, "us-east-1", "service",
    )
    assert out["x-amz-date"] == FIXED_DATE
    assert out["x-amz-content-sha256"] == hashlib.sha256(b"").hexdigest()
    assert "SignedHeaders=host;host-extra;x-amz-content-sha256;x-amz-date," in out["Authorization"]


def test_put_request_shape_and_signature_verifies():
    store, session, _ = make_store([FakeResponse(200)])
    body = b'{"a": 1}'
    store.put("v1/d/prices.json", body)
    call = session.calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == f"https://{ACCOUNT}.r2.cloudflarestorage.com/{BUCKET}/v1/d/prices.json"
    assert call["data"] is body
    assert call["allow_redirects"] is False
    assert call["timeout"] == (5, 30)
    headers = call["headers"]
    payload_hash = hashlib.sha256(body).hexdigest()
    assert set(k.lower() for k in headers) == {
        "content-type", "cache-control", "host", "x-amz-content-sha256", "x-amz-date", "authorization",
    }
    assert headers["host"] == f"{ACCOUNT}.r2.cloudflarestorage.com"
    assert headers["content-type"] == "application/json"
    assert headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert headers["x-amz-date"] == FIXED_DATE
    assert headers["x-amz-content-sha256"] == payload_hash
    match = re.fullmatch(
        r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/auto/s3/aws4_request, "
        r"SignedHeaders=([a-z0-9;-]+), Signature=([0-9a-f]{64})",
        headers["Authorization"],
    )
    assert match
    assert match.group(1) == KEY_ID
    assert match.group(3) == "cache-control;content-type;host;x-amz-content-sha256;x-amz-date"
    expected = independent_signature(
        "PUT", f"/{BUCKET}/v1/d/prices.json", headers, payload_hash, FIXED_DATE, "auto", "s3", SECRET
    )
    assert match.group(4) == expected


def test_put_quotes_key_in_url_and_canonical_path():
    store, session, _ = make_store([FakeResponse(200)])
    store.put("a b/c+d.json", b"x")
    call = session.calls[0]
    assert call["url"].endswith(f"/{BUCKET}/a%20b/c%2Bd.json")
    headers = call["headers"]
    sig = headers["Authorization"].rsplit("Signature=", 1)[1]
    assert sig == independent_signature(
        "PUT", f"/{BUCKET}/a%20b/c%2Bd.json", headers, hashlib.sha256(b"x").hexdigest(),
        FIXED_DATE, "auto", "s3", SECRET,
    )


def test_custom_endpoint_host_derived_from_url():
    store, session, _ = make_store([FakeResponse(200)], endpoint="http://localhost:9000")
    store.put("k.json", b"x")
    assert session.calls[0]["url"] == f"http://localhost:9000/{BUCKET}/k.json"
    assert session.calls[0]["headers"]["host"] == "localhost:9000"


def test_retry_500_429_then_success_sleeps_1_2_with_fresh_signatures():
    times = iter([FIXED_CLOCK, FIXED_CLOCK + 1, FIXED_CLOCK + 2])
    sleeps = []
    session = FakeSession([FakeResponse(500), FakeResponse(429), FakeResponse(200)])
    store = R2Store(ACCOUNT, BUCKET, KEY_ID, SECRET, session=session, clock=lambda: next(times), sleep=sleeps.append)
    store.put("k.json", b"x")
    assert len(session.calls) == 3
    assert sleeps == [1, 2]
    dates = [c["headers"]["x-amz-date"] for c in session.calls]
    assert len(set(dates)) == 3
    assert len({c["headers"]["Authorization"] for c in session.calls}) == 3
    assert store.stats()["retries"] == 2
    assert store.stats()["failures"] == 0


def test_client_error_raises_without_retry():
    store, session, sleeps = make_store([FakeResponse(403)])
    with pytest.raises(StoreError) as info:
        store.put("k.json", b"x")
    assert info.value.kind == "status"
    assert info.value.status == 403
    assert str(info.value) == "status 403"
    assert len(session.calls) == 1
    assert sleeps == []


def test_redirect_status_raises_without_retry():
    store, session, _ = make_store([FakeResponse(301)])
    with pytest.raises(StoreError) as info:
        store.put("k.json", b"x")
    assert info.value.kind == "status"
    assert len(session.calls) == 1


def test_server_errors_exhaust_retries():
    store, session, sleeps = make_store([FakeResponse(503)] * 3)
    with pytest.raises(StoreError) as info:
        store.put("k.json", b"x")
    assert (info.value.kind, info.value.status) == ("status", 503)
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_connection_errors_raise_connection_kind_after_retries():
    errors = [requests.exceptions.ConnectionError(f"boom {ACCOUNT} {SECRET}")] * 3
    store, session, sleeps = make_store(errors)
    with pytest.raises(StoreError) as info:
        store.put("k.json", b"x")
    assert info.value.kind == "connection"
    assert info.value.status is None
    assert str(info.value) == "connection"
    assert len(session.calls) == 3
    assert sleeps == [1, 2]
    assert store.stats()["failures"] == 1


def test_timeouts_raise_timeout_kind_after_retries():
    errors = [requests.exceptions.ReadTimeout(f"slow {BUCKET}")] * 3
    store, session, sleeps = make_store(errors)
    with pytest.raises(StoreError) as info:
        store.put("k.json", b"x")
    assert info.value.kind == "timeout"
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_retries_parameter_limits_attempts():
    store, session, sleeps = make_store([FakeResponse(500)] * 4, retries=4)
    with pytest.raises(StoreError):
        store.put("k.json", b"x")
    assert len(session.calls) == 4
    assert sleeps == [1, 2, 4]


def assert_clean(text):
    for fragment in SENSITIVE:
        assert fragment not in text


@pytest.mark.parametrize(
    "script",
    [
        [FakeResponse(403)],
        [FakeResponse(500)] * 3,
        [requests.exceptions.ConnectionError(f"{ACCOUNT} {SECRET} https://{ACCOUNT}.r2.cloudflarestorage.com")] * 3,
        [requests.exceptions.ConnectTimeout(f"{BUCKET} {KEY_ID}")] * 3,
        [RuntimeError(f"{SECRET} {BUCKET}")] * 3,
    ],
)
def test_no_sensitive_text_in_any_failure_path(script, caplog, capsys):
    store, _, _ = make_store(script)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StoreError) as info:
            store.put("k.json", b"x")
    assert_clean(str(info.value))
    assert_clean(repr(info.value))
    assert_clean(repr(info.value.args))
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ or info.value.__context__ is None
    assert_clean(caplog.text)
    captured = capsys.readouterr()
    assert_clean(captured.out + captured.err)
    assert_clean(repr(store))
    assert_clean(str(vars(store).get("_stats", "")))


def test_repr_hides_credentials():
    store, _, _ = make_store([])
    assert_clean(repr(store))
    assert_clean(str(store))


@pytest.mark.parametrize(
    "args",
    [
        ("", BUCKET, KEY_ID, SECRET),
        (ACCOUNT, "", KEY_ID, SECRET),
        (ACCOUNT, BUCKET, "", SECRET),
        (ACCOUNT, BUCKET, KEY_ID, ""),
        ("acct/evil", BUCKET, KEY_ID, SECRET),
        (ACCOUNT, "bucket name", KEY_ID, SECRET),
        (ACCOUNT, "bu:cket", KEY_ID, SECRET),
        (ACCOUNT, BUCKET, "key id", SECRET),
        (ACCOUNT, BUCKET, KEY_ID, "sec ret"),
        (ACCOUNT, BUCKET, KEY_ID, "sec\nret"),
        (ACCOUNT, BUCKET, KEY_ID, "sécret"),
    ],
)
def test_config_validation_rejects_bad_values(args):
    with pytest.raises(StoreError) as info:
        R2Store(*args)
    assert info.value.kind == "config"
    assert str(info.value) == "config"


def test_config_accepts_valid_values():
    R2Store("a.b-c_1", "bucket.name-1", "AKIA0123", "ab/cd+ef=")


def test_head_200_returns_dict():
    response = FakeResponse(200, {"ETag": '"abc"', "Content-Length": "42", "Cache-Control": "no-cache"})
    store, session, _ = make_store([response])
    assert store.head("k.json") == {"etag": '"abc"', "length": 42, "cache_control": "no-cache"}
    call = session.calls[0]
    assert call["method"] == "HEAD"
    assert call["allow_redirects"] is False
    assert call["timeout"] == (5, 15)
    assert call["headers"]["Authorization"].rsplit("Signature=", 1)[1] == independent_signature(
        "HEAD", f"/{BUCKET}/k.json", call["headers"], hashlib.sha256(b"").hexdigest(),
        FIXED_DATE, "auto", "s3", SECRET,
    )


def test_head_without_cache_control_is_none():
    store, _, _ = make_store([FakeResponse(200, {"ETag": '"e"', "Content-Length": "1"})])
    assert store.head("k.json")["cache_control"] is None


def test_head_404_returns_none():
    store, session, sleeps = make_store([FakeResponse(404)])
    assert store.head("k.json") is None
    assert len(session.calls) == 1
    assert sleeps == []


def test_head_other_status_raises():
    store, _, _ = make_store([FakeResponse(403)])
    with pytest.raises(StoreError) as info:
        store.head("k.json")
    assert (info.value.kind, info.value.status) == ("status", 403)


def test_delete_success_and_failure():
    store, session, _ = make_store([FakeResponse(204), FakeResponse(403)])
    store.delete("k.json")
    assert session.calls[0]["method"] == "DELETE"
    assert session.calls[0]["allow_redirects"] is False
    with pytest.raises(StoreError):
        store.delete("k.json")


def test_allow_redirects_false_on_every_call():
    store, session, _ = make_store([FakeResponse(200), FakeResponse(200, {"Content-Length": "0"}), FakeResponse(204)])
    store.put("k.json", b"x")
    store.head("k.json")
    store.delete("k.json")
    assert [c["allow_redirects"] for c in session.calls] == [False, False, False]


def test_stats_counters():
    store, _, _ = make_store(
        [FakeResponse(200), FakeResponse(500), FakeResponse(200), FakeResponse(404), FakeResponse(204), FakeResponse(403)]
    )
    assert store.stats() == {"put": 0, "head": 0, "delete": 0, "retries": 0, "failures": 0}
    store.put("a", b"x")
    store.put("b", b"x")
    store.head("a")
    store.delete("a")
    with pytest.raises(StoreError):
        store.delete("a")
    assert store.stats() == {"put": 2, "head": 1, "delete": 2, "retries": 1, "failures": 1}


def test_stats_returns_copy():
    store, _, _ = make_store([])
    store.stats()["put"] = 99
    assert store.stats()["put"] == 0


def test_session_created_lazily_when_not_injected():
    store = R2Store(ACCOUNT, BUCKET, KEY_ID, SECRET)
    assert store._session is None
    assert isinstance(store._session_or_new(), requests.Session)


def test_float_timeout_becomes_connect_read_pair():
    store, session, _ = make_store([FakeResponse(200), FakeResponse(200, {"Content-Length": "0"})])
    store.put("k.json", b"x", timeout=12.5)
    store.head("k.json", timeout=7)
    assert session.calls[0]["timeout"] == (5, 12.5)
    assert session.calls[1]["timeout"] == (5, 7.0)


def test_stats_consistent_under_threads():
    class ThreadSafeSession:
        def __init__(self):
            self.lock = threading.Lock()

        def request(self, method, url, **kwargs):
            return FakeResponse(200, {"Content-Length": "0"})

    store = R2Store(ACCOUNT, BUCKET, KEY_ID, SECRET, session=ThreadSafeSession(), clock=lambda: FIXED_CLOCK, sleep=lambda s: None)

    def work():
        for _ in range(200):
            store.put("k.json", b"x")
            store.head("k.json")
            store.stats()

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.stats() == {"put": 1600, "head": 1600, "delete": 0, "retries": 0, "failures": 0}
