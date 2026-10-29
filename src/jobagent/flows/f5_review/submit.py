"""F5 submit: replay the reviewed answers on the form, then (and only then) click submit.

Safety rules (REV-05, REV-06):
- the job must not already be submitted or SUBMIT_UNCERTAIN (never apply twice),
- if the page no longer matches what was reviewed, abort -> NEEDS_HUMAN and do NOT click submit,
- if no confirmation appears after clicking, the job is SUBMIT_UNCERTAIN and is never retried automatically.
"""
import re
import time
from dataclasses import dataclass
from pathlib import Path

from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.logging import get_logger
from jobagent.core.notify import Notifier
from jobagent.flows.f4_formfill.browser import open_page
from jobagent.flows.f4_formfill.filler import advance_page, fill_field, find_next_button, submit_button
from jobagent.flows.f4_formfill.guards import BLOCK_SUBMIT_JS, safe_click
from jobagent.flows.f4_formfill.snapshot import take_snapshot

log = get_logger("jobagent.submit")

CONFIRM_TEXT = re.compile(r"thank you|application (has been |was |is )?(received|submitted|sent)|successfully (applied|submitted)|we(?:'ve| have) received your application", re.I)
CONFIRM_URL = re.compile(r"confirm|thank|success|submitted", re.I)


class DuplicateApplication(Exception):
    """This job was already submitted (or its submit outcome is unknown)."""


class ReplayMismatch(Exception):
    """The page no longer matches the reviewed answers."""


@dataclass
class SubmitResult:
    status: str
    reason: str = ""
    confirmation_shot: str | None = None


def ensure_not_submitted(db: Database, job_id: int) -> None:
    job = db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
    app = db.one("SELECT submitted_at FROM applications WHERE job_id=?", (job_id,))
    if job["status"] == st.SUBMIT_UNCERTAIN:
        raise DuplicateApplication(f"job {job_id} has an uncertain earlier submit - check the employer's site/email before re-applying")
    if job["status"] == st.SUBMITTED or (app and app["submitted_at"]):
        raise DuplicateApplication(f"job {job_id} was already submitted")


def _saved_rows(db: Database, job_id: int) -> dict[int, dict[str, dict]]:
    pages: dict[int, dict[str, dict]] = {}
    for r in db.query("SELECT * FROM form_answers WHERE job_id=? ORDER BY id", (job_id,)):
        pages.setdefault(r["page_no"], {})[r["field_ref"]] = dict(r)
    return pages


def wait_for_confirmation(page, timeout_s: float) -> bool:
    end = time.monotonic() + timeout_s
    while True:
        try:
            if CONFIRM_URL.search(page.url) and not page.url.endswith(".html") or CONFIRM_TEXT.search(page.inner_text("body")):
                return True
        except Exception:
            pass  # page is navigating
        if time.monotonic() >= end:
            return False
        page.wait_for_timeout(150)


def _replay(page, db, job, saved, settings, shots_dir, confirm_timeout) -> SubmitResult:
    page.add_init_script(BLOCK_SUBMIT_JS)
    page.goto(job["apply_url"])
    page_no = 0
    while True:
        page_no += 1
        snap = take_snapshot(page)
        if snap.captcha or snap.login_wall or snap.unknown_widgets:
            raise ReplayMismatch(f"page {page_no}: captcha / login wall / unknown widget appeared")
        rows = saved.get(page_no)
        if rows is None:
            raise ReplayMismatch(f"page {page_no} was not part of the reviewed form")
        missing = [ref for ref, r in rows.items() if r["answer"] is not None and ref not in snap.refs]
        extra_required = [f.label for f in snap.fields if f.required and f.ref not in rows]
        if missing or extra_required:
            raise ReplayMismatch(f"page {page_no}: form changed since review (missing {missing[:2]}, new required {extra_required[:2]})")
        for spec in snap.fields:
            r = rows.get(spec.ref)
            if r and r["answer"] is not None:
                fill_field(page, spec, r["answer"], snap)
        nxt = find_next_button(page)
        if nxt is not None:
            if not advance_page(page, nxt, snap.refs):
                raise ReplayMismatch(f"page {page_no}: could not move to the next page")
            continue
        if page_no != max(saved):
            raise ReplayMismatch(f"form has {page_no} pages now, {max(saved)} were reviewed")
        btn = submit_button(page)
        if btn is None:
            raise ReplayMismatch("no submit button found on the last page")
        Path(shots_dir).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(shots_dir) / f"job{job['id']}_presubmit.png"), full_page=True)
        page.evaluate("window.__jobagent_allow_submit = true")
        safe_click(btn, allow_submit=True)     # the ONLY place in the codebase that passes allow_submit=True
        shot = str(Path(shots_dir) / f"job{job['id']}_confirmation.png")
        ok = wait_for_confirmation(page, confirm_timeout)
        page.screenshot(path=shot, full_page=True)
        return SubmitResult(st.SUBMITTED if ok else st.SUBMIT_UNCERTAIN, "" if ok else "no confirmation page detected", shot)


def submit_application(db: Database, job_id: int, settings: Settings, notifier: Notifier, shots_dir: Path,
                       headless: bool = True, page=None, user_data_dir: Path | None = None,
                       confirm_timeout: float = 5.0) -> SubmitResult:
    ensure_not_submitted(db, job_id)
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    saved = _saved_rows(db, job_id)
    try:
        if page is not None:
            res = _replay(page, db, job, saved, settings, shots_dir, confirm_timeout)
        else:
            with open_page(headless, user_data_dir) as pg:
                res = _replay(pg, db, job, saved, settings, shots_dir, confirm_timeout)
    except ReplayMismatch as e:
        queue.advance(db, job_id, st.NEEDS_HUMAN, note=f"replay aborted, nothing submitted: {e}")
        notifier.alert("needs_human", f"Job {job_id}: form changed after review - NOT submitted. {e}")
        return SubmitResult(st.NEEDS_HUMAN, str(e))
    except Exception as e:
        # We cannot know whether submit was clicked, so treat any later failure as uncertain only if it happened after the click.
        queue.advance(db, job_id, st.NEEDS_HUMAN, note=f"submit failed before submitting: {str(e)[:150]}")
        notifier.alert("needs_human", f"Job {job_id}: submit step failed ({str(e)[:100]}) - not submitted.")
        return SubmitResult(st.NEEDS_HUMAN, str(e))

    now = db.now_iso()
    if res.status == st.SUBMITTED:
        db.write("UPDATE applications SET submitted_at=?, confirmation_shot=?, current_status='SUBMITTED' WHERE job_id=?", (now, res.confirmation_shot, job_id))
        queue.advance(db, job_id, st.SUBMITTED, note="confirmation detected")
    else:
        db.write("UPDATE applications SET confirmation_shot=? WHERE job_id=?", (res.confirmation_shot, job_id))
        queue.advance(db, job_id, st.SUBMIT_UNCERTAIN, note=res.reason)
        notifier.alert("submit_uncertain", f"Job {job_id}: clicked submit but saw no confirmation. NOT retrying - please check manually.")
    return res
