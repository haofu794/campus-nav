"""Guopin (国聘, iguopin.com) scraper -- the SOE job platform, includes subsidiaries.

  POST https://gp-api.iguopin.com/api/jobs/v1/list
    params are flat (not wrapped in "search")
    nature: ["115xW5oQ"] = 校招, ["11bTac9"] = 实习
    district: ["000000.{province_code}"]
    page_size max 50, and the API stops at page 20 (= 1000 jobs per query).

Because of the 1000 cap, one query for "all campus jobs" would miss most of
them. So we split by province: 34 provinces x 2 natures, each query stays
under (or close to) 1000. If a province still has more than 1000 we log it.
"""
from .http import PoliteSession
from .model import make_job

API = "https://gp-api.iguopin.com/api/jobs/v1/list"
PAGE_SIZE = 50
MAX_PAGE = 20
NATURES = {"115xW5oQ": "校招", "11bTac9": "实习"}
PROVINCES = [
    "110000", "120000", "130000", "140000", "150000", "210000", "220000", "230000",
    "310000", "320000", "330000", "340000", "350000", "360000", "370000", "410000",
    "420000", "430000", "440000", "450000", "460000", "500000", "510000", "520000",
    "530000", "540000", "610000", "620000", "630000", "640000", "650000", "710000",
    "810000", "820000",
]


def _cities(x):
    # area_cn looks like "无锡-锡山区" or "北京"; keep the city part.
    return [d.get("area_cn", "").split("-")[0] for d in (x.get("district_list") or [])]


def _ent_type(company, nature_cn):
    # Guopin is mostly SOEs, but private companies post there too.
    # company_info.nature_cn says which ("国企", "央企", "民营" ...).
    if "银行" in company:
        return "银行"
    if any(k in nature_cn for k in ("国", "央", "事业")):
        return "央国企"
    if "外" in nature_cn:
        return "外企"
    return "民企" if nature_cn else "央国企"


def fetch(source, max_pages=None, log=print):
    sess = PoliteSession(delay=1.2, headers={
        "Content-Type": "application/json",
        "Origin": "https://www.iguopin.com",
        "Referer": "https://www.iguopin.com/",
    })
    seen, jobs = set(), []
    for province in PROVINCES:
        for nature, recruit in NATURES.items():
            for page in range(1, MAX_PAGE + 1):
                body = {"page": page, "page_size": PAGE_SIZE,
                        "nature": [nature], "district": [f"000000.{province}"]}
                resp = sess.post_json(API, body)
                if resp.get("code") != 200:
                    raise RuntimeError(f"guopin api error: {resp.get('msg')}")
                data = resp.get("data") or {}
                items = data.get("list") or []
                total = data.get("total") or 0
                if page == 1 and total > MAX_PAGE * PAGE_SIZE:
                    log(f"  [guopin] {province} {recruit}: {total} jobs, only first 1000 reachable")
                for x in items:
                    if x["job_id"] in seen:  # jobs in several provinces show up twice
                        continue
                    seen.add(x["job_id"])
                    company = x.get("company_name") or ""
                    jobs.append(make_job(
                        src=source["src"],
                        ext_id=x["job_id"],
                        company=company,
                        ent_type=_ent_type(company, (x.get("company_info") or {}).get("nature_cn", "")),
                        title=x.get("job_name"),
                        recruit=recruit,
                        cities=_cities(x),
                        url=f"https://www.iguopin.com/job/detail?id={x['job_id']}",
                        category=x.get("category_cn") or "",
                        publish_date=(x.get("start_time") or "")[:10] or None,
                        text="\n".join(filter(None, [x.get("job_name"), x.get("contents")])),
                    ))
                if len(items) < PAGE_SIZE or page * PAGE_SIZE >= total:
                    break
                if max_pages and page >= max_pages:
                    break
    return jobs
