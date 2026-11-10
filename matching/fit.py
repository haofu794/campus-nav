"""Does a job suit me, beyond "the text looks similar"? (the `avoid` feature)

bm25 / emb / skill all measure one thing: how much the JD text overlaps my
resume. My labels showed the failure that follows: of the jobs I marked 0
that the embedding scored high, nearly all were *similar but unsuitable*:
  - research algorithm roles that really want papers (I have none),
  - operations / product roles that happen to mention 大模型,
  - risk-control / content-safety teams I'm not interested in.
Similarity can't express "similar but not for me", so this is a separate
signal with a NEGATIVE weight (picked by cross-validation, see matching/tune.py).

It's a penalty, not a filter: keyword rules misfire ("研究" also appears in
"应用研究"), and a penalty only pushes such a job down instead of hiding it.

Rules live in config/my_prefs.json -> "avoid", so they change with my
preferences, not with the code. Each fired rule becomes a visible reason.
"""
import re

# Signs a role expects research output. Title words are strong evidence on
# their own; JD text needs explicit paper/venue language, because "博士优先"
# appears in plenty of ordinary engineering JDs.
RESEARCH_TITLE = re.compile(r"研究员|研究型|scientist|预训练|pre-?train|强化学习|(?<![a-z])rl(?![a-z])|博士|phd|top ?seed", re.I)
PAPER_TEXT = re.compile(
    r"顶会|顶级会议|顶刊|一作|first[- ]author|发表.{0,12}论文|论文.{0,6}发表|"
    r"(?<![a-z])(cvpr|iccv|eccv|neurips|nips|icml|iclr|acl|emnlp|naacl|kdd|aaai|ijcai|sigir|www)(?![a-z])", re.I)


def avoid(job, cfg):
    """Return (0 or 1, reason). cfg = prefs["avoid"]."""
    title = job.get("title", "")
    if job.get("direction") in set(cfg.get("directions", [])):
        return 1.0, f"不想做的方向: {job['direction']}"
    if cfg.get("research", True):
        m = RESEARCH_TITLE.search(title) or PAPER_TEXT.search(job.get("text", "") or "")
        if m:
            return 1.0, f"偏研究/要论文: {m.group(0)}"
    for w in cfg.get("keywords", []):
        if w.lower() in title.lower():
            return 1.0, f"不想去的领域: {w}"
    return 0.0, ""
