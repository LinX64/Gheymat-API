"""CI gate tools/verify_sealed.py: exit 0 only for an authentic, fresh, complete sealed v1/latest; fixed output lines,
no key material in any output. Throwaway test keys only."""
import base64
import json
import pathlib
import sys
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gheymat_seal as gs  # noqa: E402
import verify_sealed as vs  # noqa: E402

MASTER = bytes(range(7, 39))
MASTER_B64 = base64.b64encode(MASTER).decode()
SIGNING = Ed25519PrivateKey.from_private_bytes(bytes(range(60, 92)))
PUBLIC_B64 = base64.b64encode(SIGNING.public_key().public_bytes_raw()).decode()
OTHER = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))


def snapshot(n: int = 37) -> dict:
    return {"seq": 1, "fetchedAt": "2026-10-15T08:00:12Z", "source": "bonbast", "flags": ["static"],
            "rates": [{"code": f"c{i}", "buy": 1, "sell": 2} for i in range(n)]}


def publish(dist: pathlib.Path, obj, sealer=None, issued=None) -> pathlib.Path:
    sealer = sealer or gs.Sealer(MASTER, SIGNING)
    path = dist / sealer.opaque_path("v1/latest")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sealer.seal("v1/latest", obj, issued=issued)), encoding="utf-8")
    return path


def run(monkeypatch, capsys, dist, *args, key=MASTER_B64, public=PUBLIC_B64):
    if key is None:
        monkeypatch.delenv("GHEYMAT_PAYLOAD_KEY", raising=False)
    else:
        monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", key)
    monkeypatch.setattr(sys, "argv", ["verify_sealed.py", str(dist), "--public-key", public, *args])
    code = vs.main()
    out = capsys.readouterr()
    text = out.out + out.err
    for secret in (MASTER_B64, PUBLIC_B64, key or "", gs.opaque_path(MASTER, "v1/latest")[2:]):
        assert not secret or secret not in text
    assert text.count("\n") == 1
    return code, text


def test_gate_passes_for_a_fresh_complete_snapshot(tmp_path, monkeypatch, capsys):
    publish(tmp_path, snapshot())
    code, text = run(monkeypatch, capsys, tmp_path)
    assert code == 0 and text == "verify_sealed: sealed v1/latest ok, 37 rates\n"


def test_gate_fails_closed(tmp_path, monkeypatch, capsys):
    failed = "verify_sealed: sealed v1/latest FAILED verification; not deploying\n"
    publish(tmp_path, snapshot())
    assert run(monkeypatch, capsys, tmp_path, key=base64.b64encode(bytes(32)).decode()) == (1, failed)
    assert run(monkeypatch, capsys, tmp_path, key="short") == (1, failed)
    other_pub = base64.b64encode(OTHER.public_key().public_bytes_raw()).decode()
    assert run(monkeypatch, capsys, tmp_path, public=other_pub) == (1, failed)
    assert run(monkeypatch, capsys, tmp_path / "missing") == (1, failed)
    code, text = run(monkeypatch, capsys, tmp_path, key=None)
    assert code == 1 and "GHEYMAT_PAYLOAD_KEY is not set" in text

    sealed = publish(tmp_path, snapshot(36))
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)
    assert run(monkeypatch, capsys, tmp_path, "--expect-rates", "36") == (0, "verify_sealed: sealed v1/latest ok, 36 rates\n")

    publish(tmp_path, snapshot(), issued=int(time.time()) - 2 * 3600)
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)
    assert run(monkeypatch, capsys, tmp_path, "--max-age", "86400") == (0, "verify_sealed: sealed v1/latest ok, 37 rates\n")

    publish(tmp_path, snapshot(), sealer=gs.Sealer(MASTER, OTHER))
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)
    publish(tmp_path, snapshot(), sealer=gs.Sealer(MASTER, SIGNING, kid=2))
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)

    rates = snapshot()
    rates["source"] = "other"
    publish(tmp_path, rates)
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)
    dup = snapshot()
    dup["rates"][0]["code"] = dup["rates"][1]["code"]
    publish(tmp_path, dup)
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)

    sealed = publish(tmp_path, snapshot())
    env = json.loads(sealed.read_text(encoding="utf-8"))
    ct = bytearray(base64.b64decode(env["ciphertext"]))
    ct[3] ^= 0x10
    env["ciphertext"] = base64.b64encode(bytes(ct)).decode()
    sealed.write_text(json.dumps(env), encoding="utf-8")
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)
    sealed.write_text("{not json", encoding="utf-8")
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)
    sealed.write_text("x" * (gs.MAX_ENVELOPE_BYTES + 1), encoding="utf-8")
    assert run(monkeypatch, capsys, tmp_path) == (1, failed)


def test_production_public_key_constant_is_a_valid_ed25519_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    raw = base64.b64decode(vs.PUBLIC_KEY_B64)
    assert len(raw) == 32 and Ed25519PublicKey.from_public_bytes(raw)
    assert vs.LOGICAL == "v1/latest" and vs.EXPECTED_RATES == 37 and vs.MAX_AGE_SECONDS == 900
