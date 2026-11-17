import base64
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import accuracy_report
import night_export


def test_keygen_prints_only_public_key_and_writes_private_0600(tmp_path, capsys):
    private = tmp_path / "owner.key"
    assert night_export.main(["keygen", "--private-out", str(private)]) == 0
    printed = capsys.readouterr().out.strip()
    assert len(base64.b64decode(printed)) == 32
    assert stat.S_IMODE(os.stat(private).st_mode) == 0o600
    assert printed not in private.read_text()


def test_keygen_refuses_overwrite(tmp_path, capsys):
    private = tmp_path / "owner.key"
    private.write_text("keep")
    assert night_export.main(["keygen", "--private-out", str(private)]) == 1
    assert private.read_text() == "keep"
    assert "FileExistsError" in capsys.readouterr().err


def test_round_trip_and_no_stdout(tmp_path, capsys):
    private = tmp_path / "owner.key"
    public = night_export.keygen(private)
    payload = json.dumps({"codes": {"alpha": {"x": 1}}}).encode()
    sealed = tmp_path / "report.bin"
    sealed.write_bytes(accuracy_report.encrypt_report(public, payload))
    out = tmp_path / "plain.json"
    capsys.readouterr()
    code = night_export.main(["decrypt", "--private", str(private), "--in", str(sealed), "--out", str(out)])
    captured = capsys.readouterr()
    assert code == 0
    assert out.read_bytes() == payload
    assert captured.out == "" and "alpha" not in captured.err
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600


def test_fresh_ephemeral_key_each_time(tmp_path):
    public = night_export.keygen(tmp_path / "k")
    a = accuracy_report.encrypt_report(public, b"same")
    b = accuracy_report.encrypt_report(public, b"same")
    assert a != b


def test_wrong_key_and_corrupt_fail_quietly(tmp_path, capsys):
    one, two = tmp_path / "one", tmp_path / "two"
    public = night_export.keygen(one)
    night_export.keygen(two)
    sealed = tmp_path / "r.bin"
    sealed.write_bytes(accuracy_report.encrypt_report(public, b"secret-body"))
    out = tmp_path / "o.json"
    assert night_export.main(["decrypt", "--private", str(two), "--in", str(sealed), "--out", str(out)]) == 1
    assert not out.exists()
    sealed.write_bytes(b"!!!")
    assert night_export.main(["decrypt", "--private", str(one), "--in", str(sealed), "--out", str(out)]) == 1
    assert "secret-body" not in capsys.readouterr().err


def test_decrypt_tightens_existing_output_mode(tmp_path):
    private = tmp_path / "k"
    public = night_export.keygen(private)
    sealed = tmp_path / "r.bin"
    sealed.write_bytes(accuracy_report.encrypt_report(public, b"{}"))
    out = tmp_path / "plain.json"
    out.write_text("old")
    os.chmod(out, 0o644)
    night_export.main(["decrypt", "--private", str(private), "--in", str(sealed), "--out", str(out)])
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
