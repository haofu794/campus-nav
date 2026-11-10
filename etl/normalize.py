"""Make city names consistent across sources.

The same city shows up in many spellings:
  Feishu    "北京"
  Beisen    "北京市·丰台区", "贵州省·贵阳市", "江苏省·南京市/苏州市"
  Guopin    "无锡-锡山区"
  English   "Beijing"
All of them should end up as one short name like "北京" so the city filter works.
"""
import re

MUNICIPALITIES = {"北京", "上海", "天津", "重庆", "香港", "澳门"}
ENGLISH = {
    "beijing": "北京", "shanghai": "上海", "shenzhen": "深圳", "guangzhou": "广州",
    "hangzhou": "杭州", "chengdu": "成都", "wuhan": "武汉", "nanjing": "南京",
    "xi'an": "西安", "xian": "西安", "suzhou": "苏州", "tianjin": "天津",
    "chongqing": "重庆", "hong kong": "香港", "singapore": "新加坡",
}
SUFFIXES = ("特别行政区", "自治区", "地区", "省", "市")


def _strip(name):
    name = name.strip()
    for suf in SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf) + 1:
            return name[: -len(suf)]
    return name


def split_city(raw):
    """One raw location string -> list of clean city names."""
    s = (raw or "").strip()
    if not s:
        return []
    s = ENGLISH.get(s.lower(), s)
    if "·" in s:  # Beisen: "省·市" or "直辖市·区"
        prov, rest = s.split("·", 1)
        prov = _strip(prov)
        if prov in MUNICIPALITIES:
            return [prov]
        return [_strip(x) for x in re.split(r"[/、,，]", rest) if x.strip()]
    if "-" in s:  # Guopin: "无锡-锡山区"
        return [_strip(s.split("-")[0])]
    return [_strip(x) for x in re.split(r"[/、,，]", s) if x.strip()]


def normalize_cities(raw_list):
    out = []
    for raw in raw_list or []:
        for c in split_city(raw):
            if c and c not in out:
                out.append(c)
    return out


def norm_title(title):
    """Key used for de-duplication: lowercase, drop spaces and brackets."""
    return re.sub(r"[\s（）()【】\[\]\-_·]", "", (title or "").lower())
