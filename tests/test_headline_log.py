import base64
import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gheymat_news as news
import headline_export as export
import headline_log as hl
import news_eval

KEY = base64.b64encode(bytes(range(32))).decode()
OTHER = base64.b64encode(bytes(range(1, 33))).decode()
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def row(i, title=None, effect="usd_up", conf="high"):
    return {"id": f"{i:016x}", "title": title or f"Headline number {i}", "category": "general", "model_effect": effect,
            "model_confidence": conf, "model": "m", "ranking_version": 1}


def env_for(tmp_path, key=KEY):
    e = {"GHEYMAT_STATE_DIR": str(tmp_path)}
    if key:
        e["GHEYMAT_PAYLOAD_KEY"] = key
    return e


@pytest.fixture(autouse=True)
def fresh_warning():
    hl._warned = False
    news.CAPTURED.clear()
    yield
    news.CAPTURED.clear()


def key_of(k=KEY):
    return hl.derive(hl.master_key({"GHEYMAT_PAYLOAD_KEY": k}))


def test_round_trip_export(tmp_path, monkeypatch, capsys):
    out = []
    hl.collect([row(1), row(2, effect="unclear", conf="low"), row(3, effect=None, conf=None)], env_for(tmp_path), NOW, out.append)
    assert out == ["Headline log: 3 rows since 2026-11-09"]
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", KEY)
    labels, preds = tmp_path / "l.jsonl", tmp_path / "p.jsonl"
    assert export.main(["--state-dir", str(tmp_path), "--out", str(labels), "--predictions", str(preds)]) == 0
    assert "1 without a model effect" in capsys.readouterr().out
    got = [json.loads(x) for x in labels.read_text().splitlines()]
    assert [g["effect"] for g in got] == ["", "", ""] and got[0]["title"] == "Headline number 1"
    assert set(got[0]) == {"id", "title", "category", "model_effect", "model_confidence", "effect"}
    assert len(news_eval.load_predictions(preds)) == 2


def test_dedupe_across_appends(tmp_path):
    k = key_of()
    hl.append(tmp_path, [row(1), row(1)], k, NOW)
    kept = hl.append(tmp_path, [row(1), row(2)], k, NOW)
    assert [r["id"] for r in kept] == [row(1)["id"], row(2)["id"]]


def test_cap_drops_oldest(tmp_path):
    k = key_of()
    hl.append(tmp_path, [row(i) for i in range(hl.MAX_ROWS)], k, NOW)
    kept = hl.append(tmp_path, [row(99999)], k, NOW)
    assert len(kept) == hl.MAX_ROWS and kept[0]["id"] == row(1)["id"] and kept[-1]["id"] == row(99999)["id"]


def test_ciphertext_only_at_rest(tmp_path):
    hl.append(tmp_path, [row(1, title="Secret headline words")], key_of(), NOW)
    raw = (tmp_path / hl.FILE_NAME).read_bytes()
    assert b"Secret" not in raw and b"headline" not in raw.lower().replace(b"headline-log", b"")
    assert not list(tmp_path.glob("*.tmp"))


def test_wrong_key_fails_cleanly(tmp_path, monkeypatch, capsys):
    hl.append(tmp_path, [row(1)], key_of(), NOW)
    with pytest.raises(hl.LogError):
        hl.read_rows(tmp_path, key_of(OTHER))
    monkeypatch.setenv("GHEYMAT_PAYLOAD_KEY", OTHER)
    assert export.main(["--state-dir", str(tmp_path), "--out", str(tmp_path / "x")]) == 2
    assert "wrong key or corrupt" in capsys.readouterr().err
    monkeypatch.delenv("GHEYMAT_PAYLOAD_KEY")
    assert export.main(["--state-dir", str(tmp_path)]) == 2


def test_missing_key_off_warns_once(tmp_path):
    out = []
    env = env_for(tmp_path, key=None)
    hl.collect([row(1)], env, NOW, out.append)
    hl.collect([row(2)], env, NOW, out.append)
    assert out == ["Headline log: off (no key)"]
    assert not (tmp_path / hl.FILE_NAME).exists()
    bad = env_for(tmp_path, key="not-base64!")
    hl._warned = False
    hl.collect([row(1)], bad, NOW, out.append)
    assert out[-1] == "Headline log: off (no key)"


def test_unset_state_dir_is_noop(tmp_path):
    out = []
    hl.collect([row(1)], {"GHEYMAT_PAYLOAD_KEY": KEY}, NOW, out.append)
    hl.collect([row(1)], {"GHEYMAT_PAYLOAD_KEY": KEY, "GHEYMAT_STATE_DIR": ""}, NOW, out.append)
    assert out == []


def test_path_never_under_published_dirs():
    p = hl.log_path("/state/loop").as_posix()
    assert "/dist/" not in p and "/site/" not in p
    assert hl.FILE_NAME not in "".join(x.name for x in (TOOLS.parent / "dist", TOOLS.parent / "site") if x.exists())


def test_exception_swallowed(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    out = []
    hl.collect([row(1)], env_for(blocker), NOW, out.append)
    assert len(out) == 1 and out[0].startswith("Headline log: skipped (") and out[0].endswith(")")


ITEM = {"title": "Dollar climbs on rate talk", "desc": "", "category": "markets"}


def payload(effect="usd_up", confidence="high"):
    body = json.dumps({"en": "Dollar climbs.", "fa": "دلار بالا رفت.", "effect": effect, "confidence": confidence})
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": body}]}


def test_hook_captures_shadow_without_changing_result():
    assert news.TAGS_ENABLED is False
    got = news.parse_output(payload(), dict(ITEM))
    assert got == {"en": "Dollar climbs.", "fa": "دلار بالا رفت.", "effect": None, "shadowEffect": "usd_up"}
    (c,) = news.CAPTURED
    assert c["model_effect"] == "usd_up" and c["model_confidence"] == "high" and c["category"] == "markets"
    assert c["model"] == news.MODEL and c["ranking_version"] == news.RANKING_VERSION
    assert set(c) == {"id", "title", "category", "model_effect", "model_confidence", "model", "ranking_version"}
    assert len(c["id"]) == 16 and "http" not in json.dumps(c)


def test_hook_keeps_raw_low_confidence_and_unclear():
    got = news.parse_output(payload("unclear", "low"), dict(ITEM))
    assert got["shadowEffect"] is None
    assert news.CAPTURED[0]["model_effect"] == "unclear" and news.CAPTURED[0]["model_confidence"] == "low"
