"""Ping An (中国平安) scraper -- its own campus site, campus.pingan.com.

Ping An doesn't use Feishu or Beisen, so the registry skips it. I found the API
by opening the job list in a browser and watching the Network panel:

  POST https://campus.pingan.com/zztj-recruit-talent-webserver/rctt/candidate/
       position/campus/positionSearch/queryPositionPage
    PageNum (starts at 1), pageSize (100 works)
    positionType "1" = 应届生 (校招), "2" = 实习
    wecruitId: the id of Ping An's campus site, copied from the page's own request
  Response: data.totalCount / data.totalPage / data.list

One site covers the whole group: 平安科技, 平安银行, 平安寿险, 平安产险,
平安证券, 平安金服 ... (field businessUnitName). I use that sub-company name as
the company, so filtering by "平安科技" works.

Detail page = https://campus.pingan.com/positionDetail?positionId={idPosition}
No login needed for the list or the detail page.
"""
from .http import PoliteSession
from .model import make_job

API = ("https://campus.pingan.com/zztj-recruit-talent-webserver/rctt/candidate/"
       "position/campus/positionSearch/queryPositionPage")
WECRUIT_ID = "6c1db1bba8c33deab19a733ec785711a"
PAGE_SIZE = 100
TYPES = (("1", "校招"), ("2", "实习"))


def fetch(source, max_pages=None, log=print):
    sess = PoliteSession(delay=1.0, timeout=30, headers={
        "Content-Type": "application/json",
        "Accept": "application/json;charset=utf-8",
        "Referer": "https://campus.pingan.com/freshGraduates",
    })
    jobs = []
    for ptype, recruit in TYPES:
        page = 1
        while True:
            body = {"PageNum": page, "pageSize": PAGE_SIZE, "businessUnitId": "", "positionCategoryId": "",
                    "wecruitId": WECRUIT_ID, "positionType": ptype, "wecruitPlatform": True,
                    "workCity": "", "interviewCity": ""}
            resp = sess.post_json(API, body)
            if resp.get("responseCode") != "10001":
                raise RuntimeError(f"pingan api error: {resp.get('responseMsg')}")
            data = resp.get("data") or {}
            for x in data.get("list") or []:
                unit = x.get("businessUnitName") or "中国平安"
                jobs.append(make_job(
                    src="pingan",
                    ext_id=x["idPosition"],
                    company=unit,
                    ent_type="银行" if "银行" in unit else "民企",
                    title=x.get("positionName"),
                    recruit=recruit,
                    cities=[x.get("workCity") or x.get("interviewCity") or ""],
                    url=f"https://campus.pingan.com/positionDetail?positionId={x['idPosition']}",
                    category=x.get("positionCategoryName") or "",
                    publish_date=(x.get("publishDate") or "")[:10] or None,
                    text="\n".join(filter(None, [x.get("positionName"), x.get("deptName"),
                                                 x.get("duty"), x.get("qualification")])),
                ))
            if page >= (data.get("totalPage") or 0):
                break
            page += 1
            if max_pages and page > max_pages:
                break
    return jobs
