import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import news_eval as ne


def write(path, rows):
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
    return str(path)


def test_perfect():
    r = ne.score([("usd_up", "usd_up", "high"), ("neutral", "neutral", "low")])
    assert r["n"] == 2 and r["accuracy"] == 1.0
    assert r["precision"]["usd_up"] == 1.0 and r["recall"]["neutral"] == 1.0


def test_all_wrong():
    r = ne.score([("usd_up", "usd_down", "high"), ("usd_down", "usd_up", "high")])
    assert r["accuracy"] == 0.0
    assert r["precision"]["usd_up"] == 0.0 and r["recall"]["usd_up"] == 0.0


def test_mixed_hand_computed():
    pairs = [("usd_up", "usd_up", "high"), ("usd_up", "neutral", "low"),
             ("neutral", "neutral", "high"), ("neutral", "usd_up", "high")]
    r = ne.score(pairs)
    assert r["accuracy"] == 0.5
    assert r["precision"]["usd_up"] == 0.5 and r["recall"]["usd_up"] == 0.5
    assert r["precision"]["neutral"] == 0.5 and r["recall"]["neutral"] == 0.5
    assert r["high_confidence"] == {"n": 3, "accuracy": 2 / 3}


def test_never_predicted_class_precision_none():
    r = ne.score([("gold_up", "neutral", "low"), ("neutral", "neutral", "low")])
    assert r["precision"]["gold_up"] is None
    assert r["recall"]["gold_up"] == 0.0


def test_empty_pairs():
    r = ne.score([])
    assert r["n"] == 0 and r["accuracy"] is None
    assert r["high_confidence"] == {"n": 0, "accuracy": None}
    assert not ne.passes(r, min_n=0)


def test_high_confidence_slice_and_threshold():
    pairs = [("usd_up", "usd_up", "high"), ("usd_up", "gold_up", "low")]
    assert ne.score(pairs)["high_confidence"] == {"n": 1, "accuracy": 1.0}
    assert ne.score(pairs, threshold="low")["high_confidence"] == {"n": 2, "accuracy": 0.5}


def test_vocabulary_matches_news_module():
    assert "unclear" in ne.LABELS and "neutral" in ne.LABELS


def test_load_labels_ok_skips_blank(tmp_path):
    p = write(tmp_path / "l.jsonl", [{"id": "a", "effect": "usd_up"}, "", {"id": "b", "effect": "unclear"}])
    assert [r["id"] for r in ne.load_labels(p)] == ["a", "b"]


@pytest.mark.parametrize("rows,needle", [
    ([{"id": "a", "effect": "usd_up"}, {"id": "b", "effect": "sideways"}], "line 2"),
    ([{"id": "a", "effect": "usd_up"}, {"id": "a", "effect": "usd_up"}], "line 2"),
    ([{"id": "a", "effect": "usd_up"}, "[1]"], "line 2"),
    (["", "not json"], "line 2"),
    ([{"id": "", "effect": "usd_up"}], "line 1"),
    ([{"id": "a", "effect": None}], "line 1"),
])
def test_load_labels_errors(tmp_path, rows, needle):
    with pytest.raises(ValueError, match=needle):
        ne.load_labels(write(tmp_path / "l.jsonl", rows))


def test_load_labels_empty(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text("\n\n")
    with pytest.raises(ValueError, match="empty"):
        ne.load_labels(str(p))


def result(n, acc, hc_acc):
    return {"n": n, "accuracy": acc, "high_confidence": {"n": 50, "accuracy": hc_acc}}


def test_passes_thresholds():
    assert ne.passes(result(200, 0.8, 0.9))
    assert not ne.passes(result(199, 1.0, 1.0))
    assert not ne.passes(result(200, 0.79, 1.0))
    assert not ne.passes(result(200, 0.9, 0.89))
    assert not ne.passes(result(200, 0.9, None))
    assert ne.passes(result(5, 0.8, 0.9), min_n=5)


def test_passes_needs_enough_high_confidence_items():
    thin = {"n": 200, "accuracy": 0.9, "high_confidence": {"n": 49, "accuracy": 1.0}}
    assert not ne.passes(thin)
    assert ne.passes(thin, min_high_confidence_n=49)


def test_high_confidence_slice_skips_unclear_predictions():
    pairs = [("unclear", "unclear", "high"), ("usd_up", "usd_down", "high")]
    r = ne.score(pairs)
    assert r["accuracy"] == 0.5
    assert r["high_confidence"] == {"n": 1, "accuracy": 0.0}


def make_files(tmp_path, n, wrong=0):
    labels = [{"id": f"i{k}", "effect": "usd_up"} for k in range(n)]
    preds = [{"id": f"i{k}", "effect": "usd_down" if k < wrong else "usd_up", "confidence": "high"}
             for k in range(n)]
    return write(tmp_path / "l.jsonl", labels), write(tmp_path / "p.jsonl", preds)


def test_cli_exit_codes(tmp_path, capsys):
    lab, pred = make_files(tmp_path, 200)
    assert ne.main(["--labels", lab, "--predictions", pred]) == 0
    assert capsys.readouterr().out.startswith("PASS")
    lab, pred = make_files(tmp_path, 200, wrong=100)
    assert ne.main(["--labels", lab, "--predictions", pred]) == 1
    assert ne.main(["--labels", str(tmp_path / "missing"), "--predictions", pred]) == 2
    assert ne.main([]) == 2


def test_cli_bad_predictions(tmp_path):
    lab, _ = make_files(tmp_path, 3)
    bad = write(tmp_path / "bad.jsonl", [{"id": "i0", "effect": "usd_up", "confidence": "maybe"}])
    assert ne.main(["--labels", lab, "--predictions", bad]) == 2
    short = write(tmp_path / "short.jsonl", [{"id": "i0", "effect": "usd_up", "confidence": "high"}])
    assert ne.main(["--labels", lab, "--predictions", short]) == 2
