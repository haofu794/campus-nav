"""Dayee (大易) hotjob scraper -- wecruit.hotjob.cn/{suite key}/pb/... and custom domains.

Found by watching the Network panel on 云南白药's career site:

  POST {base}/wecruit/positionInfo/listPosition/{SU key}?iSaJAx=isAjax&request_locale=zh_CN
    form body (NOT json): isFrompb=true, recruitType, pageSize, currentPage (starts at 1)
    recruitType 1 = 校园招聘, 2 = 社会招聘 (skipped), 3 = 实习 (where the tenant has it)
    the server caps pageSize (12 or 50 seen), so we just follow data.pageForm.totalPage
  Detail page = {base}/{SU key}/pb/posDetail.html?postId={postId}&postType=campus

The suite key looks like "SU" + 24 hex chars and appears in the portal URL or,
for custom domains (job.10086.cn, job.gf.com.cn ...), in the page HTML.

Older tenants (伊利, TCL, 华熙生物 ...) run the previous generation under
{host}/wt/<code>/ with a different list API:
  GET {host}/wt/<code>/mobweb/jsonp/position/list?recruitType=1&page=N&rowSize=50
  -> {"pageCount": .., "postList": [{postId, postName, workPlace, companyName, ...}]}
  Detail page = {host}/wt/<code>/mobweb/v8/position/detail?postId={postId}&recruitType=1
"""
import time

from .http import PoliteSession
from .model import make_job

# Only recruitType 1 (校园招聘). Type numbers above 1 are NOT consistent across
# tenants: on 伊利's site type 3 returned ~1000 jobs like "灌装工段长", i.e. not
# internships. Internships inside the campus list are recognised by title.
TYPES = ((1, "校招", "campus"),)


def fetch_wt(source, max_pages=None, log=print):
    base, code = source["base"], source["wt_code"]
    sess = PoliteSession(delay=0.8, timeout=30)
    jobs = []
    for rtype, recruit, _ in TYPES:
        page = 1
        while True:
            d = sess.get_json(f"{base}/wt/{code}/mobweb/jsonp/position/list"
                              f"?recruitType={rtype}&page={page}&rowSize=50")
            for x in d.get("postList") or []:
                title = x.get("postName") or ""
                jobs.append(make_job(
                    src=source["src"], ext_id=x["postId"], company=source["company"], ent_type=source["ent"],
                    title=title,
                    recruit="实习" if (recruit == "实习" or "实习" in title) else "校招",
                    cities=(x.get("workPlace") or "").split(","),
                    url=f"{base}/wt/{code}/mobweb/v8/position/detail?postId={x['postId']}&recruitType={rtype}",
                    category=x.get("postType") or "",
                    publish_date=x.get("publishDate"),
                    text="\n".join(filter(None, [title, x.get("companyName"), x.get("subject")])),
                ))
            if page >= (d.get("pageCount") or 0):
                break
            page += 1
            if max_pages and page > max_pages:
                break
    return jobs


def fetch(source, max_pages=None, log=print):
    if source.get("wt_code"):
        return fetch_wt(source, max_pages, log)
    try:
        return fetch_suite(source, max_pages, log)
    except ValueError:
        # Some custom domains (job.gf.com.cn, 迪卡侬, 湘电) serve the pages but not
        # the API; the same suite key works on Dayee's own domain.
        if source["base"] == "https://wecruit.hotjob.cn":
            raise
        return fetch_suite({**source, "base": "https://wecruit.hotjob.cn"}, max_pages, log)


def fetch_suite(source, max_pages=None, log=print):
    base, su = source["base"], source["suite"]
    sess = PoliteSession(delay=0.8, timeout=30, headers={
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base}/{su}/pb/school.html",
    })
    jobs = []
    for rtype, recruit, post_type in TYPES:
        page = 1
        while True:
            r = sess.s.post(  # form-encoded body, so not post_json
                f"{base}/wecruit/positionInfo/listPosition/{su}?iSaJAx=isAjax&request_locale=zh_CN",
                data={"isFrompb": "true", "recruitType": rtype, "pageSize": 50, "currentPage": page},
                timeout=sess.timeout)
            sess._last = time.time()
            form = ((r.json().get("data") or {}).get("pageForm") or {})
            for x in form.get("pageData") or []:
                title = x.get("postName") or ""
                jobs.append(make_job(
                    src=source["src"],
                    ext_id=x["postId"],
                    company=source["company"],
                    ent_type=source["ent"],
                    title=title,
                    recruit="实习" if (recruit == "实习" or "实习" in title) else "校招",
                    cities=(x.get("workPlaceStr") or "").split(","),
                    url=f"{base}/{su}/pb/posDetail.html?postId={x['postId']}&postType={post_type}",
                    category=x.get("postTypeName") or "",
                    publish_date=(x.get("publishFirstDate") or x.get("publishDate") or "")[:10] or None,
                    text="\n".join(filter(None, [title, x.get("company"), x.get("subject")])),
                ))
            if page >= (form.get("totalPage") or 0):
                break
            page += 1
            if max_pages and page > max_pages:
                break
            sess._wait()
    return jobs
