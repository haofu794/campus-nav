"""Skill dictionary: canonical skill name -> the ways it is written in JDs/resumes.

The same dictionary is used on both sides (job text and my resume), so a match
always means "the same canonical skill". This is the cheap, explainable part of
matching; the LLM is only used offline to enrich my profile.
"""
import re

SKILLS = {
    "Python": ["python"], "Java": ["java"], "Go": ["golang", "go语言"], "C++": ["c++", "cpp"],
    "C": ["c语言"], "Rust": ["rust"], "JavaScript": ["javascript", "js"], "TypeScript": ["typescript", "ts"],
    "SQL": ["sql"], "Shell": ["shell", "bash"], "Scala": ["scala"], "Kotlin": ["kotlin"], "Swift": ["swift"],
    "React": ["react"], "Vue": ["vue"], "Node.js": ["node.js", "nodejs"], "Android": ["android", "安卓"],
    "iOS": ["ios"], "Flutter": ["flutter"],
    "FastAPI": ["fastapi"], "Django": ["django"], "Flask": ["flask"], "Spring": ["spring"],
    "MySQL": ["mysql"], "PostgreSQL": ["postgresql", "postgres"], "Redis": ["redis"], "MongoDB": ["mongodb"],
    "Elasticsearch": ["elasticsearch", "es搜索"], "Kafka": ["kafka"], "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"], "Linux": ["linux"], "Git": ["git"],
    "Spark": ["spark"], "Hadoop": ["hadoop"], "Flink": ["flink"], "Hive": ["hive"],
    "Pandas": ["pandas"], "NumPy": ["numpy"], "Scikit-learn": ["sklearn", "scikit-learn"],
    "PyTorch": ["pytorch", "torch"], "TensorFlow": ["tensorflow"], "Transformer": ["transformer"],
    "LangChain": ["langchain"], "RAG": ["rag", "检索增强"], "Agent": ["agent", "智能体"],
    "Prompt Engineering": ["prompt", "提示词"], "Fine-tuning": ["微调", "fine-tune", "finetune", "sft", "lora"],
    "大模型": ["大模型", "llm", "gpt"], "机器学习": ["机器学习", "machine learning"],
    "深度学习": ["深度学习", "deep learning"], "强化学习": ["强化学习", "rlhf"],
    "NLP": ["nlp", "自然语言处理"], "计算机视觉": ["计算机视觉", "cv", "图像识别"],
    "推荐系统": ["推荐系统", "推荐算法"], "搜索": ["搜索算法", "搜索引擎", "信息检索"],
    "多模态": ["多模态"], "向量数据库": ["向量数据库", "milvus", "faiss"],
    "分布式": ["分布式"], "微服务": ["微服务"], "高并发": ["高并发"], "数据库": ["数据库"],
    "数据分析": ["数据分析"], "数据挖掘": ["数据挖掘"], "数据可视化": ["可视化", "tableau", "power bi"],
    "Excel": ["excel"], "统计学": ["统计学", "统计分析"], "A/B测试": ["a/b", "ab测试", "ab实验"],
    "量化": ["量化"], "金融": ["金融"], "财务分析": ["财务分析", "财报"], "风控": ["风控"],
    "嵌入式": ["嵌入式"], "FPGA": ["fpga"], "自动驾驶": ["自动驾驶"], "机器人": ["机器人", "ros"],
    "英语": ["英语", "cet-6", "六级", "雅思", "托福", "ielts"],
}


def _pattern(term):
    esc = re.escape(term)
    left = r"(?<![a-z0-9])" if re.match(r"[a-z0-9]", term) else ""
    right = r"(?![a-z0-9+#])" if re.search(r"[a-z0-9]$", term) else ""
    return left + esc + right


_MATCHERS = [(name, re.compile("|".join(_pattern(t) for t in terms))) for name, terms in SKILLS.items()]


def extract_skills(text):
    low = (text or "").lower()
    return [name for name, rx in _MATCHERS if rx.search(low)]


def canonical(name):
    """Map a free-form skill (e.g. from the LLM) to a dictionary name if possible."""
    low = name.strip().lower()
    for canon, terms in SKILLS.items():
        if low == canon.lower() or low in terms:
            return canon
    return name.strip()
