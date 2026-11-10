"""The one job format every scraper must return.

Each source (Feishu, Beisen, Guopin, campus-radar) has different field names.
Converting them to the same dict as early as possible means the ETL step only
has to understand one shape.
"""
from datetime import datetime, timezone

RECRUIT_TYPES = ("校招", "实习")


def make_job(*, src, ext_id, company, ent_type, title, recruit, cities, url,
             category="", publish_date=None, text="", skills=None):
    """Build a normalized job dict.

    src       -- which tenant/source it came from, e.g. "feishu:agirobot". Used for
                 fallback: if one source fails today we keep its jobs from yesterday.
    ext_id    -- the job id on the original site.
    recruit   -- "校招" (full-time new grad) or "实习" (internship).
    url       -- direct link to the job detail page (not the company homepage).
    text      -- JD text, only used for skill extraction and ranking; it is NOT
                 written to data.json to keep the file small.
    skills    -- optional pre-extracted skill tags (campus-radar already has them).
    """
    assert recruit in RECRUIT_TYPES, recruit
    return {
        "id": f"{src}:{ext_id}",
        "src": src,
        "company": (company or "").strip(),
        "ent": ent_type,
        "title": (title or "").strip(),
        "recruit": recruit,
        "cities_raw": [c for c in (cities or []) if c],
        "url": url,
        "category": category or "",
        "publish": publish_date,
        "text": text or "",
        "skills": skills,
    }


def ms_to_date(ms):
    """Feishu returns milliseconds since 1970; turn it into 'YYYY-MM-DD'."""
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
