"""Tiny OpenAI-compatible chat client shared by the LLM features.

The key never goes in code or in git. Put it in ~/Desktop/job/.env (gitignored):
    LLM_API_KEY=sk-...
    LLM_BASE_URL=https://api.deepseek.com/v1   # optional, this is the default
    LLM_MODEL=deepseek-chat                    # optional, this is the default
Real environment variables win over .env.
"""
import json
import os
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config():
    load_env()
    return {
        "key": os.environ.get("LLM_API_KEY"),
        "base": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
        "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
    }


def chat_json(prompt, cfg, retries=3):
    """Send one user message, return the first JSON object in the reply."""
    body = {"model": cfg["model"], "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    for attempt in range(retries):
        try:
            r = requests.post(f"{cfg['base']}/chat/completions",
                              headers={"Authorization": f"Bearer {cfg['key']}"},
                              json=body, timeout=120)
            # Reasoning models (e.g. OpenAI gpt-5*) reject temperature != default:
            # drop it and retry instead of failing.
            if r.status_code == 400 and "temperature" in r.text and "temperature" in body:
                body.pop("temperature")
                continue
            if r.status_code in (401, 403, 404):
                raise SystemExit(f"API error {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", content, re.S)  # models sometimes wrap JSON in ```json
            if m:
                return json.loads(m.group(0))
        except (requests.RequestException, ValueError, KeyError):
            if attempt == retries - 1:
                raise
        time.sleep(2 * (attempt + 1))
    raise ValueError("no JSON in reply")
