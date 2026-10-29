"""F3 worker: SCORED (score >= auto_tailor, or manual apply) -> TAILORED, with PDF and diff saved."""
from dataclasses import dataclass
from pathlib import Path

from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.llm import LLMClient
from jobagent.core.logging import get_logger
from jobagent.core.schemas import JDExtract, Profile
from jobagent.flows.f0_profile.versioning import hash_for_versioning
from jobagent.flows.f3_resume.graph import run_tailor_loop
from jobagent.flows.f3_resume.renderer import render_pdf, resume_text, unified_diff
from jobagent.flows.f3_resume.tailor import base_draft, resolve
from jobagent.flows.f3_resume.validator import Checker

log = get_logger("jobagent.tailor")


@dataclass
class TailorSummary:
    tailored: int = 0
    fallbacks: int = 0
    failed: int = 0


def run_tailoring(db: Database, profile: Profile, llm: LLMClient | None, out_dir: Path, settings: Settings,
                  checker: Checker | None = None, worker: str = "f3", batch: int = 20) -> TailorSummary:
    summary = TailorSummary()
    for _ in range(batch):
        job = queue.claim(db, st.SCORED, worker, settings.lease_min,
                          extra_sql="(manual=1 OR id IN (SELECT job_id FROM job_scores WHERE llm_score >= ?))",
                          extra_params=(settings.auto_tailor,))
        if job is None:
            break
        try:
            jd = JDExtract.model_validate_json(job["jd_json"] or "{}")
            draft, violations = run_tailor_loop(profile, jd, llm, checker, job["id"])
            resume = resolve(draft, profile)
            base_text = resume_text(resolve(base_draft(profile), profile))
            pdf = render_pdf(resume, Path(out_dir) / f"job_{job['id']}.pdf")
            flag = "fallback_base_resume" if draft.fallback else None
            db.write(
                """INSERT INTO applications(job_id, resume_path, resume_diff, resume_flag, profile_hash)
                   VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET resume_path=excluded.resume_path,
                   resume_diff=excluded.resume_diff, resume_flag=excluded.resume_flag, profile_hash=excluded.profile_hash""",
                (job["id"], str(pdf.path), unified_diff(base_text, resume_text(resume)), flag, hash_for_versioning(profile)))
            queue.advance(db, job["id"], st.TAILORED, note=flag or "tailored")
            summary.tailored += 1
            summary.fallbacks += bool(draft.fallback)
        except Exception as e:
            log.error("tailoring job %s failed: %s", job["id"], e)
            queue.fail(db, job["id"], str(e), settings.max_attempts)
            summary.failed += 1
    return summary
