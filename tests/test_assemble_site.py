"""Versioned site: registry, headers, assembler and site verification. No network, throwaway keys only."""
import base64
import copy
import json
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import assemble_site as asm  # noqa: E402
import gheymat_seal as gs  # noqa: E402
import site_versions as sv  # noqa: E402
import verify_sealed as vs  # noqa: E402

MASTER = bytes(range(7, 39))
SIGNING = Ed25519PrivateKey.from_private_bytes(bytes(range(60, 92)))
PUBLIC = {gs.DEFAULT_KID: SIGNING.public_key()}
KEY_ENV = {"GHEYMAT_PAYLOAD_KEY": base64.b64encode(MASTER).decode(),
           "GHEYMAT_SIGNING_KEY": base64.b64encode(bytes(range(60, 92))).decode()}
SEALER = gs.Sealer(MASTER, SIGNING)
CODE = sorted(vs.all_codes())[0]
OTHER_CODE = sorted(vs.all_codes())[1]


def put(src: pathlib.Path, logical: str, obj):
    f = src / SEALER.opaque_path(logical)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(SEALER.seal(logical, obj, issued=1_000_000), separators=(",", ":")), encoding="utf-8")


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "dist"
    put(d, "v1/latest", {"rates": []})
    put(d, "v1/instruments", [])
    put(d, f"v1/history/{CODE}", {"code": CODE})
    put(d, f"v1/ai/forecast/{CODE}", {"code": CODE, "likely": 1})
    put(d, "v1/ai/brief", {"text": "x"})
    put(d, "health", {"ok": True})
    (d / "d" / "deadbeef").write_text("orphan", encoding="utf-8")
    (d / "privacy.html").write_text("p", encoding="utf-8")
    (d / ".nojekyll").write_text("", encoding="utf-8")
    return d


def snapshot_tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_registry_document_shape():
    doc = sv.registry_document("2026-11-11T00:00:00Z")
    assert doc["schema"] == 1 and doc["generatedAt"] == "2026-11-11T00:00:00Z" and doc["latest"] == "v2"
    assert doc["versions"] == [{"id": "v1", "status": "stable", "base": "/v1/"},
                               {"id": "v2", "status": "current", "base": "/v2/"}]


def test_new_version_is_one_entry():
    reg = copy.deepcopy(sv.VERSIONS) + [{"id": "v3", "status": "current", "docs": ["ai"], "derivesFrom": "v1"}]
    assert sv.registry_document("t", reg)["latest"] == "v3"
    assert "/v3/d/*" in sv.headers_text(reg)
    assert sv.transform_for("v3")("v3/ai/news", {"a": 1}) == {"a": 1}


def test_bad_registry_rejected():
    with pytest.raises(ValueError):
        sv.validate([{"id": "x1", "status": "current"}])
    with pytest.raises(ValueError):
        sv.validate([{"id": "v1", "status": "weird"}])


def test_deprecated_gets_headers():
    reg = copy.deepcopy(sv.VERSIONS)
    reg[0].update(status="deprecated", deprecatedAt="2027-01-01", sunsetAt="2027-06-30")
    text = sv.headers_text(reg)
    assert "/v1/*\n  Deprecation: @1798761600\n  Sunset: Wed, 30 Jun 2027 00:00:00 GMT\n" in text
    assert "/v2/*" not in text
    doc = sv.registry_document("t", reg)
    assert doc["versions"][0]["sunsetAt"] == "2027-06-30"
    assert "Deprecation" not in sv.headers_text()


def test_headers_cover_root_and_versions():
    text = sv.headers_text()
    for path in ("/*", "/d/*", "/v1/d/*", "/v2/d/*", "/versions.json"):
        assert f"\n{path}\n" in "\n" + text
    assert "X-Content-Type-Options: nosniff" in text and "Referrer-Policy: no-referrer" in text
    assert text.count("Access-Control-Allow-Origin: *") == 4


