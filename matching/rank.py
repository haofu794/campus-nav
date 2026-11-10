"""Score every job for me: recall -> ranking -> re-ranking (the search/rec funnel).

  Recall   : two channels, merged.
               1. BM25 over job text (exact words: "PyTorch", "RAG")
               2. embedding cosine (meaning: "智能体" ~ "Agent")
             Each channel nominates its top RECALL_K jobs; the union is the
             candidate pool for the recommended list.
  Ranking  : weighted sum of features (weights in config/my_prefs.json).
  Re-rank  : MMR on the candidate pool so the top list is not 30 jobs from
             the same company.

Why two channels instead of only embeddings: embeddings are fuzzy. "Java 后端"
and "Python 后端" look close in meaning, but if I don't know Java that's a miss.
BM25 is exact but blind to synonyms. Each covers the other's blind spot.

Feature scores are all scaled to 0~1 before weighting, otherwise BM25 (which
can be 0~40) would drown out the 0/1 features.

Example with default weights {bm25 .25, emb .25, skill .25, direction .15, city .10}:
  bm25 = 0.8, emb = 0.6, skill = 2/4 = 0.5, direction match = 1, city match = 0
  score = 100 * (0.25*0.8 + 0.25*0.6 + 0.25*0.5 + 0.15*1 + 0.10*0) = 62.5
If the embedding channel is unavailable, the remaining weights are rescaled to
sum to 1, so scores stay on the same 0~100 scale.
"""
from .bm25 import BM25, tokenize
from .fit import avoid

DEFAULT_WEIGHTS = {"bm25": 0.25, "emb": 0.25, "skill": 0.25, "direction": 0.15, "city": 0.10, "avoid": 0.0}
RECALL_K = 1000


def _top_ids(values, k):
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    return set(order[:k])


def features(jobs, profile, prefs, emb=None):
    """Return one dict of 0~1 feature values per job. `emb` = semantic scores or None."""
    my_skills = set(profile.get("skills", []))
    query = tokenize(" ".join(profile.get("skills", []) + profile.get("keywords", [])))
    docs = [tokenize(j["title"] + " " + " ".join(j.get("skills", [])) + " " + j.get("text", "")[:2000])
            for j in jobs]
    raw = BM25(docs).score(query) if jobs else []
    top = max(raw) if raw else 0
    want_dirs = set(prefs.get("directions", []))
    want_cities = set(prefs.get("cities", []))
    avoid_cfg = prefs.get("avoid", {})

    bm25_recall = _top_ids(raw, RECALL_K)
    emb_recall = _top_ids(emb, RECALL_K) if emb else set()

    feats = []
    for i, (j, b) in enumerate(zip(jobs, raw)):
        js = set(j.get("skills", []))
        hit = sorted(js & my_skills)
        # Share of the job's skills I have. +1 in the denominator so a job with a
        # single tag I happen to know does not get a perfect 1.0.
        skill = len(hit) / (len(js) + 1) if js else 0.0
        cities_hit = [c for c in j["cities"] if c in want_cities]
        av, av_reason = avoid(j, avoid_cfg)
        f = {
            "bm25": b / top if top else 0.0,
            "skill": skill,
            "direction": 1.0 if j["direction"] in want_dirs else 0.0,
            "city": 1.0 if (cities_hit or not want_cities) else 0.0,
            "avoid": av,
            "_avoid_reason": av_reason,
            "_hit": hit,
            "_cities_hit": cities_hit,
            "_recall": (["bm25"] if i in bm25_recall else []) + (["emb"] if i in emb_recall else []),
        }
        if emb:
            f["emb"] = emb[i]
        feats.append(f)
    return feats


def active_weights(prefs, have_emb):
    """Weights for the features we actually have, rescaled to sum to 1."""
    w = {**DEFAULT_WEIGHTS, **prefs.get("weights", {})}
    if not have_emb:
        # Tuned weights may lean almost entirely on emb, so dropping it would
        # leave only direction/city. Use a separate no-embedding set instead.
        w = dict(prefs.get("weights_no_emb") or w)
        w.pop("emb", None)
    # Scale by the positive weights only: `avoid` is negative (a penalty), and
    # counting it would shrink the total and inflate everything else.
    total = sum(v for v in w.values() if v > 0)
    return {k: v / total for k, v in w.items()}


def score(jobs, profile, prefs, emb=None):
    """Attach `match` (0~100), `reasons`, `emb` and `recall` to every job.
    Returns the features for evaluation."""
    w = active_weights(prefs, emb is not None)
    feats = features(jobs, profile, prefs, emb)
    for j, f in zip(jobs, feats):
        j["match"] = round(max(0.0, 100 * sum(wt * f[k] for k, wt in w.items())), 1)
        j["avoid"] = f["avoid"]
        j["recall"] = f["_recall"]
        if emb is not None:
            j["emb"] = round(f["emb"], 3)
        reasons = []
        if f["_hit"]:
            reasons.append("技能: " + ", ".join(f["_hit"][:6]))
        if f["_recall"] == ["emb"]:
            reasons.append("语义相近（关键词没对上）")
        if f["direction"]:
            reasons.append("方向: " + j["direction"])
        if f["_cities_hit"]:
            reasons.append("城市: " + "/".join(f["_cities_hit"][:3]))
        if f["_avoid_reason"]:
            reasons.append("⚠ " + f["_avoid_reason"])
        j["reasons"] = reasons
    return feats


def _jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def mmr_rerank(jobs, top_n=200, pool=600, lam=0.7):
    """Maximal Marginal Relevance.

    Pick jobs one by one. Each step chooses the job maximizing
        lam * relevance - (1 - lam) * max_similarity_to_already_picked
    similarity = 0.7 * same_company + 0.3 * jaccard(skills)

    lam = 1 is pure relevance (could be 30 ByteDance jobs in a row);
    lam = 0.7 trades a little relevance for variety.
    Sets job["rec"] = 1..top_n on the picked ones.
    """
    for j in jobs:
        j["rec"] = None
    # Only jobs nominated by at least one recall channel can be recommended.
    pooled = [j for j in jobs if j.get("recall")] or jobs
    cands = sorted(pooled, key=lambda j: j["match"], reverse=True)[:pool]
    # max_sim[i] = highest similarity of candidate i to anything picked so far.
    # Updating it after each pick keeps this O(top_n * pool) instead of O(top_n^2 * pool).
    max_sim = [0.0] * len(cands)
    alive = list(range(len(cands)))
    picked = []
    while alive and len(picked) < top_n:
        best = max(alive, key=lambda i: lam * cands[i]["match"] / 100 - (1 - lam) * max_sim[i])
        alive.remove(best)
        p = cands[best]
        picked.append(p)
        for i in alive:
            c = cands[i]
            s = 0.7 * (c["company"] == p["company"]) + 0.3 * _jaccard(c["skills"], p["skills"])
            if s > max_sim[i]:
                max_sim[i] = s
    for i, j in enumerate(picked, 1):
        j["rec"] = i
