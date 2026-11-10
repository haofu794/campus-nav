"""One command for the whole pipeline: scrape -> ETL -> rank -> web/data.json.

    python run.py                 # full run (~30-40 min, Guopin is the slow part)
    python run.py --quick         # 1 page per source, 5 tenants per platform, for testing
    python run.py --only feishu,beisen
    python run.py --skip-scrape   # reuse data/raw/*.json, just redo ETL + ranking

The run is idempotent: running it twice on the same day gives the same result,
because data.json is rebuilt from scratch each time, never appended to.
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from etl.pipeline import build
from etl.skills import SKILLS
from matching.embed import embed_scores
from matching.rank import DEFAULT_WEIGHTS, mmr_rerank, score
from scraper import SCRAPERS, campus_radar
from scraper.registry import load_companies, plan

ROOT = Path(__file__).resolve().parent
CONFIG, DATA, WEB = ROOT / "config", ROOT / "data", ROOT / "web"
RAW = DATA / "raw"


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, obj, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


ALL_PLATFORMS = ["campus_radar", "pingan", "guopin", "feishu", "beisen", "hotjob"]


def plan_sources(settings, only, quick, do_detect=True):
    """Decide which sources to scrape today. Returns (sources, company_directory)."""
    platforms = only or ALL_PLATFORMS
    try:
        skip = campus_radar.covered_companies()
    except Exception as e:  # noqa: BLE001
        log(f"campus-radar unreachable ({e}); not skipping its companies")
        skip = set()
    items = load_companies(DATA / "registry_cache.json", CONFIG / "companies_extra.json", log=log)
    reg, directory = plan(items, DATA / "platform_cache.json", skip_names=skip,
                          blacklist=settings.get("blacklist", []), do_detect=do_detect, log=log)

    sources = []
    if "campus_radar" in platforms:
        sources.append({"platform": "campus_radar", "src": "campus_radar", "company": "campus-radar"})
    if "pingan" in platforms:
        sources.append({"platform": "pingan", "src": "pingan", "company": "中国平安"})
    if "guopin" in platforms:
        sources.append({"platform": "guopin", "src": "guopin", "company": "国聘"})
    for platform in ("feishu", "beisen", "hotjob"):
        if platform in platforms:
            picked = [s for s in reg if s["platform"] == platform]
            sources.extend(picked[:5] if quick else picked)
    return sources, directory


STATUS_LABEL = {
    "campus_radar": "已抓取", "pingan": "已抓取", "feishu": "已抓取", "beisen": "已抓取", "hotjob": "已抓取",
    "moka": "仅入口（Moka 加密）", "unknown": "仅入口（自建网站）",
    "unreachable": "仅入口（网站暂时连不上）", "no_url": "仅投递说明（公众号/邮箱）",
}


def attach_job_counts(directory, jobs):
    """How many scraped jobs each directory company has, so the page can say
    '已抓取 37 个' or 'only a link'. Match by source id first, then by name."""
    by_src, by_name = {}, {}
    for j in jobs:
        k = 1 if j["recruit"] == "校招" else 0
        by_src.setdefault(j["src"], [0, 0])[1 - k] += 1
        by_name.setdefault(j["company"], [0, 0])[1 - k] += 1
    for d in directory:
        # Exact name first (平安证券 -> only its own jobs), then the whole source
        # (中国平安 -> every Ping An job), then a fuzzy name match (campus-radar).
        n = by_name.get(d["company"]) or (by_src.get(d["src"]) if d["src"] else None)
        if n is None:
            hits = [v for name, v in by_name.items()
                    if name == d["company"] or (len(name) >= 2 and name in d["company"])
                    or (len(d["company"]) >= 2 and d["company"] in name)]
            n = [sum(h[0] for h in hits), sum(h[1] for h in hits)] if hits else [0, 0]
        d["jobs_campus"], d["jobs_intern"] = n
        d["status_label"] = STATUS_LABEL.get(d["status"], d["status"] or "")


def scrape(sources, max_pages, workers, on_progress=None):
    """Run scrapers in parallel. Each task hits a different host, and inside one
    task requests are sequential with a delay, so no single site gets hammered.
    on_progress(results) is called after each finished source (used by --merge
    to save partial results, so an interrupted run keeps what it already got)."""
    results = {}

    def task(src):
        return SCRAPERS[src["platform"]](src, max_pages=max_pages, log=log)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(task, s): s for s in sources}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                jobs = fut.result()
                log(f"  ok   {s['src']:<32} {s['company']:<16} {len(jobs):>5} jobs")
                # campus-radar returns many sub-sources (one per company); split them
                for j in jobs:
                    results.setdefault(j["src"], []).append(j)
                if not jobs:
                    results.setdefault(s["src"], [])
            except Exception as e:  # noqa: BLE001 -- one bad source must not kill the run
                log(f"  FAIL {s['src']:<32} {s['company']:<16} {str(e)[:120]}")
                results[s["src"]] = None
            if on_progress:
                on_progress(results)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--force", action="store_true", help="write even if the job count dropped a lot")
    ap.add_argument("--no-embed", action="store_true", help="skip the embedding recall channel")
    ap.add_argument("--no-detect", action="store_true", help="don't probe career sites (use cache only)")
    ap.add_argument("--shard", default="", help="k/n: scrape only every n-th feishu/beisen/hotjob source")
    ap.add_argument("--merge", action="store_true", help="merge results into data/raw/latest.json instead of replacing it")
    ap.add_argument("--workers", type=int, default=0, help="parallel sources (default: settings.json)")
    args = ap.parse_args()

    settings = load_json(CONFIG / "settings.json", {})
    prefs = load_json(CONFIG / "my_prefs.json", {})
    profile = load_json(CONFIG / "profile.json", {"skills": [], "keywords": []})
    prev = load_json(WEB / "data.json", {"jobs": []})
    history = load_json(DATA / "history.json", {})
    today = date.today().isoformat()
    only = [x for x in args.only.split(",") if x]

    # 1. Scrape
    sources, directory = plan_sources(settings, only, args.quick, do_detect=not args.no_detect)
    if args.skip_scrape:
        raw = load_json(RAW / "latest.json", {})
        log(f"reusing raw cache: {sum(len(v or []) for v in raw.values())} jobs")
    else:
        if args.shard:  # split a long scrape into pieces, e.g. --shard 0/3 --merge
            k, n = map(int, args.shard.split("/"))
            per_tenant = [s for s in sources if s["platform"] in ("feishu", "beisen", "hotjob")]
            sources = [s for i, s in enumerate(per_tenant) if i % n == k]
        log(f"scraping {len(sources)} sources")
        base_raw = load_json(RAW / "latest.json", {}) if args.merge else {}

        def save_partial(results):
            # Only successful sources overwrite; a failure keeps the older data.
            save_json(RAW / "latest.json", {**base_raw, **{k: v for k, v in results.items() if v is not None}})

        fresh = scrape(sources, max_pages=1 if args.quick else None,
                       workers=args.workers or settings.get("workers", 6),
                       on_progress=save_partial if args.merge else None)
        raw = {**base_raw, **fresh} if args.merge else fresh
        save_json(RAW / "latest.json", raw)

    # Sources we did not try today (e.g. --only) count as "failed" so their
    # jobs are carried over instead of slowly expiring.
    for j in prev["jobs"]:
        raw.setdefault(j["src"], None)

    # 2. ETL
    jobs, new_history, stats = build(raw, prev["jobs"], history, today,
                                     blacklist=settings.get("blacklist", []),
                                     stale_days=settings.get("stale_days", 3), log=log)
    log(f"etl: {stats['total']} jobs, {stats['new_today']} new today, {stats['kept_stale']} kept as stale")

    # Safety net: a sudden big drop usually means something broke, not that
    # half of all jobs disappeared overnight. Don't overwrite good data.
    if prev["jobs"] and len(jobs) < 0.5 * len(prev["jobs"]) and not args.force:
        log(f"ABORT: {len(jobs)} jobs vs {len(prev['jobs'])} yesterday. Re-run with --force if this is real.")
        raise SystemExit(1)

    # 3. Rank (embedding channel is optional: skipped if fastembed isn't installed)
    emb = None if args.no_embed else embed_scores(jobs, profile, log=log)
    feats = score(jobs, profile, prefs, emb)
    mmr_rerank(jobs, top_n=prefs.get("rec_top_n", 200))
    save_json(DATA / "rank_debug.json", {
        j["id"]: {"id": j["id"], "company": j["company"], "title": j["title"], "match": j["match"],
                  **{k: round(v, 4) for k, v in f.items() if not k.startswith("_")}}
        for j, f in zip(jobs, feats)
    })

    # 4. Write outputs (drop the long JD text: data.json only needs what the page shows)
    for j in jobs:
        j.pop("text", None)
    jobs.sort(key=lambda j: (-j["match"], j["company"]))
    counts = {}
    for j in jobs:
        counts[j["src"].split(":")[0]] = counts.get(j["src"].split(":")[0], 0) + 1
    # skill_dict + prefs let the web page re-score jobs in the browser after a
    # resume upload, using exactly the same dictionary and weights as Python.
    attach_job_counts(directory, jobs)
    cov = {}
    for d in directory:
        cov[d["status_label"]] = cov.get(d["status_label"], 0) + 1
    log(f"company directory: {len(directory)} companies, {cov}")
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M"), "today": today,
           "stats": {**stats, "by_platform": counts, "coverage": cov},
           "profile_skills": profile.get("skills", []),
           "skill_dict": SKILLS,
           "prefs": {**prefs, "weights": {**DEFAULT_WEIGHTS, **prefs.get("weights", {})}},
           "companies": directory,
           "jobs": jobs}
    save_json(WEB / "data.json", out)
    save_json(DATA / "history.json", new_history)
    save_json(DATA / "run_log.json", {"date": today, **out["stats"]}, indent=2)
    log(f"done: web/data.json ({(WEB / 'data.json').stat().st_size / 1e6:.1f} MB), by platform {counts}")


if __name__ == "__main__":
    main()
