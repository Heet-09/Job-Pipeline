"""Queue-via-DB (LLD 5.1): claim with a lease, advance through the status machine, fail with retries."""
from datetime import timedelta

from jobagent.core import statuses as st
from jobagent.core.db import Database
from jobagent.core.logging import get_logger

log = get_logger("jobagent.queue")


def claim(db: Database, status_from: str, worker: str, lease_min: int = 15):
    """Atomically lock the oldest job in status_from. Stale locks (older than the lease) are reclaimed."""
    now = db.now()
    stale = (now - timedelta(minutes=lease_min)).isoformat(timespec="seconds")
    cur = db.write(
        """UPDATE jobs SET locked_by=?, locked_at=? WHERE id = (
             SELECT id FROM jobs WHERE status=? AND (locked_by IS NULL OR locked_at < ?)
             ORDER BY discovered_at, id LIMIT 1) RETURNING *""",
        (worker, now.isoformat(timespec="seconds"), status_from, stale),
    )
    return getattr(cur, "fetchone", lambda: None)()


def advance(db: Database, job_id: int, new_status: str, note: str | None = None, error: str | None = None) -> None:
    row = db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
    if row is None:
        raise KeyError(f"job {job_id} not found")
    st.check_transition(row["status"], new_status)  # raises before anything is written
    now = db.now_iso()
    db.write("UPDATE jobs SET status=?, status_updated_at=?, locked_by=NULL, locked_at=NULL, last_error=COALESCE(?, last_error) WHERE id=?",
             (new_status, now, error, job_id))
    db.write("INSERT INTO job_history(job_id, from_status, to_status, note, at) VALUES (?,?,?,?,?)",
             (job_id, row["status"], new_status, note, now))
    log.info("job %s: %s -> %s %s", job_id, row["status"], new_status, note or "")


def release(db: Database, job_id: int) -> None:
    db.write("UPDATE jobs SET locked_by=NULL, locked_at=NULL WHERE id=?", (job_id,))


def fail(db: Database, job_id: int, error: str, max_attempts: int = 3) -> str:
    """Record a failure. Below max_attempts the job is released for retry; at the limit it becomes FAILED."""
    row = db.one("SELECT attempts, status FROM jobs WHERE id=?", (job_id,))
    attempts = (row["attempts"] or 0) + 1
    db.write("UPDATE jobs SET attempts=?, last_error=? WHERE id=?", (attempts, error[:500], job_id))
    if attempts >= max_attempts:
        advance(db, job_id, st.FAILED, note=f"failed after {attempts} attempts", error=error[:500])
        return st.FAILED
    release(db, job_id)
    return row["status"]
