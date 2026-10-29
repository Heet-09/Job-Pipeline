"""F5 decisions: approve / skip / edit, the daily cap, the delay between submits, and the auto-submit switch."""
import random
import time
from pathlib import Path

from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.logging import get_logger
from jobagent.core.notify import Notifier
from jobagent.flows.f4_formfill.answer_bank import AnswerBank
from jobagent.flows.f5_review.submit import DuplicateApplication, SubmitResult, ensure_not_submitted, submit_application

log = get_logger("jobagent.review")


class DailyLimitReached(Exception):
    pass


class AutoSubmitDisabled(Exception):
    pass


def submitted_today(db: Database) -> int:
    today = db.now().date().isoformat()
    return db.scalar("SELECT COUNT(*) FROM applications WHERE submitted_at LIKE ?", (today + "%",)) or 0


def throttle(db: Database, settings: Settings, sleep=time.sleep, rng=random) -> float:
    """Wait so that consecutive submits are 45-120 s apart (random). Returns seconds waited."""
    last = db.scalar("SELECT MAX(submitted_at) FROM applications")
    if not last:
        return 0.0
    from datetime import datetime
    lo, hi = settings.between_submits_sec
    target = rng.randint(lo, hi)
    wait = target - (db.now() - datetime.fromisoformat(last)).total_seconds()
    if wait > 0:
        log.info("waiting %.0fs between submissions", wait)
        sleep(wait)
        return wait
    return 0.0


def skip(db: Database, job_id: int) -> None:
    queue.advance(db, job_id, st.SKIPPED, note="skipped at review")


def edit_answer(db: Database, job_id: int, answer_id: int, new_answer: str, bank: AnswerBank | None = None) -> None:
    """Save the user's edit; edits to drafted/banked answers are remembered for future forms (REV-03)."""
    row = db.one("SELECT * FROM form_answers WHERE id=? AND job_id=?", (answer_id, job_id))
    if row is None:
        raise KeyError(f"answer {answer_id} not found for job {job_id}")
    db.write("UPDATE form_answers SET answer=?, source='human', confidence=1.0, needs_review=0, approved=1 WHERE id=?", (new_answer, answer_id))
    if row["source"] in ("llm", "bank", "human") and row["field_type"] in ("text", "textarea", "select", "radio"):
        (bank or AnswerBank(db)).upsert(row["field_label"], new_answer, human_approved=True)


def approve(db: Database, job_id: int, settings: Settings, notifier: Notifier, shots_dir: Path, *, sleep=time.sleep,
            rng=random, page=None, headless: bool = True, user_data_dir: Path | None = None,
            confirm_timeout: float = 5.0) -> SubmitResult:
    ensure_not_submitted(db, job_id)                       # REV-06: never apply twice
    if submitted_today(db) >= settings.daily_submit_cap:   # REV-04
        raise DailyLimitReached(f"Daily submit limit reached ({settings.daily_submit_cap}/day). Try again tomorrow.")
    throttle(db, settings, sleep, rng)
    queue.advance(db, job_id, st.APPROVED, note="approved")
    db.write("UPDATE applications SET approved_at=? WHERE job_id=?", (db.now_iso(), job_id))
    db.write("UPDATE form_answers SET approved=1 WHERE job_id=?", (job_id,))
    bank = AnswerBank(db, min_sim=settings.bank_min_sim)
    for r in db.query("SELECT * FROM form_answers WHERE job_id=? AND source IN ('llm','bank','human') AND answer IS NOT NULL "
                      "AND field_type IN ('text','textarea','select','radio')", (job_id,)):
        bank.upsert(r["field_label"], r["answer"], human_approved=True)  # approved by the user => human_approved
    return submit_application(db, job_id, settings, notifier, shots_dir, headless, page, user_data_dir, confirm_timeout)


def maybe_auto_submit(db: Database, job_id: int, settings: Settings, notifier: Notifier, shots_dir: Path, **kw) -> SubmitResult:
    """SAF-01: submits without a human only when config explicitly sets auto_submit: true."""
    if not settings.auto_submit:
        raise AutoSubmitDisabled("auto_submit is off; this application needs your approval")
    return approve(db, job_id, settings, notifier, shots_dir, **kw)
