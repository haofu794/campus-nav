"""Fail the daily workflow when scraping quietly broke.

A single site failing is normal (the pipeline keeps yesterday's jobs for it),
so the workflow itself still succeeds -- and nobody gets told. This check runs
after deploy and exits 1 when something big is wrong, which makes GitHub send
the usual "workflow failed" email:
  - a major platform returned 0 jobs (usually: the site changed its API), or
  - more than 30% of sources failed today.
The page is already deployed by then, with yesterday's data for the broken
sources, so a failure here never takes the site down.
"""
import json
import sys
from pathlib import Path

MAJOR = ("campus_radar", "beisen", "feishu", "guopin")
MAX_FAILED_SHARE = 0.30

log = json.loads((Path(__file__).resolve().parent.parent / "data" / "run_log.json").read_text(encoding="utf-8"))
problems = []
by_platform = log.get("by_platform", {})
for p in MAJOR:
    if by_platform.get(p, 0) == 0:
        problems.append(f"{p}: 0 jobs today")
failed, total = len(log.get("failed_sources", [])), log.get("sources", 0)
if total and failed / total > MAX_FAILED_SHARE:
    problems.append(f"{failed}/{total} sources failed")

if problems:
    print("health check FAILED:\n  " + "\n  ".join(problems))
    sys.exit(1)
print(f"health check ok: {sum(by_platform.values())} jobs, {failed} failed sources")
