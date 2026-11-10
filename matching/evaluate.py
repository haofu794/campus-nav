"""Offline evaluation: is the ranking actually good?

Step 1 -- make a labeling sheet (top matches + random jobs, so it's not biased
          toward what the current ranker already likes):
    python -m matching.evaluate sample
  Open data/labels.csv and fill `label`: 2 = would apply, 1 = maybe, 0 = no.

Step 2 -- compare ranking variants on the labeled jobs:
    python -m matching.evaluate

NDCG@k (Normalized Discounted Cumulative Gain):
    DCG@k  = sum_{i=1..k} (2^rel_i - 1) / log2(i + 1)
    NDCG@k = DCG@k / DCG@k of the perfect order
  - 2^rel - 1: a "2" (gain 3) counts 3x a "1" (gain 1), so strong matches matter more.
  - log2(i+1): position 1 divides by 1, position 3 by 2. Mistakes at the top hurt most.
  Example, labels in ranked order [2, 0, 1]:
    DCG  = 3/1 + 0/1.585 + 1/2 = 3.5
    ideal [2, 1, 0]: 3/1 + 1/1.585 + 0/2 = 3.631
    NDCG = 3.5 / 3.631 = 0.964
"""
import csv
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEATS = ROOT / "data" / "rank_debug.json"
LABELS = ROOT / "data" / "labels.csv"

VARIANTS = {
    "skill_only": {"skill": 1},
    "bm25_only": {"bm25": 1},
    "emb_only": {"emb": 1},
    "bm25+emb": {"bm25": 0.5, "emb": 0.5},
    "combined": None,  # the real weights from config/my_prefs.json
}


def ndcg(rels, k):
    dcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))
    ideal = sorted(rels, reverse=True)
    idcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(ideal[:k]))
    return dcg / idcg if idcg else 0.0


def sample(n_top=50, n_rand=50):
    # Never overwrite a sheet that already has labels in it: that's hours of work.
    if LABELS.exists():
        with LABELS.open(encoding="utf-8-sig") as f:
            if any(r.get("label", "").strip() for r in csv.DictReader(f)):
                sys.exit(f"{LABELS} already has labels; rename or delete it first if you really want a new sheet")
    debug = json.loads(FEATS.read_text(encoding="utf-8"))
    jobs = {j["id"]: j for j in json.loads((ROOT / "web" / "data.json").read_text(encoding="utf-8"))["jobs"]}
    rows = sorted(debug.values(), key=lambda r: r["match"], reverse=True)
    picks = rows[:n_top] + random.sample(rows[n_top:], min(n_rand, len(rows) - n_top))
    random.shuffle(picks)  # don't let the order hint at the model's opinion
    # The match score is deliberately NOT in the sheet: seeing "87" would nudge
    # the label toward what the model already thinks.
    with LABELS.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["label", "company", "title", "recruit", "cities", "direction", "skills", "url", "id"])
        for r in picks:
            j = jobs.get(r["id"], {})
            w.writerow(["", r["company"], r["title"], j.get("recruit", ""),
                        "/".join(j.get("cities", [])[:4]), j.get("direction", ""),
                        ", ".join(j.get("skills", [])[:8]), j.get("url", ""), r["id"]])
    print(f"wrote {LABELS} with {len(picks)} rows -- fill the label column (0/1/2)")


def evaluate(weights):
    debug = json.loads(FEATS.read_text(encoding="utf-8"))
    labels = {}
    with LABELS.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["label"].strip() and row["id"] in debug:
                labels[row["id"]] = int(row["label"])
    if not labels:
        sys.exit("no labeled rows yet")
    print(f"{len(labels)} labeled jobs")
    for name, w in VARIANTS.items():
        w = w or weights
        if any(debug[i].get(k) is None for i in labels for k in w if w[k]):
            print(f"  {name:<11} skipped (feature missing, e.g. run without fastembed)")
            continue
        scored = sorted(labels, key=lambda i: sum(w.get(k, 0) * debug[i][k] for k in w), reverse=True)
        rels = [labels[i] for i in scored]
        print(f"  {name:<11} NDCG@10={ndcg(rels, 10):.3f}  NDCG@20={ndcg(rels, 20):.3f}")


if __name__ == "__main__":
    if sys.argv[1:] == ["sample"]:
        sample()
    else:
        prefs = json.loads((ROOT / "config" / "my_prefs.json").read_text(encoding="utf-8"))
        from matching.rank import DEFAULT_WEIGHTS
        evaluate({**DEFAULT_WEIGHTS, **prefs.get("weights", {})})
