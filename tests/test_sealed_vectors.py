import json
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "tools"))
sys.path.insert(0, str(HERE))
import gheymat_seal as gs
import make_sealed_vectors as mk

FIXTURE = mk.DEFAULT_OUT
LOCAL = HERE / "fixtures" / "sealed-vectors.json"


@pytest.fixture(scope="module")
def generated() -> dict:
    return mk.make_vectors()


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(LOCAL.read_text(encoding="utf-8"))


def keys(fx: dict) -> tuple[bytes, dict[int, Ed25519PublicKey]]:
    master = gs.unb64(fx["payloadKey"])
    pub = {int(k): Ed25519PublicKey.from_public_bytes(gs.unb64(v)) for k, v in fx["signingPublicKeys"].items()}
    return master, pub


def test_generator_is_deterministic(generated):
    assert mk.render(generated) == mk.render(mk.make_vectors())
    assert generated["version"] == gs.VERSION == 2
    assert {v["name"] for v in generated["vectors"]} == {"health", "latest", "instruments", "tampered-resigned",
                                                          "bad-signature", "next-key"}
    assert gs.unb64(generated["payloadKey"]) == mk.TEST_PAYLOAD_KEY == bytes(range(101, 133))


def test_fixture_on_disk_matches_the_generator(generated, fixture):
    assert LOCAL.read_text(encoding="utf-8") == mk.render(generated), \
        "regenerate with: python tests/make_sealed_vectors.py tests/fixtures/sealed-vectors.json"
    if FIXTURE.exists():
        assert FIXTURE.read_text(encoding="utf-8") == mk.render(generated), \
            "regenerate with: python tests/make_sealed_vectors.py"


def test_every_vector_opens_or_fails_as_labelled(fixture):
    master, pub = keys(fixture)
    current = {1: pub[1]}
    for logical, expected in fixture["opaquePaths"].items():
        assert gs.opaque_path(master, logical) == expected and len(expected) == 2 + 32
    for v in fixture["vectors"]:
        env = json.loads(v["envelope"])
        assert env["v"] == 2 and env["issued"] == v["issued"] and env["kid"] == v["kid"] and "path" not in env
        now = v["issued"] + 60
        if v["name"] in ("health", "latest", "instruments"):
            plain = gs.open_envelope(env, master, current, v["logical"], now=now)
            assert json.dumps(plain, ensure_ascii=False, separators=(",", ":")) == v["plaintext"]
        elif v["name"] == "tampered-resigned":
            with pytest.raises(gs.EnvelopeError, match="cannot open"):
                gs.open_envelope(env, master, current, v["logical"], now=now)
        elif v["name"] == "bad-signature":
            with pytest.raises(gs.EnvelopeError, match="bad signature"):
                gs.open_envelope(env, master, current, v["logical"], now=now)
        elif v["name"] == "next-key":
            with pytest.raises(gs.EnvelopeError, match="unknown signing key"):
                gs.open_envelope(env, master, current, v["logical"], now=now)
            plain = gs.open_envelope(env, master, pub, v["logical"], now=now)
            assert json.dumps(plain, ensure_ascii=False, separators=(",", ":")) == v["plaintext"]
        else:
            raise AssertionError(f"unknown vector {v['name']}")
