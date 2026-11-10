"""Turn my resume PDF into config/profile.json (skills + keywords).

Run it once, and again whenever the resume changes:

    python -m matching.profile resume/my_resume.pdf

Two extraction methods, merged:
  1. Dictionary match (always, free, same dictionary as the job side).
  2. LLM (optional). If LLM_API_KEY is set, an OpenAI-compatible chat API is
     asked to list skills and focus keywords. Works with DeepSeek, Qwen,
     OpenAI etc. -- set LLM_BASE_URL and LLM_MODEL accordingly.

This runs on my own machine only. The key never goes into the web page.
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

from etl.skills import canonical, extract_skills

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "profile.json"

PROMPT = """下面是一份简历。请提取：
1. skills: 技术技能和工具（编程语言、框架、算法领域等），每项尽量用常见英文或中文标准写法
2. keywords: 最能代表这个人求职方向的 5-10 个关键词（如 "LLM Agent"、"RAG"、"财报分析"）
只输出 JSON：{"skills": [...], "keywords": [...]}

简历：
"""


def read_pdf(path):
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def llm_extract(text):
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "temperature": 0,
              "messages": [{"role": "user", "content": PROMPT + text[:8000]}]},
        timeout=60,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)  # models sometimes wrap JSON in ```json
    return json.loads(m.group(0)) if m else None


def build_profile(pdf_path):
    text = read_pdf(pdf_path)
    skills = extract_skills(text)
    keywords, method = [], "dictionary"
    try:
        llm = llm_extract(text)
    except Exception as e:  # noqa: BLE001 -- the LLM is optional, fall back quietly
        print(f"LLM failed, using dictionary only: {e}")
        llm = None
    if llm:
        method = "dictionary+llm"
        for s in llm.get("skills", []):
            c = canonical(s)
            if c not in skills:
                skills.append(c)
        keywords = llm.get("keywords", [])
    return {"skills": skills, "keywords": keywords, "method": method,
            "generated_at": date.today().isoformat()}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m matching.profile <resume.pdf>")
    profile = build_profile(sys.argv[1])
    OUT.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}: {len(profile['skills'])} skills ({profile['method']})")
    print("skills:", ", ".join(profile["skills"]))
    if profile["keywords"]:
        print("keywords:", ", ".join(profile["keywords"]))
