from __future__ import annotations

import argparse
import json
import os
import sys

import headline_log
from news_eval import CONFIDENCE_RANK, LABELS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Decrypt the headline log into a labels template")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--predictions", required=True)
    args = ap.parse_args(argv)
    master = headline_log.master_key(os.environ)
    if master is None:
        print("error: GHEYMAT_PAYLOAD_KEY missing or invalid", file=sys.stderr)
        return 2
    try:
        rows = headline_log.read_rows(args.state_dir, headline_log.derive(master))
    except (headline_log.LogError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    skipped = 0
    preds = []
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({"id": r.get("id"), "title": r.get("title"), "category": r.get("category"),
                                 "model_effect": r.get("model_effect"),
                                 "model_confidence": r.get("model_confidence"), "effect": ""},
                                ensure_ascii=False) + "\n")
            if r.get("model_effect") in LABELS and r.get("model_confidence") in CONFIDENCE_RANK:
                preds.append({"id": r["id"], "effect": r["model_effect"], "confidence": r["model_confidence"]})
            else:
                skipped += 1
    with open(args.predictions, "w", encoding="utf-8") as fh:
        for p in preds:
            fh.write(json.dumps(p) + "\n")
    print(f"exported {len(rows)} rows, {len(preds)} predictions, {skipped} without a model effect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
