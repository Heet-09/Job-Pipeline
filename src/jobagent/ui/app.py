"""Job Pipeline dashboard (Streamlit). Run with:  python -m jobagent.cli ui

Reads the same SQLite database the pipeline writes. Everything here is local: nothing leaves your machine.
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from jobagent.core import statuses as S
from jobagent.core.config import load_settings
from jobagent.core.db import Database
from jobagent.flows.f2_scoring.digest import manual_apply, skip_job
from jobagent.flows.f4_formfill.answer_bank import AnswerBank
from jobagent.flows.f5_review import decide
from jobagent.flows.f5_review.review import build_review
from jobagent.flows.f5_review.submit import DuplicateApplication
from jobagent.flows.f7_feedback.cleanup import cleanup_answer_bank
from jobagent.ui import data as D

DB_PATH = Path(os.environ.get("JOBAGENT_DB", "data/jobagent.db"))
PROFILE_PATH = Path(os.environ.get("JOBAGENT_PROFILE", "data/profile.json"))
SHOTS_DIR = DB_PATH.parent / "screenshots"
PAGES = ["Overview", "Jobs", "Review", "Applications", "Inbox", "Answer Bank", "Health"]
TERMINAL = {S.SKIPPED, S.SUBMITTED, S.FAILED}

st.set_page_config(page_title="Job Pipeline", page_icon=":briefcase:", layout="wide")
if "page" not in st.session_state:
    st.session_state["page"] = "Overview"


def goto(page: str):
    st.session_state["page"] = page


def table(rows: list[dict], columns: list[str] | None = None, key: str | None = None, select: bool = False):
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Nothing here yet.")
        return None
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    for col in df.columns:
        if col == "at" or col.endswith("_at") or col == "last_event":
            df[col] = df[col].map(lambda v: v[:16].replace("T", " ") if isinstance(v, str) else v)
    if select:
        ev = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=key)
        idx = ev.selection.rows
        return rows[idx[0]] if idx else None
    st.dataframe(df, hide_index=True, width="stretch")
    return None


# ---------------------------------------------------------------- pages
def page_overview(db: Database, settings):
    o = D.overview(db, settings)
    if o["total_jobs"] == 0:
        st.info("No jobs yet. Collect some:  `python -m jobagent.cli collect-naukri Jobs.xlsx`  then  `python -m jobagent.cli score`.")
    c = o["counts"]
    cols = st.columns(6)
    cols[0].metric("Jobs found", o["total_jobs"])
    cols[1].metric("Apply bucket", c[S.SCORED], help="score 70+")
    cols[2].metric("Maybe", c[S.MAYBE], help="score 50-69")
    cols[3].metric("Ready to review", c[S.FILLED])
    cols[4].metric("Submitted", o["submitted_total"])
    cols[5].metric("Interviews", o["applications"].get("INTERVIEW", 0))
    st.progress(min(o["submitted_today"] / o["daily_cap"], 1.0), text=f"Submitted today: {o['submitted_today']} / {o['daily_cap']}")

    items = D.attention_items(db, PROFILE_PATH)
    st.subheader("Needs your attention" if items else "Nothing needs your attention")
    icons = {"high": "🔴", "medium": "🟠", "low": "🔵"}
    if items:
        with st.container(border=True):
            for sev, msg, page in items:
                c1, c2 = st.columns([12, 1])
                c1.markdown(f"{icons[sev]} {msg}")
                c2.button("Open", key=f"open-{msg}", on_click=goto, args=(page,))

    left, right = st.columns(2)
    with left:
        st.markdown("**Where every job is in the pipeline**")
        st.bar_chart(pd.Series(c, name="jobs"), horizontal=True)
    with right:
        f = o["funnel_7d"]
        st.markdown(f"**Last 7 days** ({f.week_start} to {f.week_end})")
        a, b, c3, d = st.columns(4)
        a.metric("Discovered", f.discovered)
        b.metric("Applied", f.applied)
        c3.metric("Responses", f.responses)
        d.metric("Interviews", f.interviews)
        st.markdown("**Response rate by score bucket** (shortlisted/interview out of applied)")
        table([{"bucket": r.bucket, "applied": r.applied, "positive": r.positive, "rate": "n/a" if r.rate is None else f"{r.rate:.0f}%"} for r in o["buckets"]])
        if o["applications"]:
            st.markdown("**Applications by status**")
            st.bar_chart(pd.Series(o["applications"], name="applications"), horizontal=True)
    st.caption(f"Last job discovered: {o['last_discovery'] or 'never'} | LLM: {o['llm_calls']} calls, ${o['llm_cost']:.4f}")


def page_jobs(db: Database, settings):
    f1, f2, f3, f4 = st.columns([3, 2, 2, 3])
    status = f1.multiselect("Status", D.PIPELINE_ORDER, default=[s for s in D.PIPELINE_ORDER if s not in (S.SKIPPED, S.REJECTED)])
    source = f2.selectbox("Source", ["(all)"] + D.sources(db))
    min_score = f3.slider("Min score", 0, 100, 0)
    search = f4.text_input("Search title / company / location")
    rows = D.jobs_table(db, status or None, None if source == "(all)" else source, min_score or None, search or None)
    st.caption(f"{len(rows)} jobs. Tick the box at the left of a row to see its details.")
    picked = table(rows, ["id", "title", "company", "location", "status", "score", "source", "posted_at", "flags", "manual"], key="jobs-table", select=True)
    if not picked:
        return
    d = D.job_detail(db, picked["id"])
    j = d["job"]
    st.divider()
    st.subheader(f"{j['title']} @ {j['company']}")
    st.markdown(f"**{j['status']}** | {j['location'] or 'location n/a'} | posted {j['posted_at'] or 'unknown'} | source {j['source']} | [open job page]({j['apply_url']})")
    if j["last_error"]:
        st.error(f"Last error ({j['attempts']} attempt(s)): {j['last_error']}")
    a, b = st.columns(2)
    with a:
        if d["score"]:
            st.metric("Score", f"{d['score']['llm_score']} / 100", help=f"scored by: {d['score']['model']}")
            for name, mx in (("skills", 40), ("seniority", 20), ("salary", 15), ("role_type", 15), ("company", 10)):
                v = d["breakdown"].get(name, 0)
                st.progress(v / mx, text=f"{name}: {v} / {mx}")
            st.write(d["score"]["reason"])
        else:
            st.info("Not scored yet.")
        jd = d["jd"]
        if jd:
            st.markdown(f"**Must-have skills:** {', '.join(jd.get('must_have_skills', [])) or '-'}  \n"
                        f"**Experience:** {jd.get('exp_min')} - {jd.get('exp_max')} yrs | **Salary:** {jd.get('salary_range') or 'not stated'} | "
                        f"**Type:** {jd.get('role_category')}")
    with b:
        st.markdown("**History**")
        table(d["history"], ["at", "from_status", "to_status", "note"])
    if j["jd_raw"]:
        with st.expander("Full job description"):
            st.text(j["jd_raw"])
    x, y, _ = st.columns([1, 1, 4])
    if j["status"] in (S.MAYBE, S.REJECTED):
        if x.button("Apply anyway", key="apply-anyway"):
            manual_apply(db, j["id"])
            st.rerun()
    if j["status"] not in TERMINAL and S.SKIPPED in S.TRANSITIONS[j["status"]]:
        if y.button("Skip this job", key="skip-job"):
            skip_job(db, j["id"])
            st.rerun()


def page_review(db: Database, settings):
    queue = D.review_queue(db)
    if not queue:
        st.success("No applications waiting for review.")
        return
    labels = {f"#{q['id']} {q['title']} @ {q['company']}  [{q['status']}, {q['to_review']} to check]": q["id"] for q in queue}
    job_id = labels[st.selectbox("Application", list(labels))]
    r = build_review(db, job_id)
    j = r["job"]
    st.subheader(f"{j['title']} @ {j['company']}  ({j['status']})")
    err = db.scalar("SELECT last_error FROM jobs WHERE id=?", (job_id,))
    note = db.scalar("SELECT note FROM job_history WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
    if j["status"] == S.NEEDS_HUMAN:
        st.error(f"The agent stopped and needs you: {note or err or 'see answers below'}")
    if r["score"]:
        st.caption(f"Score {r['score']['llm_score']}: {r['score']['reason']}")
    st.markdown(f"[Open the application page]({j['url']})")

    st.markdown("#### Answers (yellow = please check)")
    for a in r["answers"]:
        if a["field_type"] == "file" or a["answer"] is None and not a["needs_review"]:
            continue
        flag = a["needs_review"]
        c1, c2, c3 = st.columns([3, 5, 1])
        c1.markdown(f"{':warning: ' if flag else ''}**{a['field_label']}**  \n:gray[{a['source']} - conf {a['confidence'] or 0:.2f}]")
        new = c2.text_area("answer", a["answer"] or "", key=f"ans-{a['id']}", label_visibility="collapsed", height=70 if len(a["answer"] or "") > 60 else 40)
        if new != (a["answer"] or "") and c3.button("Save", key=f"save-{a['id']}"):
            decide.edit_answer(db, job_id, a["id"], new)
            st.rerun()
    left, right = st.columns(2)
    with left:
        st.markdown("#### Form screenshots")
        for p in r["screenshots"]:
            if Path(p).exists():
                st.image(p, width="stretch")
    with right:
        st.markdown("#### Resume changes")
        if r["resume_flag"]:
            st.warning(f"Resume flag: {r['resume_flag']} (validator rejected the tailored version twice; base resume used)")
        if r["resume_diff"]:
            st.code(r["resume_diff"], language="diff")
        else:
            st.caption("No changes from the base resume.")
        if r["resume_pdf"] and Path(r["resume_pdf"]).exists():
            st.download_button("Download tailored resume (PDF)", Path(r["resume_pdf"]).read_bytes(), file_name=Path(r["resume_pdf"]).name)

    st.divider()
    if j["status"] == S.FILLED:
        if settings.auto_submit:
            st.warning("auto_submit is ON in config.")
        ok = st.checkbox("I reviewed this application and I want it submitted", key=f"confirm-{job_id}")
        c1, c2, _ = st.columns([2, 1, 4])
        if c1.button("Approve and submit", type="primary", disabled=not ok):
            try:
                with st.spinner("Replaying the form and submitting (a browser window will open)..."):
                    res = decide.approve(db, job_id, settings, _Notifier(), SHOTS_DIR, headless=False)
                (st.success if res.status == S.SUBMITTED else st.error)(f"{res.status}: {res.reason or 'confirmation detected'}")
            except decide.DailyLimitReached as e:
                st.error(str(e))
            except DuplicateApplication as e:
                st.error(str(e))
        if c2.button("Skip"):
            decide.skip(db, job_id)
            st.rerun()
    else:
        st.info("Fix the problem on the application page yourself, or skip it.")
        if st.button("Skip this application"):
            decide.skip(db, job_id)
            st.rerun()


class _Notifier:
    def alert(self, kind, message, **payload):
        st.toast(message)


def page_applications(db: Database, settings):
    rows = D.applications_table(db, settings)
    st.caption("Submitted applications. Tick one for its email history. 'Ghost in' = days until it is marked GHOSTED if nobody replies.")
    picked = table(rows, ["id", "title", "company", "status", "submitted_at", "days_since_submit", "ghost_in_days", "last_event", "resume_flag"], key="apps-table", select=True)
    if not picked:
        return
    st.divider()
    st.subheader(f"{picked['title']} @ {picked['company']}  -  {picked['status']}")
    left, right = st.columns(2)
    with left:
        st.markdown("**Status history**")
        table(D.application_events(db, picked["id"]), ["at", "status", "snippet"])
        new = st.selectbox("Set status manually", D.APPLICATION_STATUSES, index=D.APPLICATION_STATUSES.index(picked["status"]) if picked["status"] in D.APPLICATION_STATUSES else 0)
        if st.button("Update status") and new != picked["status"]:
            D.set_application_status(db, picked["id"], new)
            st.rerun()
    with right:
        if picked["confirmation_shot"] and Path(picked["confirmation_shot"]).exists():
            st.markdown("**Confirmation screenshot**")
            st.image(picked["confirmation_shot"], width="stretch")


def page_inbox(db: Database, settings):
    rows = D.manual_review_rows(db)
    if not rows:
        st.success("No emails waiting. Everything was matched automatically (or ignored).")
        return
    apps = D.open_applications(db)
    labels = {"(do not attach)": None} | {f"#{a['id']} {a['title']} @ {a['company']} [{a['current_status']}]": a["id"] for a in apps}
    st.caption("Emails the agent could not match to one application, or whose meaning was unclear.")
    for r in rows:
        with st.expander(f"{r['subject'] or '(no subject)'}  -  {r['sender']}"):
            st.write(f"Why it is here: {r['reason']}")
            pick = st.selectbox("Belongs to application", list(labels), key=f"app-{r['id']}")
            status = st.selectbox("Status", D.APPLICATION_STATUSES, index=1, key=f"st-{r['id']}")
            c1, c2, _ = st.columns([2, 1, 4])
            if c1.button("Attach and resolve", key=f"attach-{r['id']}", disabled=labels[pick] is None):
                D.resolve_manual(db, r["id"], labels[pick], status)
                st.rerun()
            if c2.button("Dismiss", key=f"dismiss-{r['id']}"):
                D.resolve_manual(db, r["id"])
                st.rerun()


def page_bank(db: Database, settings):
    rows = D.bank_rows(db)
    st.caption("Answers reused on later forms when the question is similar (90%+). Human-approved answers are never overwritten by cleanup.")
    c1, c2 = st.columns([1, 5])
    if c1.button("Run cleanup"):
        rep = cleanup_answer_bank(db, settings.bank_min_sim)
        c2.success(f"merged {rep.merged} duplicate(s), flagged {rep.flagged} conflicting answer(s)")
    picked = table(rows, ["id", "canonical_question", "answer", "human_approved", "use_count", "needs_cleanup", "updated_at"], key="bank-table", select=True)
    if picked:
        new = st.text_area("Answer", picked["answer"], key=f"bank-{picked['id']}")
        a, b, _ = st.columns([2, 1, 4])
        if a.button("Save (marks human-approved)") and new.strip():
            D.update_bank_answer(db, picked["id"], new.strip())
            st.rerun()
        if b.button("Delete"):
            D.delete_bank_answer(db, picked["id"])
            st.rerun()


def page_health(db: Database, settings):
    st.markdown("**Safety settings**")
    a, b, c = st.columns(3)
    a.metric("Auto-submit", "ON" if settings.auto_submit else "off")
    b.metric("Daily submit cap", settings.daily_submit_cap)
    c.metric("Ghosted after", f"{settings.ghost_after_days} days")
    if settings.auto_submit:
        st.error("auto_submit is ON: applications are submitted without your review.")
    st.markdown("**Profile**")
    if PROFILE_PATH.exists():
        from jobagent.flows.f0_profile.loader import load_profile
        from jobagent.flows.f0_profile.sensitive import missing_sensitive
        p = load_profile(PROFILE_PATH)
        miss = missing_sensitive(p)
        st.write(f"{p.personal.name or '(no name)'} - {len(p.experience)} jobs, {len(p.projects)} projects, {len(p.skills.core)} core skills")
        (st.warning if miss else st.success)(f"Sensitive fields not set: {', '.join(miss)}" if miss else "All sensitive fields are set (they never go to the LLM).")
    else:
        st.warning(f"No profile at {PROFILE_PATH}. Run: python -m jobagent.cli build-profile your_resume.pdf")
    table(D.profile_versions(db), key="pv")
    st.markdown("**LLM usage**")
    table(D.llm_summary(db))
    st.markdown("**Recent status changes**")
    table(D.recent_history(db, 100), ["at", "job_id", "title", "company", "from_status", "to_status", "note"])
    st.caption(f"Database: {DB_PATH.resolve()} ({DB_PATH.stat().st_size // 1024 if DB_PATH.exists() else 0} KB)")


def main():
    db = Database(DB_PATH)
    settings = load_settings()
    st.sidebar.title("Job Pipeline")
    page = st.sidebar.radio("Go to", PAGES, key="page")
    n = len(D.attention_items(db))
    st.sidebar.caption(f"{n} item(s) need attention" if n else "All clear")
    st.sidebar.caption(f"DB: {DB_PATH}")
    st.title(page)
    {"Overview": page_overview, "Jobs": page_jobs, "Review": page_review, "Applications": page_applications,
     "Inbox": page_inbox, "Answer Bank": page_bank, "Health": page_health}[page](db, settings)


main()
