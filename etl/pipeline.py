"""ETL: merge all sources into one clean job list.

Steps, in order:
  1. Fallback   -- a source that failed today keeps yesterday's jobs.
  2. Normalize  -- cities, direction, skills.
  3. Blacklist  -- drop companies I never want to see (华为, 比亚迪 by default).
  4. Dedup      -- the same job can come from the company site AND from Guopin.
  5. Lifecycle  -- first_seen / last_seen; a job is removed only after it has
                   been missing for `stale_days` days, not the first day it is missing
                   (one failed request should not make jobs flicker).
"""
from datetime import date

from .classify import classify
from .normalize import norm_title, normalize_cities
from .skills import extract_skills

# Lower number wins when two sources have the same job: official sites first,
# the aggregator (Guopin) last.
PRIORITY = {"campus_radar": 0, "feishu": 0, "beisen": 0, "guopin": 1}


def _platform(src):
    return src.split(":", 1)[0]


def _days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def normalize(job):
    job["cities"] = normalize_cities(job.pop("cities_raw", job.get("cities", [])))
    job["direction"] = classify(job["title"], job.get("category", ""))
    if not job.get("skills"):
        job["skills"] = extract_skills(job.get("text", "") + " " + job["title"])
    return job


def build(raw_by_src, prev_jobs, history, today, blacklist, stale_days=3, log=print):
    """
    raw_by_src -- {src: list_of_jobs or None}. None means the scrape failed.
    prev_jobs  -- yesterday's jobs (from web/data.json), used for fallback.
    history    -- {job_id: {"first_seen": d, "last_seen": d}}
    Returns (jobs, new_history, stats).
    """
    prev_by_src = {}
    for j in prev_jobs:
        prev_by_src.setdefault(j["src"], []).append(j)

    # 1. Fallback for failed sources
    jobs, failed = [], []
    for src, items in raw_by_src.items():
        if items is None:
            failed.append(src)
            carried = [dict(j) for j in prev_by_src.get(src, [])]
            for j in carried:
                j.setdefault("text", "")
            jobs.extend(carried)
        else:
            jobs.extend(items)
    if failed:
        log(f"  [etl] {len(failed)} sources failed, kept yesterday's jobs for them")

    # 2. Normalize + 3. Blacklist
    clean = []
    for j in jobs:
        if any(b in j["company"] for b in blacklist):
            continue
        clean.append(normalize(j) if "cities_raw" in j else j)

    # 4. Dedup: same URL, or same (company, title, recruit type)
    clean.sort(key=lambda j: PRIORITY.get(_platform(j["src"]), 9))
    by_url, by_key, merged = {}, {}, []
    for j in clean:
        key = (j["company"], norm_title(j["title"]), j["recruit"])
        if j["url"] in by_url:
            continue
        # Only merge across platforms. Inside one site, two jobs with the same
        # title are usually different teams (each has its own detail page).
        if key in by_key and _platform(by_key[key]["src"]) != _platform(j["src"]):
            keep = by_key[key]
            for c in j["cities"]:  # merge cities instead of dropping info
                if c not in keep["cities"]:
                    keep["cities"].append(c)
            continue
        by_url[j["url"]] = j
        by_key[key] = j
        merged.append(j)

    # 5. Lifecycle
    today_ids = {j["id"] for j in merged}
    new_history = {}
    for j in merged:
        h = history.get(j["id"], {})
        first = h.get("first_seen", today)
        new_history[j["id"]] = {"first_seen": first, "last_seen": today}
        j["first_seen"] = first

    # Jobs that vanished today: keep them a few days in case it's a hiccup.
    kept_stale = 0
    for src, olds in prev_by_src.items():
        if src in failed:
            continue  # already carried over above
        for old in olds:
            if old["id"] in today_ids:
                continue
            h = history.get(old["id"])
            if h and _days_between(h["last_seen"], today) < stale_days:
                old = dict(old)
                old.setdefault("text", "")
                merged.append(old)
                new_history[old["id"]] = h
                kept_stale += 1

    stats = {
        "total": len(merged),
        "sources": len(raw_by_src),
        "failed_sources": failed,
        "kept_stale": kept_stale,
        "new_today": sum(1 for j in merged if j.get("first_seen") == today),
    }
    return merged, new_history, stats
