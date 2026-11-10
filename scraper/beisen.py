"""Beisen (北森) scraper -- career sites on xxx.zhiye.com.

Lots of SOEs, insurers and car makers use it.

  POST {base}/api/Jobad/GetJobAdPageList
    Category ["2"] = campus full-time (校招), ["3"] = internship (实习)
    PageIndex starts at 0, PageSize up to 100 works.
  Detail page = {base}/campus/detail?jobAdId={Id}

Some tenants (e.g. 方太 fotile.zhiye.com) still run the OLD Beisen CMS portal:
the API path redirects to a 404 page, and the job list is rendered straight
into the HTML of {base}/campus/?PageIndex=N (10 jobs per page). There is no
JSON API to find in that case, so we fall back to parsing the HTML.
"""
import html as htmllib
import re

import requests

from .http import PoliteSession
from .model import make_job

PAGE_SIZE = 100
CATEGORIES = (("2", "校招"), ("3", "实习"))

LEGACY_ITEM = re.compile(
    r'<a href="/job_show\?jobId=(\d+)"[^>]*>\s*<dd>(.*?)</dd>\s*<ol>(.*?)</ol>\s*<dl>(.*?)</dl>', re.S)
TAGS = re.compile(r"<[^>]+>")


def _legacy_cities(loc):
    # "浙江省-宁波市-..." -> ["宁波"]; "河南省,安徽省-..." -> ["河南", "安徽"]; "全国" -> ["全国"]
    out = []
    for chunk in loc.replace("...", "").split(","):
        parts = [p.strip() for p in chunk.split("-") if p.strip()]
        cities = [p for p in parts if not p.endswith(("省", "自治区"))]
        out.extend(cities or parts[:1])
    return out


def fetch_legacy(source, max_pages=None, log=print):
    base = source["base"]
    sess = PoliteSession(delay=0.8, headers={"Accept": "text/html"})
    jobs, page = [], 1
    while True:
        page_html = sess.get(f"{base}/campus/?PageIndex={page}").text
        items = LEGACY_ITEM.findall(page_html)
        for job_id, title, meta, desc in items:
            title = htmllib.unescape(TAGS.sub("", title)).strip()
            title = re.sub(r"\s*[（(]J\d+[)）]?\s*$|\s*[（(]J\d*\.\.\.$", "", title).rstrip(".")
            loc, *rest = [x.strip() for x in htmllib.unescape(TAGS.sub("", meta)).split("｜")]
            date = rest[-1] if rest and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rest[-1]) else None
            text = htmllib.unescape(TAGS.sub(" ", desc))
            jobs.append(make_job(
                src=source["src"], ext_id=job_id, company=source["company"], ent_type=source["ent"],
                title=title,
                recruit="实习" if "实习" in title else "校招",  # the legacy list doesn't say; guess from title
                cities=_legacy_cities(loc),
                url=f"{base}/job_show?jobId={job_id}",
                publish_date=date,
                text=title + "\n" + text,
            ))
        if not items or f"PageIndex={page + 1}" not in page_html:
            break
        page += 1
        if max_pages and page > max_pages:
            break
    return jobs


def _is_legacy(base):
    # New portals answer the API with JSON; legacy ones redirect (302) to /404.
    try:
        r = requests.post(f"{base}/api/Jobad/GetJobAdPageList", json={"PageIndex": 0, "PageSize": 1},
                          allow_redirects=False, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException:
        return False
    return r.status_code in (301, 302)


def fetch(source, max_pages=None, log=print):
    if _is_legacy(source["base"]):
        return fetch_legacy(source, max_pages, log)
    try:
        return fetch_api(source, max_pages, log)
    except ValueError:
        # Non-JSON answer: the legacy check above can miss on a flaky first
        # request, so try the HTML route once before giving up.
        return fetch_legacy(source, max_pages, log)


def fetch_api(source, max_pages=None, log=print):
    base = source["base"]
    # timeout=45: some tenants (上海银行) take ~8 s per page from abroad.
    sess = PoliteSession(delay=0.8, timeout=45, headers={
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": f"{base}/campus/jobs",
    })
    jobs = []
    for cat, recruit in CATEGORIES:
        page = 0
        while True:
            body = {
                "PageIndex": page, "PageSize": PAGE_SIZE, "KeyWords": "",
                "SpecialType": 0, "PortalId": "",
                "DisplayFields": ["Category", "Kind", "LocId", "ClassificationOne"],
                "Category": [cat],
            }
            resp = sess.post_json(f"{base}/api/Jobad/GetJobAdPageList", body)
            if resp.get("Code") != 200:
                raise RuntimeError(f"beisen api error: {resp.get('Message')}")
            items = resp.get("Data") or []
            for d in items:
                # Titles end with an internal code like "(J19330)"; drop it.
                title = re.sub(r"\s*[（(]J\d+[)）]\s*$", "", d.get("JobAdName") or "")
                jobs.append(make_job(
                    src=source["src"],
                    ext_id=d["Id"],
                    company=source["company"],
                    ent_type=source["ent"],
                    title=title,
                    recruit=recruit,
                    cities=d.get("LocNames") or [],
                    url=f"{base}/campus/detail?jobAdId={d['Id']}",
                    category=d.get("ClassificationOne") or "",
                    publish_date=None,  # Beisen returns 0001-01-01 here, useless
                    text="\n".join(filter(None, [title, d.get("Duty"), d.get("Require")])),
                ))
            page += 1
            if not items or page * PAGE_SIZE >= (resp.get("Count") or 0):
                break
            if max_pages and page >= max_pages:
                break
    return jobs
