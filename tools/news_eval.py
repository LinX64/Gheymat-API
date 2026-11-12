"""Offline labelled eval for the AI news effect tags. No model calls, no network.

Gate for enabling tags: see TAGS_ENABLED in gheymat_news. Labels and predictions are JSON Lines.
Run on the private labelled set: python tools/news_eval.py --labels L.jsonl --predictions P.jsonl
(exit 0 = gate passed, 1 = failed, 2 = bad input).
"""
import argparse
import json
import sys

from gheymat_news import EFFECTS

LABELS = tuple(EFFECTS) + ("unclear",)  # the schema's effect enum
CONFIDENCE_RANK = {"low": 0, "high": 1}  # the schema's confidence enum
DEFAULT_THRESHOLD = "high"  # parse_output only trusts confidence == "high"


def _read_jsonl(path, what):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                raise ValueError(f"{what} line {no}: invalid JSON") from None
            if not isinstance(obj, dict):
                raise ValueError(f"{what} line {no}: not an object")
            rows.append((no, obj))
    if not rows:
        raise ValueError(f"{what}: file is empty")
    return rows


def _check_id_effect(no, obj, what, seen):
    i = obj.get("id")
    if not isinstance(i, str) or not i:
        raise ValueError(f"{what} line {no}: id must be a non-empty string")
    if obj.get("effect") not in LABELS:
        raise ValueError(f"{what} line {no}: unknown effect {obj.get('effect')!r}")
    if i in seen:
        raise ValueError(f"{what} line {no}: duplicate id {i!r}")
    seen.add(i)


def load_labels(path) -> list[dict]:
    rows, seen = _read_jsonl(path, "labels"), set()
    for no, obj in rows:
        _check_id_effect(no, obj, "labels", seen)
    return [obj for _, obj in rows]


def load_predictions(path) -> list[dict]:
    rows, seen = _read_jsonl(path, "predictions"), set()
    for no, obj in rows:
        _check_id_effect(no, obj, "predictions", seen)
        if obj.get("confidence") not in CONFIDENCE_RANK:
            raise ValueError(f"predictions line {no}: unknown confidence {obj.get('confidence')!r}")
    return [obj for _, obj in rows]


def _ratio(num, den):
    return num / den if den else None


def score(pairs, threshold=DEFAULT_THRESHOLD) -> dict:
    """pairs: (expected, predicted, confidence).

    high_confidence covers what would be shown: confidence rank >= threshold's and a predicted effect
    other than "unclear" (those are dropped before publishing).
    """
    pairs = list(pairs)
    floor = CONFIDENCE_RANK[threshold]
    classes = sorted({p[0] for p in pairs} | {p[1] for p in pairs})
    correct = sum(1 for e, p, _ in pairs if e == p)
    precision, recall = {}, {}
    for c in classes:
        tp = sum(1 for e, p, _ in pairs if e == c and p == c)
        precision[c] = _ratio(tp, sum(1 for _, p, _ in pairs if p == c))
        recall[c] = _ratio(tp, sum(1 for e, _, _ in pairs if e == c))
    high = [(e, p) for e, p, conf in pairs if CONFIDENCE_RANK.get(conf, -1) >= floor and p in EFFECTS]
    return {
        "n": len(pairs),
        "accuracy": _ratio(correct, len(pairs)),
        "precision": precision,
        "recall": recall,
        "high_confidence": {"n": len(high), "accuracy": _ratio(sum(1 for e, p in high if e == p), len(high))},
    }


def passes(result, min_n=200, min_accuracy=0.8, min_high_confidence_accuracy=0.9,
           min_high_confidence_n=50) -> bool:
    hc = result["high_confidence"]
    if result["n"] < min_n or result["accuracy"] is None or hc["accuracy"] is None:
        return False
    if hc["n"] < min_high_confidence_n:
        return False
    return result["accuracy"] >= min_accuracy and hc["accuracy"] >= min_high_confidence_accuracy


def evaluate(labels_path, predictions_path) -> dict:
    labels = {r["id"]: r["effect"] for r in load_labels(labels_path)}
    preds = {r["id"]: r for r in load_predictions(predictions_path)}
    missing = sorted(set(labels) - set(preds))
    if missing:
        raise ValueError(f"predictions missing for {len(missing)} labelled id(s), first {missing[0]!r}")
    return score((labels[i], preds[i]["effect"], preds[i]["confidence"]) for i in labels)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--predictions", required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        res = evaluate(args.labels, args.predictions)
    except (ValueError, OSError) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 2
    ok = passes(res)
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"
    print(f"{'PASS' if ok else 'FAIL'} n={res['n']} accuracy={fmt(res['accuracy'])} "
          f"high_confidence_n={res['high_confidence']['n']} "
          f"high_confidence_accuracy={fmt(res['high_confidence']['accuracy'])}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
