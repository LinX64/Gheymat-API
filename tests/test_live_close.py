import base64
import pathlib
import sys
from datetime import datetime, timezone

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import live_close as lc

KEY_TEXT = base64.b64encode(bytes(range(32))).decode()
OTHER_TEXT = base64.b64encode(bytes(range(1, 33))).decode()
KEY = lc.derive_key({lc.ENV_KEY: KEY_TEXT})
OTHER = lc.derive_key({lc.ENV_KEY: OTHER_TEXT})
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh():
    lc._warned = False
    yield


def test_last_write_wins_within_day(tmp_path):
    assert lc.record(tmp_path, "2026-11-09", {"alpha": 123456.5, "beta": 7.25}, KEY)
    assert lc.record(tmp_path, "2026-11-09", {"alpha": 130000.0}, KEY)
    assert lc.read(tmp_path, KEY) == {"2026-11-09": {"alpha": 130000.0, "beta": 7.25}}


def test_new_day_appends(tmp_path):
    lc.record(tmp_path, "2026-11-08", {"alpha": 1.5}, KEY)
    lc.record(tmp_path, "2026-11-09", {"alpha": 2.5}, KEY)
    assert lc.read(tmp_path, KEY) == {"2026-11-08": {"alpha": 1.5}, "2026-11-09": {"alpha": 2.5}}


def test_unchanged_does_not_rewrite(tmp_path):
    lc.record(tmp_path, "2026-11-09", {"alpha": 1.5}, KEY)
    before = (tmp_path / lc.FILE_NAME).read_bytes()
    assert lc.record(tmp_path, "2026-11-09", {"alpha": 1.5}, KEY) is False
    assert (tmp_path / lc.FILE_NAME).read_bytes() == before


def test_only_finite_positive_recorded(tmp_path):
    bad = {"a": 0, "b": -1, "c": float("nan"), "d": float("inf"), "e": True, "f": "9", "g": None}
    assert lc.record(tmp_path, "2026-11-09", bad, KEY) is False
    assert not (tmp_path / lc.FILE_NAME).exists()
    assert lc.record(tmp_path, "2026-11-09", {**bad, "alpha": 3.5}, KEY)
    assert lc.read(tmp_path, KEY) == {"2026-11-09": {"alpha": 3.5}}


def test_ciphertext_on_disk(tmp_path):
    lc.record(tmp_path, "2026-11-09", {"alpha": 123456.75}, KEY)
    raw = (tmp_path / lc.FILE_NAME).read_bytes()
    raw.decode("ascii")
    plain = base64.b64decode(raw)
    for needle in (b"alpha", b"123456", b"2026"):
        assert needle not in raw and needle not in plain
    assert not list(tmp_path.glob(".tmp-*"))


def test_fresh_nonce_each_write(tmp_path):
    lc.record(tmp_path, "2026-11-09", {"alpha": 1.5}, KEY)
    first = (tmp_path / lc.FILE_NAME).read_bytes()
    lc.record(tmp_path, "2026-11-09", {"alpha": 2.5}, KEY)
    assert (tmp_path / lc.FILE_NAME).read_bytes()[:16] != first[:16]


def test_wrong_key_backup_once_and_skip(tmp_path):
    lc.record(tmp_path, "2026-11-09", {"alpha": 1.5}, KEY)
    original = (tmp_path / lc.FILE_NAME).read_bytes()
    assert lc.record(tmp_path, "2026-11-10", {"alpha": 2.5}, OTHER) is False
    backup = tmp_path / (lc.FILE_NAME + ".corrupt")
    assert backup.read_bytes() == original
    assert (tmp_path / lc.FILE_NAME).read_bytes() == original
    backup.write_bytes(b"sentinel")
    assert lc.record(tmp_path, "2026-11-11", {"alpha": 3.5}, OTHER) is False
    assert backup.read_bytes() == b"sentinel"
    assert lc.read(tmp_path, OTHER) == {}
    assert lc.read(tmp_path, KEY) == {"2026-11-09": {"alpha": 1.5}}


def test_corrupt_file_kept(tmp_path):
    (tmp_path / lc.FILE_NAME).write_bytes(b"\xff\xfe garbage")
    assert lc.record(tmp_path, "2026-11-09", {"alpha": 1.5}, KEY) is False
    assert (tmp_path / (lc.FILE_NAME + ".corrupt")).read_bytes() == b"\xff\xfe garbage"
    assert (tmp_path / lc.FILE_NAME).read_bytes() == b"\xff\xfe garbage"


