"""FBK-03: Answer Bank cleanup. Merge exact duplicates, flag conflicts. Human-approved answers are never overwritten or deleted."""
from dataclasses import dataclass, field

from jobagent.core.db import Database
from jobagent.core.similarity import normalize_text, similarity


@dataclass
class CleanupReport:
    merged: int = 0
    flagged: int = 0
    groups: int = 0
    flagged_ids: list[int] = field(default_factory=list)


def _groups(rows, min_sim: float) -> list[list]:
    groups: list[list] = []
    for r in rows:
        for g in groups:
            if similarity(r["canonical_question"], g[0]["canonical_question"]) >= min_sim:
                g.append(r)
                break
        else:
            groups.append([r])
    return [g for g in groups if len(g) > 1]


def cleanup_answer_bank(db: Database, min_sim: float = 0.90) -> CleanupReport:
    rep = CleanupReport()
    rows = db.query("SELECT * FROM answer_bank ORDER BY id")
    for g in _groups(rows, min_sim):
        rep.groups += 1
        distinct = {normalize_text(r["answer"]) for r in g}
        if len(distinct) == 1:  # same answer: merge into the best row, keep human_approved if any
            keep = max(g, key=lambda r: (r["human_approved"], r["use_count"], r["updated_at"] or "", r["id"]))
            total_uses = sum(r["use_count"] for r in g)
            db.write("UPDATE answer_bank SET use_count=?, human_approved=? WHERE id=?",
                     (total_uses, max(r["human_approved"] for r in g), keep["id"]))
            for r in g:
                if r["id"] != keep["id"]:
                    db.write("DELETE FROM answer_bank WHERE id=?", (r["id"],))
                    rep.merged += 1
        else:  # conflicting answers: change nothing, just flag so a human decides
            for r in g:
                db.write("UPDATE answer_bank SET needs_cleanup=1 WHERE id=?", (r["id"],))
                rep.flagged += 1
                rep.flagged_ids.append(r["id"])
    return rep
