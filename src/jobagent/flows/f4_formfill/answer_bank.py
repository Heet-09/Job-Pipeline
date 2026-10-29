"""Answer Bank (FRM-03): reuse earlier answers for similar questions. Human-approved answers win."""
from dataclasses import dataclass

from jobagent.core.db import Database
from jobagent.core.similarity import Embedder, similarity, trigram_embed


@dataclass
class Hit:
    id: int
    answer: str
    sim: float
    human_approved: bool


class AnswerBank:
    def __init__(self, db: Database, embed: Embedder = trigram_embed, min_sim: float = 0.90):
        self.db, self.embed, self.min_sim = db, embed, min_sim

    def lookup(self, question: str) -> Hit | None:
        best: Hit | None = None
        for r in self.db.query("SELECT * FROM answer_bank"):
            sim = similarity(question, r["canonical_question"], self.embed)
            if sim < self.min_sim:
                continue
            hit = Hit(r["id"], r["answer"], sim, bool(r["human_approved"]))
            if best is None or (hit.human_approved, hit.sim) > (best.human_approved, best.sim):
                best = hit
        return best

    def mark_used(self, hit_id: int) -> None:
        self.db.write("UPDATE answer_bank SET use_count = use_count + 1 WHERE id=?", (hit_id,))

    def upsert(self, question: str, answer: str, human_approved: bool) -> int:
        """Update the closest existing entry (>= min_sim) or insert a new one. Never downgrades human_approved."""
        hit = self.lookup(question)
        now = self.db.now_iso()
        if hit:
            self.db.write("UPDATE answer_bank SET answer=?, human_approved=MAX(human_approved, ?), updated_at=? WHERE id=?",
                          (answer, int(human_approved), now, hit.id))
            return hit.id
        cur = self.db.write("INSERT INTO answer_bank(canonical_question, answer, human_approved, updated_at) VALUES (?,?,?,?)",
                            (question, answer, int(human_approved), now))
        return cur.lastrowid
