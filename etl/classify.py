"""Put every job into one direction (方向).

Why rules and not an LLM: ~20k jobs a day, and the title (plus the site's own
category) is usually enough. Rules are free, instant and easy to debug: if a
job lands in the wrong bucket I can see exactly which keyword caused it.

Version 1 used one flat keyword list and was far too generous with 算法/AI:
any title containing "AI" or "大模型" went there, so "AI Agent 产品经理" and
"大模型运营实习生" were counted as AI jobs (about 1 in 5 of the AI bucket).
Version 2 decides in three tiers:

  1. STRONG title words: words that name the *role* itself
     ("算法", "前端", "测试", "产品经理", "运营" ...). If one matches, done.
  2. The site's own category ("算法", "后端", "运营" ...), when it maps cleanly.
  3. WEAK title words: words that name the *topic* ("AI", "大模型", "Agent",
     "开发" ...). Only used when nothing above matched.

So "AI Agent 产品经理" -> 产品 (role word beats topic word),
   "AI 应用开发工程师" -> 算法/AI (no role word, topic word decides).

Team suffixes are cut first: in "算法工程师 - Seed 产品研发" the part after
" - " is the team name, and its "产品" must not make this a product job.
"""
import re

STRONG = [
    ("算法/AI", ["算法", "机器学习", "深度学习", "nlp", "自然语言", "计算机视觉", "cv", "强化学习",
               "语音识别", "自动驾驶", "研究员", "scientist"]),
    ("前端/客户端", ["前端", "web", "客户端", "ios", "android", "安卓", "鸿蒙", "harmonyos", "flutter", "小程序"]),
    ("测试", ["测试", "质量保障", "qa"]),
    ("数据", ["数据分析", "数据科学", "数据挖掘", "数据开发", "数据工程", "数仓", "大数据开发"]),
    ("运营/市场", ["运营", "市场", "营销", "销售", "商务", "品牌", "bd", "客户经理", "增长", "电商", "公关"]),
    ("产品", ["产品经理", "产品实习", "产品专员", "产品助理", "产品策划", "产品设计"]),
    ("设计", ["设计师", "ui", "ux", "交互设计", "视觉设计", "美术", "原画"]),
    ("职能/管培", ["人力", "hr", "hrbp", "bp", "法务", "行政", "管培", "管理培训生", "文秘", "党建", "储备干部", "招聘"]),
    # Not "金融" here: bank titles like "金融科技岗（应用开发）" are dev jobs.
    ("金融/财会", ["财务", "会计", "审计", "精算", "风控", "投资", "证券", "信贷", "柜员"]),
    ("硬件/嵌入式", ["硬件", "嵌入式", "芯片", "fpga", "电路", "射频", "集成电路"]),
    # AI-application engineering roles. Checked last among strong words, so a
    # business role still wins ("AI Agent 产品经理" -> 产品), but they beat the
    # site category, which files many of them under plain "后端".
    ("算法/AI", ["ai应用", "大模型应用", "llm应用", "agent应用", "agent开发", "智能体开发", "ai agent",
               "agent工程", "ai工程师", "大模型工程师", "aigc应用"]),
]

# The site's own category text -> direction. Checked in order.
CATEGORY = [
    ("算法/AI", ["算法", "机器学习", "多模态", "智能体", "大语言模型", "nlp", "搜索、推荐", "模型应用", "ai基础设施"]),
    ("前端/客户端", ["前端", "客户端"]),
    ("测试", ["测试"]),
    ("数据", ["数据"]),
    ("运营/市场", ["运营", "销售", "市场"]),
    ("产品", ["产品"]),
    ("设计", ["设计"]),
    ("职能/管培", ["人力", "职能", "行政", "管培", "综合"]),
    ("金融/财会", ["财务", "金融"]),
    ("硬件/嵌入式", ["硬件", "制造"]),
    ("后端/开发", ["后端", "研发", "技术", "基础架构", "安全", "运维"]),
]

WEAK = [
    ("算法/AI", ["大模型", "llm", "vlm", "aigc", "agent", "智能体", "多模态", "ai", "人工智能", "模型",
               "推荐", "搜索", "语音"]),
    ("数据", ["数据分析", "数据科学", "数据挖掘", "数据开发", "数仓", "大数据", "数据工程", "bi", "数据"]),
    ("后端/开发", ["后端", "服务端", "java", "golang", "go", "c++", "python", "开发", "研发", "软件",
               "全栈", "架构", "sre", "运维", "infra", "基础架构", "安全", "工程师"]),
    ("产品", ["产品"]),
    ("硬件/嵌入式", ["电子", "电气", "通信", "ic", "机械", "结构", "电池"]),
    ("设计", ["设计"]),
    ("金融/财会", ["金融", "保险", "量化", "银行"]),
    ("职能/管培", ["综合"]),
]
OTHER = "其他"


def _pattern(word):
    # ASCII words need boundaries ("ai" must not match "mail"); Chinese words don't.
    if re.fullmatch(r"[a-z0-9+#.]+", word):
        return r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"
    return re.escape(word)


def _compile(rules):
    return [(name, re.compile("|".join(_pattern(w) for w in words))) for name, words in rules]


_STRONG, _CATEGORY, _WEAK = _compile(STRONG), _compile(CATEGORY), _compile(WEAK)


def role_part(title):
    """Drop the team suffix: 'X - Team' / 'X — Team' -> 'X'."""
    return re.split(r"\s+[-—–]\s+", title or "", maxsplit=1)[0]


def _first(rules, text):
    for name, rx in rules:
        if rx.search(text):
            return name
    return None


def classify(title, category=""):
    t = role_part(title).lower()
    # Brackets usually describe the business area, not the role:
    # "全栈开发工程师（电商营销）" is a dev job, so strong role words ignore them.
    t_role = re.sub(r"[（(【\[][^）)】\]]*[）)】\]]", " ", t)
    c = (category or "").lower()
    return (_first(_STRONG, t_role)
            or (_first(_CATEGORY, c) if c else None)
            or _first(_WEAK, t)
            or OTHER)


ALL_DIRECTIONS = sorted({d for d, _ in STRONG + CATEGORY + WEAK}) + [OTHER]
