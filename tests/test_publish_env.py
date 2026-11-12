import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import publish_loop as pl


def test_run_returns_output_and_code():
    code, output = pl.Env().run(["echo", "hi"])
    assert code == 0 and output == "hi\n"
    code, _ = pl.Env().run(["sh", "-c", "exit 3"])
    assert code == 3


def test_run_merges_stderr():
    code, output = pl.Env().run(["sh", "-c", "echo out; echo err 1>&2"])
    assert code == 0 and "out" in output and "err" in output


def test_missing_command_is_127():
    assert pl.Env().run(["definitely-not-a-command-xyz"]) == (127, "")


def test_timeout_kills_the_whole_group(tmp_path):
    pidfile = tmp_path / "pid"
    started = time.time()
    code, _ = pl.Env().run(["sh", "-c", f"echo $$ > {pidfile}; sleep 30 & sleep 30"], timeout=1)
    assert code == 124
    assert time.time() - started < 8
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_environment_is_passed_to_the_child():
    code, output = pl.Env().run(["sh", "-c", "echo $PROBE"], env={"PATH": os.environ["PATH"], "PROBE": "yes"})
    assert code == 0 and output.strip() == "yes"


def test_clear_top_keeps_only_the_named_entries(tmp_path):
    for name in ("v1", "d", "archive", "extra"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "f").write_text("x")
    (tmp_path / "loose.txt").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "v1")
    pl.Env().clear_top(tmp_path, pl.KEPT_IN_DIST)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["archive", "d", "v1"]
    assert (tmp_path / "v1" / "f").exists()


def test_file_helpers(tmp_path):
    env = pl.Env()
    folder = tmp_path / "a" / "b"
    env.mkdir(folder)
    assert env.exists(folder)
    marker = folder / "m"
    env.touch(marker)
    assert env.exists(marker)
    marker.write_text("text")
    assert env.read_text(marker) == "text"
    moved = tmp_path / "moved"
    env.move(folder, moved)
    assert env.exists(moved / "m") and not env.exists(folder)
    env.remove(moved / "m")
    env.remove(moved / "m")
    assert not env.exists(moved / "m")
    env.rmtree(tmp_path / "a")
    assert not env.exists(tmp_path / "a")
    env.rmtree(tmp_path / "never-existed")


def test_main_smoke_without_cloudflare_or_chain(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for key in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GITHUB_REF", "GHEYMAT_LIVE_STATE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", "pk")
    monkeypatch.setenv("GHEYMAT_SIGNING_KEY", "sk")
    monkeypatch.setenv("PUBLISH_LOOP_MINUTES", "0")
    assert pl.main() == 0
    out = capsys.readouterr().out
    assert "Cloudflare deploy is off" in out


def test_main_smoke_with_a_live_state_path_that_does_not_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for key in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GITHUB_REF"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", "pk")
    monkeypatch.setenv("GHEYMAT_SIGNING_KEY", "sk")
    monkeypatch.setenv("PUBLISH_LOOP_MINUTES", "0")
    monkeypatch.setenv("GHEYMAT_LIVE_STATE", str(tmp_path / "missing" / "live.json"))
    assert pl.main() == 0


def test_main_exits_one_without_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GHEYMAT_PAYLOAD_KEY", raising=False)
    monkeypatch.delenv("GHEYMAT_SIGNING_KEY", raising=False)
    assert pl.main() == 1
