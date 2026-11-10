"""Second recall channel: semantic similarity with a small embedding model.

BM25 only matches words that literally appear in both texts. My resume says
"智能体" and a JD says "Agent"; I write "检索增强" and the JD writes "RAG".
BM25 scores those 0. An embedding model maps both texts to vectors, and texts
with similar meaning end up close together, whatever words they use.

Model: BAAI/bge-small-zh-v1.5 via fastembed (ONNX, CPU only, ~90 MB, 512 dims).
  - small: 15k jobs embed in well under a minute on a laptop or GitHub runner
  - Chinese-first, but handles the English tech words in JDs fine
  - fastembed avoids installing PyTorch (~800 MB) just to run inference

Similarity = cosine of the two vectors (dot product after normalizing):
    cos(a, b) = a·b / (|a| |b|)
Example with 3-dim toy vectors: a = [1, 0, 1], b = [1, 1, 0]
    a·b = 1, |a| = |b| = √2, cos = 1/2 = 0.5

Raw cosine for bge sits in a narrow band (roughly 0.3 ~ 0.8 for unrelated vs
related), so before it joins the other features it is min-max scaled to 0~1
over all jobs of the day, the same way BM25 is scaled by its max.

Vectors are cached in data/emb_cache.npz keyed by a hash of (job id, title), so
a daily run only embeds the new jobs (~a few hundred), not all 15k again.
Why not hash the full text: jobs carried over from yesterday (a source failed,
or --only) come from data.json, which has no JD text. Their text differs from
the original, so a text hash would miss the cache and re-embed them with less
information. The id + title stays the same.

If fastembed is not installed, embed_scores() returns None and ranking simply
runs without this channel.
"""
import hashlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "emb_cache.npz"
MODEL_DIR = ROOT / "data" / "model_cache"
MODEL = "BAAI/bge-small-zh-v1.5"


def job_text(j):
    # Title + skill tags + the start of the JD. The first ~300 characters of a JD
    # are usually the duties; the rest is boilerplate that only adds noise.
    return f"{j['title']}。{' '.join(j.get('skills') or [])}。{(j.get('text') or '')[:TEXT_CHARS]}"


def _key(job):
    return hashlib.md5(f"{job['id']}|{job['title']}".encode("utf-8")).hexdigest()


CHUNK = 1000
TEXT_CHARS = 300


def _save(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp.npz")  # write then rename, so a kill mid-write can't corrupt it
    np.savez_compressed(tmp, keys=np.array(list(cache.keys())), vecs=np.array(list(cache.values())))
    tmp.replace(CACHE)


def _normalize(m):
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(n == 0, 1, n)


def embed_scores(jobs, profile, log=print):
    """Return a list of 0~1 semantic scores (one per job), or None if unavailable."""
    try:
        from fastembed import TextEmbedding
    except ImportError:
        log("  [embed] fastembed not installed, skipping semantic recall")
        return None

    query = " ".join(profile.get("keywords", []) + profile.get("skills", []))
    if not query.strip() or not jobs:
        return None

    model = TextEmbedding(MODEL, cache_dir=str(MODEL_DIR))
    texts = [job_text(j) for j in jobs]
    keys = [_key(j) for j in jobs]

    cache = {}
    if CACHE.exists():
        z = np.load(CACHE)
        cache = dict(zip(z["keys"].tolist(), z["vecs"]))
    todo = [i for i, k in enumerate(keys) if k not in cache]
    log(f"  [embed] {len(jobs) - len(todo)} cached, embedding {len(todo)} new jobs")
    # Save every CHUNK jobs: the first run embeds all ~15k jobs and takes a few
    # minutes; if it gets interrupted, the next run continues instead of restarting.
    for start in range(0, len(todo), CHUNK):
        part = todo[start:start + CHUNK]
        new = np.array(list(model.embed([texts[i] for i in part], batch_size=64)), dtype=np.float32)
        for i, v in zip(part, new):
            cache[keys[i]] = v.astype(np.float16)  # float16 halves the cache size
        _save(cache)
        log(f"  [embed] {min(start + CHUNK, len(todo))}/{len(todo)}")

    vecs = _normalize(np.array([cache[k] for k in keys], dtype=np.float32))
    # query_embed adds bge's retrieval instruction prefix; queries and passages
    # are embedded slightly differently on purpose.
    q = _normalize(np.array(list(model.query_embed([query]))[0], dtype=np.float32))
    cos = vecs @ q

    # Keep only today's jobs in the cache so it doesn't grow forever.
    _save({k: cache[k] for k in keys})

    lo, hi = float(cos.min()), float(cos.max())
    scaled = (cos - lo) / (hi - lo) if hi > lo else np.zeros_like(cos)
    return scaled.tolist()
