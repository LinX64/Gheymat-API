import hashlib
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from r2_store import R2Store, sign_v4

KEY_ID = "KEYIDEXAMPLE01"
SECRET = "secretexample/0123456789+abcdef"
SEEN = []


class Handler(BaseHTTPRequestHandler):
    def do_PUT(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        SEEN.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        SEEN.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, b""))
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def serve():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_a_real_signed_put_verifies_on_the_wire():
    SEEN.clear()
    server = serve()
    try:
        store = R2Store("acct1", "bucket-1", KEY_ID, SECRET, endpoint=f"http://127.0.0.1:{server.server_address[1]}")
        body = b'{"v":2,"x":"y"}'
        store.put("d/0123456789abcdef0123456789abcdef", body)
    finally:
        server.shutdown()
    method, path, headers, received = SEEN[0]
    assert method == "PUT" and received == body
    assert path == "/bucket-1/d/0123456789abcdef0123456789abcdef"
    assert headers["host"] == f"127.0.0.1:{server.server_address[1]}"
    assert headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
    assert headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert headers["content-type"] == "application/json"
    assert "expect" not in headers
    authorization = headers["authorization"]
    signed = re.search(r"SignedHeaders=([^,]+),", authorization).group(1).split(";")
    assert signed == sorted(signed)
    assert set(signed) == {"cache-control", "content-type", "host", "x-amz-content-sha256", "x-amz-date"}
    claimed = re.search(r"Signature=([0-9a-f]{64})", authorization).group(1)
    expected = sign_v4(
        "PUT",
        headers["host"],
        path,
        "",
        {name: headers[name] for name in ("content-type", "cache-control")},
        headers["x-amz-content-sha256"],
        KEY_ID,
        SECRET,
        headers["x-amz-date"],
        "auto",
        "s3",
    )["Authorization"]
    assert f"Signature={claimed}" in expected


def test_head_404_over_the_wire_is_none():
    SEEN.clear()
    server = serve()
    try:
        store = R2Store("acct1", "bucket-1", KEY_ID, SECRET, endpoint=f"http://127.0.0.1:{server.server_address[1]}")
        assert store.head("d/0123456789abcdef0123456789abcdef") is None
    finally:
        server.shutdown()
    assert SEEN[0][0] == "HEAD" and "authorization" in SEEN[0][2]
