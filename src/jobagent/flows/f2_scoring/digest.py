"""SCR-04 daily digest and SCR-05 manual apply/skip."""
from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.db import Database
from jobagent.core.notify import DigestChannel


def build_digest(db: Database, top_n: int = 10) -> tuple[str, list[int]]:
    rows = db.query(
        """SELECT j.id, j.title, j.company, j.status, j.apply_url, s.llm_score, s.reason FROM jobs j
           JOIN job_scores s ON s.job_id = j.id
           WHERE s.digested_at IS NULL AND j.status IN ('SCORED', 'MAYBE')
           ORDER BY (j.status = 'SCORED') DESC, s.llm_score DESC, j.id LIMIT ?""", (top_n,))
    if not rows:
        return "", []
    lines = ["Job digest - top matches", ""]
    for bucket_name, label in (("SCORED", "APPLY"), ("MAYBE", "MAYBE")):
        group = [r for r in rows if r["status"] == bucket_name]
        if group:
            lines.append(f"== {label} ({len(group)}) ==")
            for r in group:
                lines.append(f"[{r['llm_score']}] {r['title']} @ {r['company']}")
                lines.extend(f"    {ln}" for ln in (r["reason"] or "").splitlines())
                lines.append(f"    {r['apply_url']}")
    return "\n".join(lines), [r["id"] for r in rows]


def send_digest(db: Database, channel: DigestChannel, top_n: int = 10) -> bool:
    """Returns True if a digest was sent. With nothing new, a short 'No new matches' note goes out instead of an empty digest."""
    body, ids = build_digest(db, top_n)
    if not ids:
        channel.send("Job digest: no new matches", "No new matches today.")
        return False
    channel.send(f"Job digest: {len(ids)} new matches", body)
    for job_id in ids:
        db.write("UPDATE job_scores SET digested_at=? WHERE job_id=?", (db.now_iso(), job_id))
    return True


def manual_apply(db: Database, job_id: int) -> None:
    """User overrides the bucket: the job moves on as if it were in the Apply bucket."""
    status = db.scalar("SELECT status FROM jobs WHERE id=?", (job_id,))
    if status != st.SCORED:
        queue.advance(db, job_id, st.SCORED, note="manual apply")
    db.write("UPDATE jobs SET manual=1 WHERE id=?", (job_id,))


def skip_job(db: Database, job_id: int, note: str = "manual skip") -> None:
    queue.advance(db, job_id, st.SKIPPED, note=note)
