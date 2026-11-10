"""LLM-as-a-judge labels, corrected with my own labels (prediction-powered inference).

    python -m matching.evaluate llm-label   # LLM labels the top region (needs .env)
    python -m matching.evaluate ppi         # agreement, bias check, corrected estimates

Why: my 100 labels only cover ~50 jobs in the top region, which is where ranking
quality actually matters. An LLM can label hundreds more for cheap, but its
labels are biased in some unknown direction. PPI fixes that: measure the bias
on jobs that have BOTH my label and the LLM's, then subtract it.

The quantity estimated, per ranking variant v (baseline, tuned, emb_only, ...):
    DCG@20(v) / maxDCG@20,  where maxDCG@20 = sum_{i=1..20} 3 / log2(i+1)
The denominator is fixed (every slot a "2"), unlike NDCG whose denominator
depends on the labels. That keeps the metric a weighted SUM of per-job gains,
and a sum is what the PPI correction can be applied to: if each unlabeled
job's gain is estimated as  llm_gain + delta, the sum's estimate shifts by
delta * (sum of that job's weights), no ratio of two noisy things.

Pool = union of the top 50 of each variant. Each pool job's gain is:
  - my label, if I labeled it;
  - otherwise LLM gain + delta, where
      delta = mean(my_gain - llm_gain) over a RANDOM sample of the unlabeled
      part of the pool (data/labels_ppi.csv, written by `ppi` the first time).
    Random matters: delta measured on a hand-picked subset would carry that
    subset's own quirks. Until that sheet is filled, delta falls back to the
    jobs I already labeled in the pool (the old top 50) -- a weaker assumption
    ("the LLM is biased the same way on the rest of the top region"), and the
    report says so.
Uncertainty comes only from delta (the pool itself is enumerated in full), so
the CI is a bootstrap over the jobs delta was measured on.
"""
import csv
import json
import math
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent
FEATS = ROOT / "data" / "rank_debug.json"
RAW = ROOT / "data" / "raw" / "latest.json"
LLM_LABELS = ROOT / "data" / "llm_labels.json"
PPI_SHEET = ROOT / "data" / "labels_ppi.csv"
TOP_N, K = 50, 20
BASELINE = {"bm25": 0.25, "emb": 0.25, "skill": 0.25, "direction": 0.15, "city": 0.10}


def gain(label):
    return 2 ** label - 1  # 0 -> 0, 1 -> 1, 2 -> 3, same as NDCG


def variants(tuned):
    return {"baseline": BASELINE, "tuned": tuned, "emb_only": {"emb": 1},
            "bm25_only": {"bm25": 1}, "skill_only": {"skill": 1}}


def ranked(feats, w, n):
    return sorted(feats, key=lambda i: sum(x * feats[i].get(f, 0) for f, x in w.items()), reverse=True)[:n]


def pool_ids(feats, tuned):
    tops = {name: ranked(feats, w, TOP_N) for name, w in variants(tuned).items()}
    pool = sorted({i for t in tops.values() for i in t})
    return tops, pool


# ---------- labeling ----------

PROMPT = """你在帮一位求职者筛选岗位：判断他会不会投下面这个岗位。

【求职者简历】
{resume}

【求职偏好】
2027 届，找校招或实习。主方向：AI 应用 / Agent / 大模型相关的算法或开发岗；次要方向：金融数据分析。
可接受的岗位方向：{dirs}。偏好城市：{cities}。

【岗位】
公司：{company}
标题：{title}
类型：{recruit}　城市：{job_cities}　类别：{category}
描述：{text}

【评分标准】
2 = 会投：方向对口，要求和他的背景基本匹配
1 = 可能投：部分对口，或者要求偏离/偏高但仍有关系
0 = 不投：方向不对口，或明显不适合他
有的岗位描述很短（只有标题和技能标签），按已有信息判断，不要因为信息少就打高分或低分。

只输出 JSON：{{"label": 0 或 1 或 2, "reason": "一句话理由"}}"""


