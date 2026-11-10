"""Choose ranking weights from my labels without fooling myself.

    python -m matching.evaluate tune

The trap: try 66 weight combinations on my 100 labels, keep the best, report
its NDCG. That number is optimistic -- the weights were picked *because* they
scored well on exactly these 100 jobs (like grading yourself on the exam you
studied the answers for). With only 100 labels the gap can be large.

The fix is cross-validation:
  1. Split the 100 labeled jobs into 5 folds of 20 (stratified: each fold gets
     about the same mix of 0/1/2, so no fold is all "want to apply").
  2. For each fold: pick the best weights on the other 80, then score them on
     the held-out 20 the picking never saw.
  3. Average the 5 held-out scores. Repeat with 10 different random splits and
     average again, because one split of 100 items is itself noisy.
That average estimates how the *procedure* "tune weights on my labels" does on
new jobs. The baseline weights get scored on the very same held-out folds, so
the comparison is fair. If tuning helps, the final weights are fitted on all
100 labels (standard practice: CV estimates performance, the final fit uses
all data).

Grid: weights for bm25 / emb / skill go from 0 to 1 in steps of 0.1 and sum
to 1 (66 combinations), scaled to 75% of the total, times 5 avoid penalties. direction 0.15 and city
0.10 stay fixed: in the top region they are 1 for every job, so the labels
can't tell us anything about them there; they matter for coarse filtering.
"""
import random
from statistics import mean, pstdev

from .evaluate import ndcg

TUNED = ("bm25", "emb", "skill")
FIXED = {"direction": 0.15, "city": 0.10}


# Penalty for jobs that hit an avoid rule (matching/fit.py). On the same scale
# as the other weights: -0.3 cancels most of what a strong text match earns.
AVOID = (0.0, -0.1, -0.2, -0.3, -0.5)


def grid():
    steps = [i / 10 for i in range(11)]
    for b in steps:
        for e in steps:
            s = round(1 - b - e, 10)
            if s >= -1e-9:
                for a in AVOID:
                    yield {"bm25": 0.75 * b, "emb": 0.75 * e, "skill": 0.75 * max(s, 0), **FIXED, "avoid": a}


def ndcg_of(weights, ids, labels, feats, k):
    order = sorted(ids, key=lambda i: sum(w * feats[i].get(f, 0) for f, w in weights.items()), reverse=True)
    return ndcg([labels[i] for i in order], k)


def stratified_folds(ids, labels, n_folds, rng):
    by_label = {}
    for i in ids:
        by_label.setdefault(labels[i], []).append(i)
    folds = [[] for _ in range(n_folds)]
    for group in by_label.values():
        rng.shuffle(group)
        for j, i in enumerate(group):
            folds[j % n_folds].append(i)
    return folds


def best_on(ids, labels, feats, k):
    return max(grid(), key=lambda w: ndcg_of(w, ids, labels, feats, k))


def cross_validate(labels, feats, baseline, n_folds=5, repeats=10, k_select=20, k_test=10, seed=0):
    rng = random.Random(seed)
    ids = list(labels)
    scores = {"baseline": [], "tuned": [], "emb_only": [], "no_avoid": []}
    for _ in range(repeats):
        for test in stratified_folds(ids, labels, n_folds, rng):
            train = [i for i in ids if i not in set(test)]
            w = best_on(train, labels, feats, k_select)
            scores["tuned"].append(ndcg_of(w, test, labels, feats, k_test))
            scores["baseline"].append(ndcg_of(baseline, test, labels, feats, k_test))
            scores["emb_only"].append(ndcg_of({"emb": 1}, test, labels, feats, k_test))
            # Same search but with the penalty switched off: isolates what avoid adds.
            w0 = max((g for g in grid() if g["avoid"] == 0), key=lambda g: ndcg_of(g, train, labels, feats, k_select))
            scores["no_avoid"].append(ndcg_of(w0, test, labels, feats, k_test))
    return {name: (mean(v), pstdev(v)) for name, v in scores.items()}


def run(labels, feats, baseline):
    print(f"{len(labels)} labeled jobs, {len(list(grid()))} weight combinations, 10 x 5-fold CV")
    print("baseline = the current config weights")
    cv = cross_validate(labels, feats, baseline)
    print("held-out NDCG@10 (mean ± sd over 50 folds):")
    for name, (m, sd) in cv.items():
        print(f"  {name:<9} {m:.3f} ± {sd:.3f}")
    final = best_on(list(labels), labels, feats, 20)
    print("weights fitted on all labels:", {k: round(v, 3) for k, v in final.items()})
    in_sample = ndcg_of(final, list(labels), labels, feats, 20)
    print(f"  (in-sample NDCG@20 of those weights: {in_sample:.3f} -- optimistic, don't report this one)")
    return cv, final
