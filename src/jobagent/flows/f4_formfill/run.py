"""F4: fill an application form page by page and STOP before submit. Answers are saved to form_answers."""
from dataclasses import dataclass, field
from pathlib import Path

from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.llm import LLMClient
from jobagent.core.logging import get_logger
from jobagent.core.notify import Notifier
from jobagent.core.schemas import JDExtract, Profile
from jobagent.flows.f0_profile.versioning import hash_for_versioning
from jobagent.flows.f4_formfill.answer_bank import AnswerBank
from jobagent.flows.f4_formfill.browser import open_page
from jobagent.flows.f4_formfill.filler import advance_page, fill_field, find_next_button
from jobagent.flows.f4_formfill.guards import BLOCK_SUBMIT_JS
from jobagent.flows.f4_formfill.mapper import map_fields
from jobagent.flows.f4_formfill.resolver import ResolveContext, resolve
from jobagent.flows.f4_formfill.snapshot import take_snapshot

log = get_logger("jobagent.formfill")
PAGE_RETRIES = 3


@dataclass
class FillResult:
    status: str
    pages: int = 0
    problems: list[str] = field(default_factory=list)
    rows: int = 0


def _fill_form(page, db, job_id, url, ctx, mapper_llm, settings, shots_dir) -> tuple[list[dict], list[str], int]:
    rows: list[dict] = []
    problems: list[str] = []
    page.add_init_script(BLOCK_SUBMIT_JS)
    page.goto(url)
    page_no = 0
    while page_no < settings.max_pages:
        page_no += 1
        snap = take_snapshot(page)
        for flag, msg in ((snap.captcha, "CAPTCHA detected - a human must solve it"),
                          (snap.login_wall, "login wall - a human must sign in"),
                          (bool(snap.unknown_widgets), f"unknown widget(s) {snap.unknown_widgets} - cannot fill safely")):
            if flag:
                problems.append(f"page {page_no}: {msg}")
                return rows, problems, page_no
        maps = map_fields(snap.fields, mapper_llm)
        for spec in snap.fields:
            fmap = maps[spec.ref]
            ans = resolve(spec, fmap, ctx)
            row = dict(page_no=page_no, field_ref=spec.ref, field_label=spec.label, field_type=spec.type, answer=ans.answer,
                       source=ans.source, confidence=ans.confidence, needs_review=int(ans.needs_review))
            if ans.answer is not None and fmap.category != "skip":
                try:
                    fill_field(page, spec, ans.answer, snap)
                except Exception as e:
                    row["needs_review"] = 1
                    problems.append(f"page {page_no}: could not fill '{spec.label}': {str(e)[:80]}")
            elif spec.required and fmap.category != "skip":
                problems.append(f"page {page_no}: required field '{spec.label}' has no answer ({fmap.category}) - needs the user")
            rows.append(row)
        if shots_dir:
            Path(shots_dir).mkdir(parents=True, exist_ok=True)
            shot = str(Path(shots_dir) / f"job{job_id}_p{page_no}.png")
            page.screenshot(path=shot, full_page=True)
            for r in rows:
                if r["page_no"] == page_no:
                    r["screenshot"] = shot
        nxt = find_next_button(page)
        if nxt is None:
            return rows, problems, page_no
        if not advance_page(page, nxt, snap.refs):
            problems.append(f"page {page_no}: could not move to the next page (validation error?)")
            return rows, problems, page_no
    problems.append(f"form has more than {settings.max_pages} pages")
    return rows, problems, page_no


def fill_application(db: Database, job_id: int, profile: Profile, resume_path: str | None, settings: Settings,
                     notifier: Notifier, llm: LLMClient | None = None, bank: AnswerBank | None = None,
                     jd: JDExtract | None = None, shots_dir: Path | None = None, headless: bool = True,
                     page=None, user_data_dir: Path | None = None, map_with_llm: bool = False) -> FillResult:
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    bank = bank or AnswerBank(db, min_sim=settings.bank_min_sim)
    ctx = ResolveContext(profile=profile, now=db.now(), bank=bank, llm=llm, jd=jd, resume_path=resume_path, job_id=job_id)
    rows: list[dict] = []
    problems: list[str] = []
    pages = 0
    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            if page is not None:
                rows, problems, pages = _fill_form(page, db, job_id, job["apply_url"], ctx, llm if map_with_llm else None, settings, shots_dir)
            else:
                with open_page(headless, user_data_dir) as pg:
                    rows, problems, pages = _fill_form(pg, db, job_id, job["apply_url"], ctx, llm if map_with_llm else None, settings, shots_dir)
            break
        except Exception as e:  # transient browser trouble: retry the whole fill (it is idempotent)
            log.warning("fill attempt %d for job %s failed: %s", attempt, job_id, e)
            if attempt == PAGE_RETRIES:
                problems.append(f"browser error: {str(e)[:120]}")

    db.write("DELETE FROM form_answers WHERE job_id=?", (job_id,))
    for r in rows:
        db.write("INSERT INTO form_answers(job_id, page_no, field_ref, field_label, field_type, answer, source, confidence, needs_review, screenshot)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (job_id, r["page_no"], r["field_ref"], r["field_label"], r["field_type"], r["answer"], r["source"],
                  r["confidence"], r["needs_review"], r.get("screenshot")))
    if problems:
        queue.advance(db, job_id, st.NEEDS_HUMAN, note="; ".join(problems)[:300])
        notifier.alert("needs_human", f"Job {job_id} ({job['title']} @ {job['company']}) needs you: {'; '.join(problems)}")
        return FillResult(st.NEEDS_HUMAN, pages, problems, len(rows))
    db.write("""INSERT INTO applications(job_id, profile_hash, filled_at) VALUES (?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET filled_at=excluded.filled_at, profile_hash=COALESCE(applications.profile_hash, excluded.profile_hash)""",
             (job_id, hash_for_versioning(profile), db.now_iso()))
    queue.advance(db, job_id, st.FILLED, note=f"{len(rows)} fields over {pages} page(s); stopped before submit")
    return FillResult(st.FILLED, pages, [], len(rows))
