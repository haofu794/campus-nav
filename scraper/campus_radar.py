"""campus-radar (MIT License, github.com/Ajax-1/campus-radar) public job index.

It already collects 17 big companies (ByteDance, Tencent, Alibaba, Meituan,
Baidu, Kuaishou, JD, PDD ...) every day. Re-scraping them myself would double
the load on those sites for no gain, so I reuse their published index and
credit them in the README.

Each job is a compact array:
  [id, company_index, title, category, is_intern, grad_year, cities, apply_url,
   publish_day (days since 1970), skill_tag_indexes]
"""
from datetime import date, timedelta
from functools import lru_cache

from .http import PoliteSession
from .model import make_job

URL = "https://ajax-1.github.io/campus-radar/data/jobs.json"
BIG_TECH = {"bytedance", "alibaba", "tencent", "meituan", "kuaishou", "baidu", "jd", "pdd"}


@lru_cache(maxsize=1)
def _load():
    # Cached so covered_companies() and fetch() share one 2.7 MB download.
    return PoliteSession(timeout=60).get_json(URL)


def fetch(source, max_pages=None, log=print):
    data = _load()
    companies, tags = data["companies"], data["tags"]
    jobs = []
    for row in data["jobs"]:
        jid, ci, title, category, intern, _grad, cities, url, pub_day, tag_idx = row
        comp = companies[ci]
        skills = [tags[i] for i in tag_idx]
        publish = (date(1970, 1, 1) + timedelta(days=pub_day)).isoformat() if pub_day else None
        jobs.append(make_job(
            src="campus_radar:" + comp["source"],
            ext_id=jid,
            company=comp["company"],
            ent_type="互联网大厂" if comp["source"] in BIG_TECH else "民企",
            title=title,
            recruit="实习" if intern else "校招",
            cities=cities,
            url=url,
            category=category or "",
            publish_date=publish,
            text=" ".join(filter(None, [title, category] + skills)),
            skills=skills,
        ))
    return jobs


def covered_companies():
    """Names (incl. aliases) campus-radar covers, so the registry can skip them."""
    data = _load()
    names = set()
    for c in data["companies"]:
        names.add(c["company"])
        names.update(c.get("aliases") or [])
    return names