def resume_text():
    from pypdf import PdfReader
    pdfs = sorted((ROOT / "resume").glob("*.pdf"))
    if not pdfs:
        raise SystemExit("no resume PDF in resume/")
    return "\n".join(p.extract_text() or "" for p in PdfReader(pdfs[0]).pages)[:4000]


def raw_jobs():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    return {j["id"]: j for jobs in raw.values() for j in jobs}


def llm_label(human_ids, tuned):
    cfg = llm.config()
    if not cfg["key"]:
        raise SystemExit("LLM_API_KEY not set: put it in .env (see matching/llm.py)")
    feats = json.loads(FEATS.read_text(encoding="utf-8"))
    prefs = json.loads((ROOT / "config" / "my_prefs.json").read_text(encoding="utf-8"))
    _, pool = pool_ids(feats, tuned)
    done = json.loads(LLM_LABELS.read_text(encoding="utf-8")) if LLM_LABELS.exists() else {}
    jobs = raw_jobs()
    todo = [i for i in dict.fromkeys(pool + list(human_ids)) if i not in done and i in jobs]
    print(f"pool {len(pool)} + human {len(human_ids)} -> {len(todo)} to label with {cfg['model']}")
    resume = resume_text()

    def one(i):
        j = jobs[i]
        cities = j.get("cities_raw") or j.get("cities") or ""
        prompt = PROMPT.format(resume=resume, dirs="、".join(prefs.get("directions", [])),
                               cities="、".join(prefs.get("cities", [])), company=j["company"],
                               title=j["title"], recruit=j.get("recruit", ""), job_cities=str(cities)[:60],
                               category=j.get("category", ""), text=(j.get("text") or "")[:1200])
        out = llm.chat_json(prompt, cfg)
        label = int(out["label"])
        if label not in (0, 1, 2):
            raise ValueError(f"bad label {label}")
        return i, {"label": label, "reason": str(out.get("reason", ""))[:200]}

    failed = 0
    with ThreadPoolExecutor(6) as ex:
        futures = [ex.submit(one, i) for i in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                i, res = fut.result()
                done[i] = res
            except Exception as e:  # noqa: BLE001 -- one bad reply shouldn't kill the batch
                failed += 1
                print("  failed:", e)
            if n % 20 == 0 or n == len(todo):
                LLM_LABELS.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  {n}/{len(todo)}")
    print(f"done, {len(done)} labeled in total, {failed} failed (rerun to retry them)")


# ---------- analysis ----------

def read_sheet(path):
    out = {}
    if path.exists():
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["label"].strip():
                    out[row["id"]] = int(row["label"])
    return out


def agreement(human, llm_labels):
    both = [i for i in human if i in llm_labels]
    m = [[0] * 3 for _ in range(3)]
    for i in both:
        m[human[i]][llm_labels[i]] += 1
    n = len(both)
    po = sum(m[k][k] for k in range(3)) / n
    pe = sum(sum(m[k]) * sum(r[k] for r in m) for k in range(3)) / n ** 2
    print(f"\n[1] agreement on {n} jobs I labeled")
    print("            LLM=0  LLM=1  LLM=2")
    for k in range(3):
        print(f"  me={k}    {m[k][0]:>5}  {m[k][1]:>5}  {m[k][2]:>5}")
    print(f"  exact agreement {po:.2f}, chance-level {pe:.2f}, Cohen's kappa {(po - pe) / (1 - pe):.2f}")
    return both


def pearson(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sx = sum((a - mx) ** 2 for a in x) ** 0.5
    sy = sum((b - my) ** 2 for b in y) ** 0.5
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


def bias_check(both, human, llm_labels, feats):
    # Circularity: if the LLM judges by surface similarity the way the
    # embedding does, it will over-rate exactly the jobs emb ranks high, and
    # "emb wins" becomes partly the judge agreeing with itself. Test: does the
    # LLM's error (llm_gain - my_gain) grow with the emb score?
    err = [gain(llm_labels[i]) - gain(human[i]) for i in both]
    print("\n[2] is the LLM's error tied to a ranking feature? (corr > 0 = LLM over-rates what that feature likes)")
    for f in ("emb", "bm25", "skill"):
        print(f"  corr(error, {f:<5}) = {pearson(err, [feats[i][f] for i in both]):+.2f}")
    print(f"  mean error = {sum(err) / len(err):+.2f} gain units (>0: LLM more generous than me)")


def ppi(tuned, human_all, seed=0):
    feats = json.loads(FEATS.read_text(encoding="utf-8"))
    llm_labels = {i: v["label"] for i, v in json.loads(LLM_LABELS.read_text(encoding="utf-8")).items()}
    both = agreement(human_all, llm_labels)
    bias_check(both, human_all, llm_labels, feats)

    tops, pool = pool_ids(feats, tuned)
    missing = [i for i in pool if i not in llm_labels and i not in human_all]
    if missing:
        raise SystemExit(f"{len(missing)} pool jobs have no LLM label yet: run llm-label first")
    old = read_sheet(ROOT / "data" / "labels.csv")
    unlabeled = [i for i in pool if i not in old]
    if not PPI_SHEET.exists():
        write_ppi_sheet(random.Random(seed).sample(unlabeled, min(40, len(unlabeled))))

    # Jobs delta is measured on: a random sample of the pool part I hadn't labeled.
    rect = [i for i in unlabeled if i in human_all and i in llm_labels]
    if len(rect) >= 20:
        source = f"random sample of the unlabeled pool part ({len(rect)} jobs)"
    else:
        rect = [i for i in pool if i in old and i in llm_labels]
        source = (f"FALLBACK: my old top-50 labels ({len(rect)} jobs) -- assumes the LLM is biased the "
                  f"same way on the rest of the pool; fill {PPI_SHEET.name} for the proper estimate")
    print(f"\n[3] PPI over a pool of {len(pool)} jobs (top {TOP_N} of each variant); delta from {source}")

    max_dcg = sum(3 / math.log2(r + 2) for r in range(K))

    def metric(order, delta):
        s = 0.0
        for r, i in enumerate(order[:K]):
            g = gain(human_all[i]) if i in human_all else gain(llm_labels[i]) + delta
            s += g / math.log2(r + 2)
        return s / max_dcg

    diffs = [gain(human_all[i]) - gain(llm_labels[i]) for i in rect]
    delta = sum(diffs) / len(diffs)
    rng = random.Random(seed)
    boots = []
    for _ in range(2000):
        d = [rng.choice(diffs) for _ in diffs]
        boots.append(sum(d) / len(d))

    def ci(f):
        vals = sorted(f(b) for b in boots)
        return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]

    print(f"  delta = {delta:+.2f} (correction added to each LLM-only gain)")
    llm_only = {}
    print(f"  {'variant':<11} {'LLM only':>8} {'PPI':>7}   95% CI")
    for name, order in tops.items():
        # What we'd report trusting the LLM blindly, for comparison.
        llm_only[name] = sum(gain(llm_labels.get(i, human_all.get(i, 0))) / math.log2(r + 2)
                             for r, i in enumerate(order[:K])) / max_dcg
        lo, hi = ci(lambda b, o=order: metric(o, b))
        print(f"  {name:<11} {llm_only[name]:>8.3f} {metric(order, delta):>7.3f}   [{lo:.3f}, {hi:.3f}]")
    for a, b in (("tuned", "baseline"), ("emb_only", "tuned")):
        d = metric(tops[a], delta) - metric(tops[b], delta)
        lo, hi = ci(lambda x: metric(tops[a], x) - metric(tops[b], x))
        print(f"  {a} - {b}: {d:+.3f}  [{lo:+.3f}, {hi:+.3f}]")
    if not source.startswith("FALLBACK"):
        subset_estimates(tops, unlabeled, rect, human_all, llm_labels, seed)


def subset_estimates(tops, unlabeled, sample, human, llm_labels, seed, boots=2000):
    """[3] adds ONE pool-wide delta to every LLM-only job. That is only right if
    the LLM's bias is the same everywhere in the pool -- and [2] can show it
    isn't (error correlated with the ranking features). A variant's top 20 is a
    SUBSET of the pool, so its correction should be measured on that subset.

    Horvitz-Thompson: the 40 sampled jobs were drawn uniformly from the N
    unlabeled pool jobs, so each sampled job stands in for N/n of them. For a
    variant's top-20 list S:
        HT      = sum_{S, labeled before} d_r*y  +  N/n * sum_{S, sampled} d_r*y
        PPI-HT  = HT-style correction on top of the LLM:
                  sum_{S, labeled before} d_r*y + sum_{S, unlabeled} d_r*f
                  + N/n * sum_{S, sampled} d_r*(y - f)
    (d_r = 1/log2(r+1), y = my gain, f = LLM gain.) Both are unbiased for the
    subset with no assumption about where the LLM is biased; PPI-HT has lower
    variance when f tracks y, HT is the fallback when the LLM is useless.
    The CI bootstraps the 40-job sample."""
    N, n, U = len(unlabeled), len(sample), set(unlabeled)
    max_dcg = sum(3 / math.log2(r + 2) for r in range(K))

    def est(order, smp, use_llm):
        count = {}
        for i in smp:
            count[i] = count.get(i, 0) + 1
        s = 0.0
        for r, i in enumerate(order[:K]):
            d = 1 / math.log2(r + 2)
            if i not in U:
                s += d * gain(human[i])
                continue
            f = gain(llm_labels[i]) if use_llm else 0
            s += d * f
            if i in count:  # sampled, so I have my own label for it
                s += count[i] * (N / n) * d * (gain(human[i]) - f)
        return s / max_dcg

    rng = random.Random(seed)
    resamples = [[rng.choice(sample) for _ in sample] for _ in range(boots)]

    def ci(f):
        vals = sorted(f(s) for s in resamples)
        return vals[int(0.025 * boots)], vals[int(0.975 * boots)]

    print(f"\n[4] subset-correct estimates (Horvitz-Thompson over the {n}/{N} random sample)")
    print(f"  {'variant':<11} {'HT':>6} {'95% CI':>16}   {'PPI-HT':>6} {'95% CI':>16}")
    for name, order in tops.items():
        h, p_ = est(order, sample, False), est(order, sample, True)
        hl, hh = ci(lambda s: est(order, s, False))
        pl, ph = ci(lambda s: est(order, s, True))
        print(f"  {name:<11} {h:>6.3f} [{hl:.3f}, {hh:.3f}]   {p_:>6.3f} [{pl:.3f}, {ph:.3f}]")
    for a, b in (("tuned", "baseline"), ("emb_only", "tuned")):
        for label, use in (("HT", False), ("PPI-HT", True)):
            d = est(tops[a], sample, use) - est(tops[b], sample, use)
            lo, hi = ci(lambda s: est(tops[a], s, use) - est(tops[b], s, use))
            print(f"  {a} - {b} ({label}): {d:+.3f}  [{lo:+.3f}, {hi:+.3f}]")
    hits = {name: sum(i in set(sample) for i in order[:K]) for name, order in tops.items()}
    print("  sampled jobs inside each top 20 (how much data each subset estimate rests on):", hits)


def write_ppi_sheet(ids):
    jobs = raw_jobs()
    random.shuffle(ids)
    with PPI_SHEET.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["label", "company", "title", "recruit", "cities", "url", "id"])
        for i in ids:
            j = jobs.get(i, {})
            w.writerow(["", j.get("company", ""), j.get("title", ""), j.get("recruit", ""),
                        str(j.get("cities_raw", ""))[:40], j.get("url", ""), i])
    print(f"wrote {PPI_SHEET} with {len(ids)} random pool jobs -- label them 0/1/2 like before, then rerun ppi")
