"""Envelope v2 reference: key derivation, header layout, policy checks, malformed input, state read-back.
Throwaway test keys only."""
import hashlib
import hmac
import json
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import gheymat_seal as gs  # noqa: E402

MASTER = bytes(range(32))
SIGNING = Ed25519PrivateKey.from_private_bytes(bytes(range(100, 132)))
NEXT = Ed25519PrivateKey.from_private_bytes(bytes(range(50, 82)))
PUBLIC = SIGNING.public_key()
NOW = 1_792_100_000


@pytest.fixture
def sealer() -> gs.Sealer:
    return gs.Sealer(MASTER, SIGNING)


def opened(env, logical="v1/latest", **kw):
    kw.setdefault("now", NOW)
    return gs.open_envelope(env, MASTER, PUBLIC, logical, **kw)


def rfc5869_hkdf_sha256(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.new(bytes(32), ikm, hashlib.sha256).digest()
    okm, block, counter = b"", b"", 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def test_subkeys_match_rfc5869_with_zero_salt_and_differ_per_purpose(sealer):
    assert sealer.path_key == rfc5869_hkdf_sha256(MASTER, b"gheymat/v2/path")
    assert sealer.enc_key == rfc5869_hkdf_sha256(MASTER, b"gheymat/v2/enc")
    assert sealer.path_key != sealer.enc_key and sealer.path_key != MASTER and sealer.enc_key != MASTER
    assert gs.derive_keys(MASTER) == (sealer.path_key, sealer.enc_key)
    with pytest.raises(ValueError):
        gs.derive_keys(b"short")


def test_opaque_path_is_32_hex_under_the_path_subkey(sealer):
    p = sealer.opaque_path("v1/latest")
    assert p == gs.opaque_path(MASTER, "v1/latest")
    assert p.startswith("d/") and len(p) == 2 + 32 and all(c in "0123456789abcdef" for c in p[2:])
    assert p == "d/" + hmac.new(sealer.path_key, b"v1/latest", hashlib.sha256).hexdigest()[:32]
    assert p != hmac.new(MASTER, b"v1/latest", hashlib.sha256).hexdigest()[:32]
    assert p != sealer.opaque_path("v1/instruments") and p != gs.opaque_path(bytes(32), "v1/latest")


def test_header_layout_is_canonical():
    nonce = bytes(range(12))
    h = gs.header("v1/latest", 1792051212, nonce, kid=3)
    assert h == (b"gheymat-seal" + bytes([2, 3]) + (9).to_bytes(2, "big") + b"v1/latest"
                 + (1792051212).to_bytes(8, "big") + nonce)
    assert gs.header("v1/latest", 1, nonce) != gs.header("v1/latest", 1, nonce, kid=2)
    for bad in (dict(logical=""), dict(logical="x" * 70000), dict(kid=256), dict(issued=-1), dict(nonce=b"\0" * 11)):
        args = dict(logical="v1/latest", issued=1, nonce=nonce)
        args.update(bad)
        with pytest.raises(ValueError):
            gs.header(args["logical"], args["issued"], args["nonce"], args.get("kid", 1))


def test_seal_open_roundtrip_and_envelope_shape(sealer):
    obj = {"seq": 1, "rates": [{"code": "usd", "fa": "دلار"}], "flags": None}
    env = sealer.seal("v1/latest", obj, issued=NOW - 30)
    assert set(env) == set(gs.ENVELOPE_FIELDS) and "path" not in env
    assert env["v"] == 2 and env["kid"] == 1 and env["issued"] == NOW - 30
    assert len(gs.unb64(env["nonce"])) == 12 and len(gs.unb64(env["sig"])) == 64
    assert opened(env) == obj
    assert opened(json.loads(json.dumps(env))) == obj
    assert gs.open_envelope(env, MASTER, {1: PUBLIC}, "v1/latest", now=NOW) == obj
    assert sealer.seal("v1/latest", obj, issued=NOW)["nonce"] != sealer.seal("v1/latest", obj, issued=NOW)["nonce"]


def test_signature_binds_path_version_kid_issued_nonce_and_ciphertext(sealer):
    env = sealer.seal("v1/latest", {"seq": 1}, issued=NOW - 30)
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        opened(env, "v1/instruments")
    with pytest.raises(gs.EnvelopeError, match="version"):
        opened({**env, "v": 1})
    with pytest.raises(gs.EnvelopeError, match="version"):
        opened({**env, "v": 3})
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        opened({**env, "kid": 2})
    with pytest.raises(gs.EnvelopeError, match="unknown signing key"):
        gs.open_envelope({**env, "kid": 2}, MASTER, {1: PUBLIC}, "v1/latest", now=NOW)
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        opened({**env, "issued": env["issued"] + 1})
    nonce = bytearray(gs.unb64(env["nonce"]))
    nonce[0] ^= 1
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        opened({**env, "nonce": gs.b64(bytes(nonce))})
    ct = bytearray(gs.unb64(env["ciphertext"]))
    ct[0] ^= 1
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        opened({**env, "ciphertext": gs.b64(bytes(ct))})
    resigned = {**env, "ciphertext": gs.b64(bytes(ct)),
                "sig": gs.b64(SIGNING.sign(gs.header("v1/latest", env["issued"], gs.unb64(env["nonce"])) + bytes(ct)))}
    with pytest.raises(gs.EnvelopeError, match="cannot open"):
        opened(resigned)
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        gs.open_envelope(env, MASTER, NEXT.public_key(), "v1/latest", now=NOW)
    with pytest.raises(gs.EnvelopeError, match="cannot open"):
        gs.open_envelope(env, bytes(32), PUBLIC, "v1/latest", now=NOW)


def test_key_id_selects_the_verifying_key():
    env = gs.Sealer(MASTER, NEXT, kid=2).seal("v1/latest", {"seq": 2}, issued=NOW)
    assert env["kid"] == 2
    keys = {1: PUBLIC, 2: NEXT.public_key()}
    assert gs.open_envelope(env, MASTER, keys, "v1/latest", now=NOW) == {"seq": 2}
    assert gs.open_envelope(env, MASTER, NEXT.public_key(), "v1/latest", now=NOW) == {"seq": 2}
    with pytest.raises(gs.EnvelopeError, match="unknown signing key"):
        gs.open_envelope(env, MASTER, {1: PUBLIC}, "v1/latest", now=NOW)
    with pytest.raises(gs.EnvelopeError, match="bad signature"):
        gs.open_envelope(env, MASTER, PUBLIC, "v1/latest", now=NOW)
    with pytest.raises(ValueError):
        gs.Sealer(MASTER, NEXT, kid=300).seal("v1/latest", {}, issued=NOW)


def test_freshness_policy_defaults_and_cold_start(sealer):
    env = sealer.seal("v1/latest", {"seq": 1}, issued=NOW)
    assert gs.MAX_AGE == 7200 and gs.MAX_FUTURE == 300
    assert opened(env, now=NOW + 7200) == {"seq": 1}
    with pytest.raises(gs.EnvelopeError, match="too old"):
        opened(env, now=NOW + 7201)
    assert opened(env, now=NOW - 300) == {"seq": 1}
    with pytest.raises(gs.EnvelopeError, match="future"):
        opened(env, now=NOW - 301)
    assert opened(env, now=NOW + 10 * 86400, max_age=None) == {"seq": 1}
    with pytest.raises(gs.EnvelopeError, match="future"):
        opened(env, now=NOW - 86400, max_age=None)
    assert opened(env, now=NOW - 86400, max_age=None, max_future=None) == {"seq": 1}
    with pytest.raises(gs.EnvelopeError, match="too old"):
        opened(env, now=NOW + 1, max_age=0)


def test_rollback_rejects_strictly_older_envelopes_only(sealer):
    env = sealer.seal("v1/latest", {"seq": 1}, issued=NOW)
    assert opened(env, last_accepted=NOW - 1) == {"seq": 1}
    assert opened(env, last_accepted=NOW) == {"seq": 1}
    with pytest.raises(gs.EnvelopeError, match="older than the last accepted"):
        opened(env, last_accepted=NOW + 1)
    older = sealer.seal("v1/latest", {"seq": 0}, issued=NOW - 600)
    with pytest.raises(gs.EnvelopeError, match="older than the last accepted"):
        opened(older, last_accepted=NOW)


def test_malformed_envelopes_are_rejected_without_crashing(sealer):
    env = sealer.seal("v1/latest", {"seq": 1}, issued=NOW)
    cases = [
        "not an object", [], {}, {**env, "v": "2"}, {**env, "v": True}, {**env, "kid": "1"}, {**env, "kid": -1},
        {**env, "issued": "1"}, {**env, "issued": -5}, {**env, "issued": 1 << 63}, {**env, "issued": 1.5},
        {**env, "nonce": "@@"}, {**env, "nonce": gs.b64(b"\0" * 11)}, {**env, "sig": gs.b64(b"\0" * 63)},
        {**env, "ciphertext": gs.b64(b"\0" * 15)}, {**env, "ciphertext": 7}, {k: v for k, v in env.items() if k != "sig"},
    ]
    for case in cases:
        with pytest.raises(gs.EnvelopeError):
            opened(case)


def test_sealed_plaintext_must_be_json(sealer):
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    nonce = bytes(12)
    aad = gs.header("health", NOW, nonce)
    ct = ChaCha20Poly1305(sealer.enc_key).encrypt(nonce, b"\xff\xfe not json", aad)
    env = {"v": 2, "kid": 1, "issued": NOW, "nonce": gs.b64(nonce), "ciphertext": gs.b64(ct), "sig": gs.b64(SIGNING.sign(aad + ct))}
    with pytest.raises(gs.EnvelopeError, match="not JSON"):
        opened(env, "health")


def test_from_env_requires_both_keys_of_32_bytes(monkeypatch):
    monkeypatch.delenv("GHEYMAT_PAYLOAD_KEY", raising=False)
    monkeypatch.delenv("GHEYMAT_SIGNING_KEY", raising=False)
    assert gs.Sealer.from_env() is None
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", gs.b64(MASTER))
    assert gs.Sealer.from_env() is None
    monkeypatch.setenv("GHEYMAT_SIGNING_KEY", gs.b64(bytes(range(100, 132))))
    s = gs.Sealer.from_env()
    assert s is not None and s.opaque_path("health") == gs.Sealer(MASTER, SIGNING).opaque_path("health")
    monkeypatch.setenv("GHEYMAT_SIGNING_KEY", gs.b64(b"x" * 31))
    with pytest.raises(SystemExit):
        gs.Sealer.from_env()
    monkeypatch.setenv("GHEYMAT_SIGNING_KEY", "not base64!")
    with pytest.raises(gs.EnvelopeError):
        gs.Sealer.from_env()


def write_sealed(out, sealer, logical, obj):
    sealed = out / sealer.opaque_path(logical)
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_text(json.dumps(sealer.seal(logical, obj, issued=NOW - 30 * 86400)), encoding="utf-8")
    return sealed


def test_load_published_prefers_plain_then_falls_back_to_sealed_state(tmp_path, sealer):
    daily = {"start": "2012-10-09", "codes": {"usd": {"2020-03-20": [16000, 16100]}}}
    assert gs.load_published(tmp_path, "v1/daily.json", sealer) is None
    assert gs.load_published(tmp_path, "v1/daily.json", None) is None
    sealed = write_sealed(tmp_path, sealer, "v1/daily.json", daily)
    assert gs.load_published(tmp_path, "v1/daily.json", sealer) == daily
    assert gs.load_published(tmp_path, "v1/daily.json", None) is None
    plain = tmp_path / "v1" / "daily.json"
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text(json.dumps({"start": "2012-10-09", "codes": {"plain": {}}}), encoding="utf-8")
    assert gs.load_published(tmp_path, "v1/daily.json", sealer)["codes"] == {"plain": {}}
    plain.write_text("{broken", encoding="utf-8")
    assert gs.load_published(tmp_path, "v1/daily.json", sealer) is None
    plain.unlink()
    sealed.write_text("{broken", encoding="utf-8")
    assert gs.load_published(tmp_path, "v1/daily.json", sealer) is None
    write_sealed(tmp_path, sealer, "v1/daily.json", daily)
    other = gs.Sealer(MASTER, NEXT)
    assert gs.load_published(tmp_path, "v1/daily.json", other) is None
    assert gs.load_published(tmp_path, "v1/intraday/usd", gs.Sealer(bytes(32), SIGNING)) is None


def test_load_published_reads_a_state_file_larger_than_the_client_envelope_bound(tmp_path, sealer):
    daily = {"start": "2012-10-09", "codes": {f"c{c}": {f"2020-01-{d:03d}": [d, d + 1] for d in range(2500)} for c in range(33)}}
    sealed = write_sealed(tmp_path, sealer, "v1/daily.json", daily)
    assert sealed.stat().st_size > gs.MAX_ENVELOPE_BYTES
    assert gs.load_published(tmp_path, "v1/daily.json", sealer) == daily
    sealed.write_text("x" * (gs.MAX_STATE_BYTES + 1), encoding="utf-8")
    assert gs.load_published(tmp_path, "v1/daily.json", sealer) is None
