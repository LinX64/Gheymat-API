import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import live_guard as lg  # noqa: E402

CH = "<html>Just a moment...</html>"
CH2 = '<script src="/cdn-cgi/challenge-platform/x.js">'


def test_classify_matrix():
    assert lg.classify_response(403, "", None) == ("blocked", "status", None)
    assert lg.classify_response(429, "", "600") == ("blocked", "status", 600)
    assert lg.classify_response(429, "", "99999") == ("blocked", "status", 7200)
    assert lg.classify_response(429, "", "Wed, 21 Oct") == ("blocked", "status", None)
    assert lg.classify_response(429, "", None) == ("blocked", "status", None)
    assert lg.classify_response(503, "", None) == ("failed", "status", None)
    assert lg.classify_response(503, CH, None)[:2] == ("blocked", "challenge")
    assert lg.classify_response(200, CH, None)[:2] == ("blocked", "challenge")
    assert lg.classify_response(200, CH2, None)[:2] == ("blocked", "challenge")
    assert lg.classify_response(404, "", None) == ("failed", "status", None)
    assert lg.classify_response(500, "", "10") == ("failed", "status", None)
    assert lg.classify_response(200, "{}", None) == ("ok", None, None)


def test_retry_after_junk():
    assert lg.classify_response(429, "", "-5")[2] is None
    assert lg.classify_response(429, "", "0")[2] == 0
    assert lg.classify_response(429, "", "")[2] is None


def test_load_state_bad_inputs(tmp_path):
    assert lg.load_state(None, 1000) == lg.new_state()
    assert lg.load_state("", 1000) == lg.new_state()
    assert lg.load_state(str(tmp_path / "nope.json"), 1000) == lg.new_state()
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert lg.load_state(str(p), 1000) == lg.new_state()
    p.write_text("[1,2]")
    assert lg.load_state(str(p), 1000) == lg.new_state()
    p.write_text(json.dumps({"quiet_until": "x", "cool": [1], "primary_marks": "a",
                             "live_fp": 5, "evil": 1}))
    s = lg.load_state(str(p), 1000)
    assert s == lg.new_state()


def test_load_state_clamps(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "quiet_until": 10 ** 12, "cool": 1234, "evil": 1,
        "primary_marks": ["a" * 100] + [str(i) for i in range(30)] + [5],
    }))
    s = lg.load_state(str(p), 1000)
    assert s["quiet_until"] == 1000 + 7200 + 60
    assert s["cool"] == 900
    assert "evil" not in s
    assert len(s["primary_marks"]) == 16
    assert len(s["primary_marks"][0]) == 40


def test_load_state_unsafe_path(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "s.json").write_text(json.dumps({"quiet_until": 1500, "cool": 1800}))
    assert lg.load_state(str(d / "s.json"), 1000) == lg.new_state()


def test_save_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    st = lg.record_block(lg.new_state(), 1000, "status", None)
    assert lg.save_state(str(p), st) is True
    assert lg.load_state(str(p), 1000) == st
    assert [f.name for f in tmp_path.iterdir()] == ["s.json"]


def test_save_refuses_unsafe(tmp_path):
    for name in ("dist", "site"):
        d = tmp_path / name
        d.mkdir()
        assert lg.save_state(str(d / "s.json"), lg.new_state()) is False
        assert list(d.iterdir()) == []
    assert lg.save_state(None, lg.new_state()) is False
    assert lg.save_state("", lg.new_state()) is False
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    assert lg.save_state(str(link), lg.new_state()) is False
    assert real.read_text() == "{}"


def test_save_cleans_temp_on_replace_failure(tmp_path, monkeypatch):
    def boom(a, b):
        raise OSError("x")

    monkeypatch.setattr(lg.os, "replace", boom)
    assert lg.save_state(str(tmp_path / "s.json"), lg.new_state()) is False
    assert list(tmp_path.iterdir()) == []


def test_cooldown_doubling_and_retry_after():
    s = lg.new_state()
    seen = []
    for _ in range(5):
        s = lg.record_block(s, 0, "status", None)
        seen.append((s["quiet_until"], s["cool"]))
    assert seen == [(900, 1800), (1800, 3600), (3600, 7200), (7200, 7200), (7200, 7200)]
    s = lg.record_block(lg.new_state(), 100, "status", 3000)
    assert s["quiet_until"] == 3100
    s = lg.record_block(lg.new_state(), 100, "status", 7200)
    assert s["quiet_until"] == 7300
    assert lg.record_block(lg.new_state(), 0, "status", 10)["quiet_until"] == 900


def test_record_block_returns_new_and_resets_clean():
    s = lg.new_state()
    s["clean_since"] = 50
    n = lg.record_block(s, 100, "bogus", None)
    assert n is not s and s["quiet_until"] == 0
    assert n["clean_since"] == 0


def test_record_clean_resets_cool():
    s = lg.new_state()
    s["cool"] = 3600
    a = lg.record_clean(s, 1000)
    assert a["clean_since"] == 1000 and a["cool"] == 3600 and s["clean_since"] == 0
    b = lg.record_clean(a, 1000 + 7199)
    assert b["cool"] == 3600 and b["clean_since"] == 1000
    c = lg.record_clean(a, 1000 + 7200)
    assert c["cool"] == 900 and c["clean_since"] == 8200


def test_effective_order():
    order = ["live", "primary"]
    s = lg.new_state()
    s["quiet_until"] = 500
    assert lg.is_quiet(s, 499) and not lg.is_quiet(s, 500)
    assert lg.effective_order(order, "live", s, 100) == ["primary"]
    assert lg.effective_order(order, "live", s, 100, primary_short=True) == order
    out = lg.effective_order(order, "live", s, 600)
    assert out == order and out is not order


def test_frozen_check():
    s = lg.new_state()
    f, s = lg.frozen_check(s, "fp1", "m1", 0)
    assert not f
    f, s = lg.frozen_check(s, "fp1", "m2", 600)
    f, s = lg.frozen_check(s, "fp1", "m3", 1200)
    assert f is True
    # fingerprint change resets
    f, s2 = lg.frozen_check(s, "fp2", "m4", 1300)
    assert not f and s2["live_fp"] == "fp2" and s2["live_fp_since"] == 1300
    assert s2["primary_marks"] == ["m4"]
    # only two marks
    t = lg.new_state()
    _, t = lg.frozen_check(t, "a", "m1", 0)
    f, t = lg.frozen_check(t, "a", "m2", 1500)
    assert not f
    # repeated mark does not count
    u = lg.new_state()
    _, u = lg.frozen_check(u, "a", "m1", 0)
    _, u = lg.frozen_check(u, "a", "m1", 600)
    f, u = lg.frozen_check(u, "a", "m1", 1500)
    assert not f and u["primary_marks"] == ["m1"]
    # None mark adds nothing
    f, u = lg.frozen_check(u, "a", None, 1600)
    assert u["primary_marks"] == ["m1"]


def test_status_line_closed_set():
    assert lg.status_line("ok", fp="abcdefghijklmnopqrst") == "live: ok fp=abcdefghijkl"
    assert lg.status_line("failed", "format") == "live: failed format"
    assert lg.status_line("blocked", "challenge") == "live: blocked challenge"
    assert lg.status_line("blocked", "Traceback boom") == "live: blocked status"
    assert lg.status_line("failed", None) == "live: failed status"
    assert lg.status_line("quiet") == "live: quiet"
    assert lg.status_line("whatever") == "live: quiet"
