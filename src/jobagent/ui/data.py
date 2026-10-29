"""Read/write helpers behind the dashboard. No Streamlit in here, so everything is unit-testable."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.flows.f7_feedback.metrics import bucket_response_rates, weekly_funnel

PIPELINE_ORDER = [st.DISCOVERED, st.JD_PARTIAL, st.EXTRACTED, st.SCORED, st.MAYBE, st.REJECTED, st.TAILORED, st.FILLED,
                  st.NEEDS_HUMAN, st.APPROVED, st.SUBMITTED, st.SUBMIT_UNCERTAIN, st.SKIPPED, st.EXTRACTION_FAILED, st.FAILED]
APPLICATION_STATUSES = ["SUBMITTED", "RECEIVED", "SHORTLISTED", "INTERVIEW", "REJECTED", "GHOSTED"]


def status_counts(db: Database) -> dict[str, int]:
    got = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    return {s: got.get(s, 0) for s in PIPELINE_ORDER}


def overview(db: Database, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    now = db.now()
    counts = status_counts(db)
    apps = {r["current_status"]: r["n"] for r in db.query(
        "SELECT current_status, COUNT(*) n FROM applications WHERE submitted_at IS NOT NULL GROUP BY current_status")}
    today = now.date().isoformat()
    llm = db.one("SELECT COUNT(*) calls, COALESCE(SUM(cost_usd),0) cost, COALESCE(SUM(prompt_tokens+completion_tokens),0) tokens FROM llm_calls")
    return {
        "total_jobs": sum(counts.values()), "counts": counts, "applications": apps,
        "submitted_total": sum(apps.values()),
        "submitted_today": db.scalar("SELECT COUNT(*) FROM applications WHERE submitted_at LIKE ?", (today + "%",)) or 0,
        "daily_cap": settings.daily_submit_cap,
        "funnel_7d": weekly_funnel(db, now - timedelta(days=7)),
        "buckets": bucket_response_rates(db),
        "llm_calls": llm["calls"], "llm_cost": llm["cost"], "llm_tokens": llm["tokens"],
        "last_discovery": db.scalar("SELECT MAX(discovered_at) FROM jobs"),
    }


def attention_items(db: Database, profile_path: Path | None = None) -> list[tuple[str, str, str]]:
    """(severity, message, page) for everything that needs the user. Empty list = nothing to do."""
    items: list[tuple[str, str, str]] = []
    c = status_counts(db)

    def add(sev, n, text, page):
        if n:
            items.append((sev, f"{n} {text}", page))
    add("high", c[st.NEEDS_HUMAN], "job(s) need you (CAPTCHA, login wall, missing sensitive answer or changed form)", "Review")
    add("high", c[st.SUBMIT_UNCERTAIN], "application(s) clicked submit but showed no confirmation - check manually", "Applications")
    add("medium", c[st.FILLED], "filled application(s) waiting for your approval", "Review")
    add("medium", db.scalar("SELECT COUNT(*) FROM manual_review WHERE resolved=0") or 0, "email(s) could not be matched automatically", "Inbox")
    add("medium", db.scalar("SELECT COUNT(*) FROM applications WHERE current_status='INTERVIEW'") or 0, "application(s) at interview stage", "Applications")
    add("medium", c[st.SCORED], "Apply-bucket job(s) not yet tailored/filled", "Jobs")
    add("low", c[st.FAILED] + c[st.EXTRACTION_FAILED], "job(s) failed processing", "Jobs")
    add("low", db.scalar("SELECT COUNT(*) FROM answer_bank WHERE needs_cleanup=1") or 0, "saved answer(s) conflict and need cleanup", "Answer Bank")
    if profile_path is not None:
        p = Path(profile_path)
        if not p.exists():
            items.append(("high", "No profile.json yet - run build-profile from your resume", "Health"))
        else:
            try:
                from jobagent.flows.f0_profile.loader import load_profile
                from jobagent.flows.f0_profile.sensitive import missing_sensitive
                miss = missing_sensitive(load_profile(p))
                if miss:
                    items.append(("medium", f"Sensitive profile fields not set: {', '.join(miss)} (forms asking for them will need you)", "Health"))
            except Exception as e:
                items.append(("high", f"profile.json is unreadable: {str(e)[:80]}", "Health"))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(items, key=lambda x: order[x[0]])


def jobs_table(db: Database, status: list[str] | None = None, source: str | None = None, min_score: int | None = None,
               search: str | None = None, limit: int = 1000) -> list[dict]:
    where, params = ["1=1"], []
    if status:
        where.append(f"j.status IN ({','.join('?' * len(status))})")
        params += status
    if source:
        where.append("j.source = ?")
        params.append(source)
    if min_score is not None:
        where.append("COALESCE(s.llm_score, -1) >= ?")
        params.append(min_score)
    if search:
        where.append("(j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ?)")
        params += [f"%{search}%"] * 3
    rows = db.query(f"""SELECT j.id, j.title, j.company, j.location, j.status, s.llm_score AS score, j.source, j.posted_at,
                               j.discovered_at, j.manual, j.flags, j.apply_url AS url, j.attempts, j.last_error
                        FROM jobs j LEFT JOIN job_scores s ON s.job_id = j.id WHERE {' AND '.join(where)}
                        ORDER BY (s.llm_score IS NULL), s.llm_score DESC, j.discovered_at DESC, j.id DESC LIMIT ?""", (*params, limit))
    return [dict(r) for r in rows]


def sources(db: Database) -> list[str]:
    return [r["source"] for r in db.query("SELECT DISTINCT source FROM jobs ORDER BY source")]


def job_detail(db: Database, job_id: int) -> dict | None:
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if job is None:
        return None
    score = db.one("SELECT * FROM job_scores WHERE job_id=?", (job_id,))
    breakdown = json.loads(score["breakdown"]) if score and score["breakdown"] else {}
    return {
        "job": dict(job), "score": dict(score) if score else None, "breakdown": breakdown,
        "jd": json.loads(job["jd_json"]) if job["jd_json"] else {},
        "history": [dict(r) for r in db.query("SELECT from_status, to_status, note, at FROM job_history WHERE job_id=? ORDER BY id", (job_id,))],
        "application": dict(a) if (a := db.one("SELECT * FROM applications WHERE job_id=?", (job_id,))) else None,
        "llm_calls": db.scalar("SELECT COUNT(*) FROM llm_calls WHERE job_id=?", (job_id,)) or 0,
    }


def applications_table(db: Database, settings: Settings | None = None) -> list[dict]:
    settings = settings or Settings()
    now = db.now()
    out = []
    for r in db.query("""SELECT a.id, a.job_id, j.title, j.company, COALESCE(a.current_status, j.status) AS status, a.submitted_at, a.approved_at,
                                a.confirmation_shot, a.resume_flag, a.resume_path, a.last_checked_at,
                                (SELECT MAX(at) FROM status_events e WHERE e.application_id = a.id) AS last_event
                         FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.submitted_at IS NOT NULL
                         ORDER BY a.submitted_at DESC"""):
        d = dict(r)
        last = max(x for x in (d["submitted_at"], d["last_event"]) if x)
        idle = (now - datetime.fromisoformat(last)).days
        d["days_since_submit"] = (now - datetime.fromisoformat(d["submitted_at"])).days
        d["ghost_in_days"] = max(settings.ghost_after_days - idle, 0) if d["status"] in ("SUBMITTED", "RECEIVED") else None
        out.append(d)
    return out


def application_events(db: Database, application_id: int) -> list[dict]:
    return [dict(r) for r in db.query("SELECT status, snippet, email_id, at FROM status_events WHERE application_id=? ORDER BY id", (application_id,))]


def set_application_status(db: Database, application_id: int, status: str, note: str = "set manually") -> None:
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"unknown application status {status!r}")
    db.write("UPDATE applications SET current_status=? WHERE id=?", (status, application_id))
    db.write("INSERT INTO status_events(application_id, status, email_id, snippet, at) VALUES (?,?,?,?,?)",
             (application_id, status, None, note, db.now_iso()))


def review_queue(db: Database) -> list[dict]:
    return [dict(r) for r in db.query(
        """SELECT j.id, j.title, j.company, j.status, j.last_error,
                  (SELECT COUNT(*) FROM form_answers f WHERE f.job_id = j.id) AS fields,
                  (SELECT COUNT(*) FROM form_answers f WHERE f.job_id = j.id AND f.needs_review = 1) AS to_review
           FROM jobs j WHERE j.status IN ('FILLED', 'NEEDS_HUMAN') ORDER BY (j.status = 'NEEDS_HUMAN') DESC, j.id""")]


def manual_review_rows(db: Database, include_resolved: bool = False) -> list[dict]:
    q = "SELECT * FROM manual_review" + ("" if include_resolved else " WHERE resolved=0") + " ORDER BY id DESC"
    return [dict(r) for r in db.query(q)]


def open_applications(db: Database) -> list[dict]:
    return [dict(r) for r in db.query("""SELECT a.id, j.title, j.company, a.current_status FROM applications a JOIN jobs j ON j.id=a.job_id
                                         WHERE a.submitted_at IS NOT NULL ORDER BY j.company""")]


def resolve_manual(db: Database, review_id: int, application_id: int | None = None, status: str | None = None) -> None:
    """The user looked at an unmatched/unclear email. Optionally attach it to an application with a status."""
    row = db.one("SELECT * FROM manual_review WHERE id=?", (review_id,))
    if row is None:
        raise KeyError(f"manual review item {review_id} not found")
    if application_id is not None and status:
        set_application_status(db, application_id, status, note=f"from email '{(row['subject'] or '')[:80]}'")
    db.write("UPDATE manual_review SET resolved=1 WHERE id=?", (review_id,))


def bank_rows(db: Database) -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM answer_bank ORDER BY needs_cleanup DESC, use_count DESC, id")]


def update_bank_answer(db: Database, bank_id: int, answer: str) -> None:
    db.write("UPDATE answer_bank SET answer=?, human_approved=1, needs_cleanup=0, updated_at=? WHERE id=?", (answer, db.now_iso(), bank_id))


def delete_bank_answer(db: Database, bank_id: int) -> None:
    db.write("DELETE FROM answer_bank WHERE id=?", (bank_id,))


def llm_summary(db: Database) -> list[dict]:
    return [dict(r) for r in db.query(
        """SELECT flow, model, COUNT(*) calls, SUM(ok) ok, SUM(prompt_tokens) prompt_tokens, SUM(completion_tokens) completion_tokens,
                  ROUND(SUM(cost_usd), 4) cost_usd, ROUND(AVG(latency_ms)) avg_latency_ms FROM llm_calls GROUP BY flow, model ORDER BY cost_usd DESC""")]


def recent_history(db: Database, limit: int = 100) -> list[dict]:
    return [dict(r) for r in db.query(
        """SELECT h.at, h.job_id, j.title, j.company, h.from_status, h.to_status, h.note FROM job_history h
           JOIN jobs j ON j.id = h.job_id ORDER BY h.id DESC LIMIT ?""", (limit,))]


def profile_versions(db: Database) -> list[dict]:
    return [dict(r) for r in db.query("SELECT hash, version, saved_at FROM profile_versions ORDER BY version DESC")]