def test_assemble_legacy_untouched_and_v1_identical(src, tmp_path):
    before = snapshot_tree(src)
    out = tmp_path / "site"
    result = asm.assemble(src, out, SEALER, now_iso="2026-11-11T00:00:00Z", log=lambda *_: None)
    assert snapshot_tree(src) == before
    site = snapshot_tree(out)
    assert not any(k.startswith(".nojekyll") for k in site)
    for k, v in before.items():
        if k != ".nojekyll":
            assert site[k] == v  # root d/ and pages stay
    for logical in ("v1/latest", "v1/instruments", f"v1/history/{CODE}"):
        name = SEALER.opaque_path(logical)
        assert site[f"v1/{name}"] == before[name]
    assert result["counts"] == {"v1": 5, "v2": 2}
    assert result["orphans"] == 1


def test_v2_docs_bind_to_their_logical_path(src, tmp_path):
    out = tmp_path / "site"
    asm.assemble(src, out, SEALER, log=lambda *_: None)
    for rel in (f"ai/forecast/{CODE}", "ai/brief"):
        f = out / "v2" / SEALER.opaque_path(f"v2/{rel}")
        env = json.loads(f.read_text(encoding="utf-8"))
        assert gs.open_envelope(env, MASTER, PUBLIC, f"v2/{rel}", max_age=None)
        with pytest.raises(gs.EnvelopeError):
            gs.open_envelope(env, MASTER, PUBLIC, f"v1/{rel}", max_age=None)
    v1 = json.loads((out / "v1" / SEALER.opaque_path("v1/ai/brief")).read_text(encoding="utf-8"))
    with pytest.raises(gs.EnvelopeError):
        gs.open_envelope(v1, MASTER, PUBLIC, "v2/ai/brief", max_age=None)
    assert not (out / "v2" / SEALER.opaque_path(f"v2/ai/forecast/{OTHER_CODE}")).exists()
    assert not (out / "v2" / SEALER.opaque_path("v2/ai/news")).exists()


def test_site_verification(src, tmp_path):
    out = tmp_path / "site"
    asm.assemble(src, out, SEALER, log=lambda *_: None)
    assert vs.verify_site(out, MASTER, PUBLIC) == {"v1": 5, "v2": 2}
    victim = out / "v1" / SEALER.opaque_path("v1/latest")
    victim.write_bytes(victim.read_bytes() + b" ")
    with pytest.raises(ValueError):
        vs.verify_site(out, MASTER, PUBLIC)


def test_cli_missing_key_exits_nonzero(src, tmp_path, monkeypatch, capsys):
    for k in KEY_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["assemble_site.py", "--src", str(src), "--out", str(tmp_path / "site")])
    assert asm.main() != 0
    err = capsys.readouterr()
    assert KEY_ENV["GHEYMAT_PAYLOAD_KEY"] not in err.out + err.err
    assert not (tmp_path / "site").exists()


def test_cli_ok_and_missing_core_fails(src, tmp_path, monkeypatch, capsys):
    for k, v in KEY_ENV.items():
        monkeypatch.setenv(k, v)
    out = tmp_path / "site"
    monkeypatch.setattr(sys, "argv", ["assemble_site.py", "--src", str(src), "--out", str(out)])
    assert asm.main() == 0
    text = capsys.readouterr()
    assert "v1 5 files, v2 2 files" in text.out and KEY_ENV["GHEYMAT_PAYLOAD_KEY"] not in text.out + text.err
    (src / SEALER.opaque_path("v1/latest")).unlink()
    assert asm.main() != 0


@pytest.mark.parametrize("relative", ["same", "inside", "parent"])
def test_out_must_be_separate(src, relative):
    out = {"same": src, "inside": src / "site", "parent": src.parent}[relative]
    with pytest.raises(SystemExit):
        asm.assemble(src, out, SEALER)
    assert (src / "privacy.html").exists()


def test_no_source_names_anywhere(src, tmp_path):
    out = tmp_path / "site"
    asm.assemble(src, out, SEALER, log=lambda *_: None)
    texts = [(out / "versions.json").read_text(), (out / "_headers").read_text()]
    texts += [(TOOLS / n).read_text() for n in ("site_versions.py", "assemble_site.py")]
    for text in texts:
        assert "hansha" not in text.lower() and "bonbast" not in text.lower()
