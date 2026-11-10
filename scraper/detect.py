"""Find out which recruiting system is behind a company's career site.

Many "self-built" career sites are really a SaaS product under the company's
own domain: jobs.sigenergy.com is Feishu, zhaopin.xdf.cn is Beisen, job.gf.com.cn
is Dayee hotjob. If we can tell which product it is, the existing scraper for
that product works unchanged. So for each portal we:

  1. GET it (following redirects) and look at the final URL and the HTML for
     fingerprints ("jobs.feishu.cn"/"atsx" -> Feishu, "zhiye.com"/"beisen" ->
     Beisen, "hotjob" -> Dayee, "mokahr" -> Moka).
  2. Verify with one cheap API call, and find the missing piece each scraper
     needs (Feishu: the portal path; Dayee: the "SU..." suite key).

Results are cached in data/platform_cache.json for CACHE_DAYS days, so the
daily run doesn't re-probe ~800 websites; the first run takes a few minutes.

Statuses:
  feishu / beisen / hotjob -> scraped by the matching scraper
  moka        -> encrypted API, link only (we don't break encryption)
  unknown     -> a truly custom site; link + 投递说明 only for now
  unreachable -> timed out from here (often Chinese sites from abroad)
  no_url      -> the entry only names a WeChat account or an email address
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests

from .http import UA

CACHE_DAYS = 7
TIMEOUT = 8
FEISHU_PATHS = ("campus", "index", "school", "campus-recruitment", "campusrecruitment")


def _get(url):
    return requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True)


def _feishu_campus_count(base, path):
    """How many campus jobs a Feishu portal path has (None if the path doesn't exist)."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Content-Type": "application/json", "website-path": path})
    try:
        tok = s.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1}, timeout=TIMEOUT).json()
        s.headers["x-csrf-token"] = tok["data"]["token"]
        d = s.post(f"{base}/api/v1/search/job/posts", timeout=TIMEOUT, json={
            "keyword": "", "limit": 100, "offset": 0, "portal_type": 6, "portal_entrance": 1,
            "job_category_id_list": [], "location_code_list": [], "subject_id_list": [],
            "recruitment_id_list": [], "job_function_id_list": []}).json()
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    if d.get("code") != 0:
        return None
    posts = (d.get("data") or {}).get("job_post_list") or []
    return sum(1 for p in posts
               if ((p.get("recruit_type") or {}).get("parent") or {}).get("name") == "校招")


def _detect_feishu(final_url):
    p = urlparse(final_url)
    base = f"{p.scheme}://{p.netloc}"
    first = [x for x in p.path.split("/") if x][:1]
    tried = None
    for path in dict.fromkeys(first + list(FEISHU_PATHS)):
        n = _feishu_campus_count(base, path)
        if n is None:
            continue
        tried = tried or path
        if n > 0:
            return {"platform": "feishu", "base": base, "path": path}
    if tried:  # portal exists but has no campus jobs right now
        return {"platform": "feishu", "base": base, "path": tried}
    return None


def _detect_beisen(final_url):
    p = urlparse(final_url)
    base = f"{p.scheme}://{p.netloc}"
    try:
        r = requests.post(f"{base}/api/Jobad/GetJobAdPageList", json={"PageIndex": 0, "PageSize": 1},
                          timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=False)
    except requests.RequestException:
        return None
    ok_json = r.status_code == 200 and r.text.lstrip().startswith("{")
    legacy = r.status_code in (301, 302)
    return {"platform": "beisen", "base": base} if (ok_json or legacy) else None


def _detect_hotjob(final_url, html):
    """Dayee has two generations:
      new: {host}/SU<24 hex>/pb/...   the suite key is in the URL, the HTML, or (for
           xxx.hotjob.cn sub-domains) returned by POST /wecruit/common/getSLD
      old: {host}/wt/<code>/...       separate list API, see scraper/hotjob.py
    """
    p = urlparse(final_url)
    base = f"{p.scheme}://{p.netloc}"
    m = re.search(r"/wt/([A-Za-z0-9_-]+)/", final_url)
    if m:
        return {"platform": "hotjob", "base": base, "wt_code": m.group(1)}
    m = re.search(r"(SU[0-9a-f]{24})", final_url) or re.search(r"(SU[0-9a-f]{24})", html)
    if not m:
        try:
            # form field "sld" = the full host name, e.g. goertek.hotjob.cn
            r = requests.post(f"{base}/wecruit/common/getSLD", data={"sld": p.netloc},
                              timeout=TIMEOUT, headers={"User-Agent": UA})
            m = re.search(r"(SU[0-9a-f]{24})", r.text)
        except requests.RequestException:
            m = None
    if not m:
        return None
    return {"platform": "hotjob", "base": base, "suite": m.group(1)}


def detect(portal):
    portal = (portal or "").strip()
    if not portal.startswith("http"):
        return {"platform": "no_url"}
    url = portal.split()[0]
    if "mokahr.com" in url:  # decidable from the URL alone, no request needed
        return {"platform": "moka"}
    try:
        r = _get(url)
    except requests.RequestException:
        return {"platform": "unreachable"}
    final, html = r.url, r.text[:300_000]
    low_url, low = final.lower(), html.lower()
    if "mokahr" in low_url or "mokahr" in low:
        return {"platform": "moka"}
    if "hotjob" in low_url or "hotjob" in low:
        found = _detect_hotjob(final, html)
        if found:
            return found
    if "jobs.feishu.cn" in low_url or "atsx" in low or "jobs.feishu" in low:
        found = _detect_feishu(final)
        if found:
            return found
    if "zhiye.com" in low_url or "beisen" in low:
        found = _detect_beisen(final)
        if found:
            return found
    return {"platform": "unknown", "final_url": final}


def detect_all(items, cache_path: Path, log=print, workers=32, probe=True):
    """items: [(key, portal)]. Returns {key: result}, using/refreshing the cache.
    probe=False: never touch the network, use whatever the cache has."""
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    today = date.today()
    if not probe:
        return {k: cache.get(k, {"platform": "unknown"}) for k, _ in items}
    todo = [(k, p) for k, p in items
            if k not in cache or cache[k].get("portal") != p
            or (today - date.fromisoformat(cache[k]["checked"])).days >= CACHE_DAYS]
    if todo:
        log(f"  [detect] probing {len(todo)} career sites ({len(items) - len(todo)} cached)")

        def one(kp):
            k, p = kp
            res = detect(p)
            res.update({"portal": p, "checked": today.isoformat()})
            return k, res

        with ThreadPoolExecutor(workers) as ex:
            for i, (k, res) in enumerate(ex.map(one, todo), 1):
                cache[k] = res
                if i % 100 == 0:  # save progress, a long first run can be resumed
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {k: cache[k] for k, _ in items}
