"""Which companies exist, and how to scrape each one.

The company list comes from the open-source summary github.com/ouput/2027qiuzhao
(~1000 companies, each with a portal URL plus useful notes: when campus hiring
opened, which directions, and how to apply -- WeChat account, email, an event).
Extra companies can be added by hand in config/companies_extra.json.

Every company ends up in the "company directory" shown on the web page, even if
we can't scrape its individual jobs, because the notes (投递说明) are often the
fastest way in. On top of that, each portal is routed to a scraper:

  - URL is already xxx.jobs.feishu.cn/path or xxx.zhiye.com -> direct
  - company covered by campus-radar or the Ping An scraper     -> skip here
  - anything else -> scraper/detect.py figures out the system behind it
    (custom-domain Feishu / Beisen / Dayee hotjob, Moka, or truly custom)
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .detect import detect_all
from .http import PoliteSession

QZ_URL = "https://raw.githubusercontent.com/ouput/2027qiuzhao/main/data.json"
ENT_MAP = {"央企国企": "央国企", "外企": "外企", "民企": "民企", "事业单位": "事业单位"}

# Stop at whitespace: some entries append notes after the URL,
# e.g. "https://weilongmeiwei.jobs.feishu.cn/439244 ｜ 公众号：卫龙美味招聘".
FEISHU_RE = re.compile(r"https?://([a-z0-9-]+)\.jobs\.feishu\.cn/([^/?#\s]+)")
BEISEN_RE = re.compile(r"https?://([a-z0-9-]+)\.zhiye\.com")
OWN_SCRAPER = {"平安": "pingan"}  # name keyword -> dedicated scraper


def _first_url(portal):
    portal = (portal or "").strip()
    return portal.split()[0] if portal else ""


def _ent(item):
    if "银行" in item.get("company", ""):
        return "银行"
    return ENT_MAP.get(item.get("ent"), item.get("ent") or "民企")


def parse_portal(item):
    """Direct match on the URL alone (no network). Returns a scrape source or None."""
    portal = _first_url(item.get("portal"))
    company = item.get("company", "").strip()
    m = FEISHU_RE.match(portal)
    if m:
        tenant, path = m.group(1), m.group(2)
        return {"platform": "feishu", "src": f"feishu:{tenant}", "company": company, "ent": _ent(item),
                "base": f"https://{tenant}.jobs.feishu.cn", "path": path, "portal": portal}
    m = BEISEN_RE.match(portal)
    if m:
        tenant = m.group(1)
        return {"platform": "beisen", "src": f"beisen:{tenant}", "company": company, "ent": _ent(item),
                "base": f"https://{tenant}.zhiye.com", "portal": portal}
    return None


def _source_from_detect(item, d):
    company, ent, portal = item.get("company", "").strip(), _ent(item), _first_url(item.get("portal"))
    host = urlparse(d.get("base", "")).netloc
    if d["platform"] == "feishu":
        return {"platform": "feishu", "src": f"feishu:{host}", "company": company, "ent": ent,
                "base": d["base"], "path": d["path"], "portal": portal}
    if d["platform"] == "beisen":
        return {"platform": "beisen", "src": f"beisen:{host}", "company": company, "ent": ent,
                "base": d["base"], "portal": portal}
    if d["platform"] == "hotjob":
        key = d.get("suite") or f"wt-{d.get('wt_code')}"
        return {"platform": "hotjob", "src": f"hotjob:{key}", "company": company, "ent": ent,
                "base": d["base"], "suite": d.get("suite"), "wt_code": d.get("wt_code"), "portal": portal}
    return None


def load_companies(cache_path: Path, extra_path: Path, log=print):
    """The raw company list (2027qiuzhao + my extras). Falls back to the cache offline."""
    try:
        data = PoliteSession(timeout=30).get_json(QZ_URL)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 -- any failure means "use the cache"
        log(f"  [registry] fetch failed ({e}), using cached list")
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    items = list(data.get("data", []))
    if extra_path.exists():
        items += [i for i in json.loads(extra_path.read_text(encoding="utf-8")) if i.get("company")]
    return items


def plan(items, detect_cache: Path, skip_names=frozenset(), blacklist=(), do_detect=True, log=print):
    """Returns (sources, directory).

    sources   -- list of scrape sources for feishu / beisen / hotjob
    directory -- one entry per company for the web page, with how it's covered
    """
    sources, directory, seen = [], [], set()
    pending = []  # (index in directory, item) waiting for detection

    for item in items:
        name = item.get("company", "").strip()
        if not name or any(b in name for b in blacklist):
            continue
        entry = {
            "company": name, "cat": item.get("cat", ""), "ent": _ent(item),
            "opened": item.get("date", ""), "roles": item.get("roles", ""),
            "note": item.get("note", ""), "portal": _first_url(item.get("portal")),
            "portal_raw": (item.get("portal") or "").strip(), "status": None, "src": None,
        }
        own = next((v for k, v in OWN_SCRAPER.items() if k in name), None)
        src = parse_portal(item)
        if own:
            entry.update(status=own, src=own)
        elif any(n and (n == name or n in name) for n in skip_names):
            entry["status"] = "campus_radar"
        elif src:
            entry.update(status=src["platform"], src=src["src"])
            if src["src"] not in seen:
                seen.add(src["src"])
                sources.append(src)
        else:
            pending.append((len(directory), item))
        directory.append(entry)

    if pending:
        found = detect_all([(it["company"], _first_url(it.get("portal")) or (it.get("portal") or ""))
                            for _, it in pending], detect_cache, log=log, probe=do_detect)
        for idx, item in pending:
            d = found[item["company"]]
            src = _source_from_detect(item, d)
            directory[idx]["status"] = d["platform"]
            if src:
                directory[idx]["src"] = src["src"]
                if src["src"] not in seen:
                    seen.add(src["src"])
                    sources.append(src)
    return sources, directory
