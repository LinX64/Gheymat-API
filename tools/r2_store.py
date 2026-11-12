import hashlib
import hmac
import re
import threading
import time
from urllib.parse import quote, urlsplit

import requests

EMPTY_PAYLOAD_HASH = hashlib.sha256(b"").hexdigest()
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SECRET_PATTERN = re.compile(r"^[\x21-\x7e]+$")
_BACKOFF_SECONDS = (1, 2, 4)


class StoreError(Exception):
    def __init__(self, kind, status=None):
        self.kind = kind
        self.status = status
        super().__init__(kind if status is None else f"{kind} {status}")


def _hmac(key, message):
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret, day, region, service):
    step = _hmac(("AWS4" + secret).encode("utf-8"), day)
    step = _hmac(step, region)
    step = _hmac(step, service)
    return _hmac(step, "aws4_request")


def canonical_request(method, path, query, headers, payload_hash):
    names = sorted(headers)
    block = "".join(f"{name}:{' '.join(headers[name].split())}\n" for name in names)
    return "\n".join([method, path, query, block, ";".join(names), payload_hash])


def string_to_sign(canonical, amz_date, region, service):
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, digest])


def authorization_header(method, path, query, headers, payload_hash, key_id, secret, amz_date, region, service):
    lowered = {name.lower(): str(value) for name, value in headers.items()}
    canonical = canonical_request(method, path, query, lowered, payload_hash)
    to_sign = string_to_sign(canonical, amz_date, region, service)
    key = signing_key(secret, amz_date[:8], region, service)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    names = ";".join(sorted(lowered))
    return f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={names}, Signature={signature}"


def sign_v4(method, host, path, query, headers, payload_hash, key_id, secret, amz_date, region, service):
    out = {name.lower(): str(value) for name, value in headers.items()}
    out["host"] = host
    out["x-amz-date"] = amz_date
    out["x-amz-content-sha256"] = payload_hash
    out["authorization"] = authorization_header(
        method, path, query, {k: v for k, v in out.items()}, payload_hash, key_id, secret, amz_date, region, service
    )
    return {("Authorization" if name == "authorization" else name): value for name, value in out.items()}


class R2Store:
    def __init__(
        self,
        account_id,
        bucket,
        key_id,
        secret,
        session=None,
        clock=time.time,
        sleep=time.sleep,
        endpoint=None,
        region="auto",
        service="s3",
        retries=3,
    ):
        valid = (
            isinstance(account_id, str)
            and isinstance(bucket, str)
            and isinstance(key_id, str)
            and isinstance(secret, str)
            and _NAME_PATTERN.match(account_id)
            and _NAME_PATTERN.match(bucket)
            and _SECRET_PATTERN.match(key_id)
            and _SECRET_PATTERN.match(secret)
        )
        if not valid:
            raise StoreError("config") from None
        self._bucket = bucket
        self._key_id = key_id
        self._secret = secret
        self._session = session
        self._clock = clock
        self._sleep = sleep
        self._base = (endpoint.rstrip("/") if endpoint else f"https://{account_id}.r2.cloudflarestorage.com")
        self._host = urlsplit(self._base).netloc
        self._region = region
        self._service = service
        self._retries = max(1, int(retries))
        self._lock = threading.Lock()
        self._stats = {"put": 0, "head": 0, "delete": 0, "retries": 0, "failures": 0}

    def __repr__(self):
        return "R2Store()"

    def _bump(self, name):
        with self._lock:
            self._stats[name] += 1

    def stats(self):
        with self._lock:
            return dict(self._stats)

    def put(self, key, body, content_type="application/json", cache_control="public, max-age=0, must-revalidate", timeout=(5, 30)):
        self._bump("put")
        headers = {"content-type": content_type, "cache-control": cache_control}
        self._send("PUT", key, body, headers, timeout)

    def head(self, key, timeout=(5, 15)):
        self._bump("head")
        response = self._send("HEAD", key, b"", {}, timeout, allow_missing=True)
        if response.status_code == 404:
            return None
        found = response.headers
        return {
            "etag": found.get("ETag", ""),
            "length": int(found.get("Content-Length", 0) or 0),
            "cache_control": found.get("Cache-Control"),
        }

    def delete(self, key, timeout=(5, 15)):
        self._bump("delete")
        self._send("DELETE", key, b"", {}, timeout)

    def _session_or_new(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _send(self, method, key, body, headers, timeout, allow_missing=False):
        if isinstance(timeout, (int, float)):
            timeout = (5, float(timeout))
        path = f"/{self._bucket}/{quote(key, safe='/')}"
        url = f"{self._base}{path}"
        payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_PAYLOAD_HASH
        session = self._session_or_new()
        last = None
        for attempt in range(self._retries):
            if attempt:
                self._bump("retries")
                self._sleep(_BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)])
            amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self._clock()))
            signed = sign_v4(
                method, self._host, path, "", headers, payload_hash,
                self._key_id, self._secret, amz_date, self._region, self._service,
            )
            try:
                response = session.request(
                    method, url, headers=signed, data=body if method == "PUT" else None,
                    timeout=timeout, allow_redirects=False,
                )
            except requests.exceptions.Timeout:
                last = StoreError("timeout")
                continue
            except requests.exceptions.RequestException:
                last = StoreError("connection")
                continue
            except Exception:
                last = StoreError("connection")
                continue
            code = response.status_code
            if code == 429 or code >= 500:
                last = StoreError("status", code)
                continue
            if code == 404 and allow_missing:
                return response
            if code >= 300:
                self._bump("failures")
                raise StoreError("status", code) from None
            return response
        self._bump("failures")
        raise StoreError(last.kind, last.status) from None