def test_refuses_to_shrink(tmp_path, monkeypatch):
    for i in range(1, 6):
        lc.record(tmp_path, f"2026-11-0{i}", {"alpha": float(i)}, KEY)
    before = (tmp_path / lc.FILE_NAME).read_bytes()
    monkeypatch.setattr(lc, "MAX_DAYS", 2)
    assert lc.record(tmp_path, "2026-11-09", {"alpha": 9.5}, KEY) is False
    assert (tmp_path / lc.FILE_NAME).read_bytes() == before


def test_three_year_cap_drops_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "MAX_DAYS", 3)
    for i in range(1, 6):
        lc.record(tmp_path, f"2026-11-0{i}", {"alpha": float(i)}, KEY)
    assert sorted(lc.read(tmp_path, KEY)) == ["2026-11-03", "2026-11-04", "2026-11-05"]
    assert lc.MAX_DAYS == 3
    monkeypatch.undo()
    assert lc.MAX_DAYS == 1096


def test_older_day_beyond_cap_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "MAX_DAYS", 2)
    lc.record(tmp_path, "2026-11-02", {"alpha": 1.0}, KEY)
    lc.record(tmp_path, "2026-11-03", {"alpha": 1.0}, KEY)
    before = (tmp_path / lc.FILE_NAME).read_bytes()
    assert lc.record(tmp_path, "2026-11-01", {"alpha": 2.0}, KEY) is False
    assert (tmp_path / lc.FILE_NAME).read_bytes() == before
    assert lc.record(tmp_path, "2026-11-04", {"alpha": 2.0}, KEY) is True
    assert sorted(lc.read(tmp_path, KEY)) == ["2026-11-03", "2026-11-04"]


def test_no_key_is_quiet_noop(tmp_path):
    logs = []
    env = {lc.ENV_STATE: str(tmp_path)}
    assert lc.day_hook(env, NOW, {"alpha": 1.5}, logs.append) is False
    assert lc.day_hook(env, NOW, {"alpha": 1.5}, logs.append) is False
    assert logs == ["live-close: off (no key)"]
    assert lc.record(tmp_path, "2026-11-09", {"alpha": 1.5}, None) is False
    assert lc.read(tmp_path, None) == {}
    assert not list(tmp_path.iterdir())


def test_hook_needs_state_dir(tmp_path):
    logs = []
    assert lc.day_hook({lc.ENV_KEY: KEY_TEXT}, NOW, {"alpha": 1.5}, logs.append) is False
    assert logs == []


def test_hook_records_tehran_day(tmp_path):
    env = {lc.ENV_STATE: str(tmp_path), lc.ENV_KEY: KEY_TEXT}
    late = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)
    assert lc.day_hook(env, late, {"alpha": 1.5}, print)
    import gheymat_ai
    assert list(lc.read(tmp_path, KEY)) == [gheymat_ai.default_today(late).isoformat()]


def test_hook_swallows_every_exception(tmp_path, monkeypatch):
    env = {lc.ENV_STATE: str(tmp_path), lc.ENV_KEY: KEY_TEXT}

    def boom(*a, **k):
        raise RuntimeError("secret 999")

    monkeypatch.setattr(lc, "record", boom)
    assert lc.day_hook(env, NOW, {"alpha": 1.5}, print) is False
    monkeypatch.undo()
    assert lc.day_hook(None, NOW, {}, print) is False
    assert lc.day_hook(env, "bad", {"alpha": 1.5}, print) is False
    assert lc.day_hook(env, NOW, None, print) is False
    assert lc.day_hook(env, NOW, {"alpha": 1.5}, lambda m: 1 / 0) is True
    lc._warned = False
    assert lc.day_hook({lc.ENV_STATE: str(tmp_path)}, NOW, {"alpha": 1.5}, lambda m: 1 / 0) is False


def test_hook_does_not_change_prices(tmp_path):
    env = {lc.ENV_STATE: str(tmp_path), lc.ENV_KEY: KEY_TEXT}
    prices = {"alpha": 1.5, "beta": 2.5}
    snapshot = dict(prices)
    lc.day_hook(env, NOW, prices, print)
    assert prices == snapshot


def test_snapshot_hook_wrapped_and_reuses_prices():
    text = (TOOLS / "gheymat_snapshot.py").read_text()
    i = text.index("live_close.day_hook")
    block = text[text.rindex("if args.ai:", 0, i):i]
    assert "try:" in block and "live_prices" in block
    assert "live_prices_for(" in text[text.rindex("if args.ai:", 0, i):i].split("gheymat_ai.run_step")[0]
    assert "lead_samples" not in text
