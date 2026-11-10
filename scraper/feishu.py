"""Feishu Recruiting (飞书招聘) scraper.

Many companies host their career site on xxx.jobs.feishu.cn (ByteDance's own
jobs.bytedance.com runs the same system). Two calls are needed:

  1. POST {base}/api/v1/csrf/token      -> returns a token and sets a cookie
  2. POST {base}/api/v1/search/job/posts -> paged job list (limit / offset)

Things I found while testing:
  - The header `website-path` tells the API which portal we mean (campus vs
    experienced). Without it you get social-hiring jobs.
  - `recruit_type.parent.name == "校招"` marks campus jobs;
    `recruit_type.name == "实习"` marks internships.
  - Detail page = {base}/{path}/position/{id}/detail
"""
import re

import requests

from .http import UA, PoliteSession
from .model import make_job, ms_to_date

PAGE_SIZE = 100


def resolve_short_link(portal):
    """Some portals are short links like /s/b84uFgu7Ahc that answer with a 302.

    We only need the Location header (e.g. .../campus/position/list?share_token=...),
    so we do NOT follow the redirect: the target page returns 404 to non-browser
    clients, which made the first version of this function give up.
    Returns (base, path) or None."""
    try:
        r = requests.get(portal, allow_redirects=False, timeout=20, headers={"User-Agent": UA})
    except requests.RequestException:
        return None
    target = r.headers.get("Location", "")
    if target.startswith("/"):
        target = re.match(r"https?://[^/]+", portal).group(0) + target
    m = re.match(r"(https?://[^/]+)/([^/?#]+)", target)
    if not m or m.group(2) == "s":
        return None
    return m.group(1), m.group(2)


def fetch(source, max_pages=None, log=print):
    base, path = source["base"], source["path"]
    if path == "s":
        resolved = resolve_short_link(source["portal"])
        if not resolved:
            raise RuntimeError(f"cannot resolve short link {source['portal']}")
        base, path = resolved

    sess = PoliteSession(delay=0.8, headers={
        "Content-Type": "application/json",
        "website-path": path,
        "Referer": f"{base}/{path}/position",
    })
    token = sess.post_json(f"{base}/api/v1/csrf/token", {"portal_entrance": 1})["data"]["token"]
    sess.headers["x-csrf-token"] = token

    jobs, offset, pages = [], 0, 0
    while True:
        body = {
            "keyword": "", "limit": PAGE_SIZE, "offset": offset,
            "job_category_id_list": [], "location_code_list": [],
            "subject_id_list": [], "recruitment_id_list": [],
            "job_function_id_list": [], "portal_type": 6, "portal_entrance": 1,
        }
        resp = sess.post_json(f"{base}/api/v1/search/job/posts", body)
        if resp.get("code") != 0:
            raise RuntimeError(f"feishu api error: {resp.get('message')}")
        data = resp["data"]
        posts = data.get("job_post_list") or []
        for p in posts:
            rt = p.get("recruit_type") or {}
            parent = (rt.get("parent") or {}).get("name") or rt.get("name")
            if parent != "校招":
                continue  # skip social hiring
            cities = [c.get("name") for c in (p.get("city_list") or [])]
            if not cities and p.get("city_info"):
                cities = [p["city_info"].get("name")]
            jobs.append(make_job(
                src=source["src"],
                ext_id=p["id"],
                company=source["company"],
                ent_type=source["ent"],
                title=p.get("title"),
                recruit="实习" if rt.get("name") == "实习" else "校招",
                cities=cities,
                url=f"{base}/{path}/position/{p['id']}/detail",
                category=(p.get("job_category") or {}).get("name", ""),
                publish_date=ms_to_date(p.get("publish_time")),
                text="\n".join(filter(None, [p.get("title"), p.get("description"), p.get("requirement")])),
            ))
        pages += 1
        offset += PAGE_SIZE
        if not posts or offset >= (data.get("count") or 0):
            break
        if max_pages and pages >= max_pages:
            break
    return jobs
