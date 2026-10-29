"""Module 3: SCR-01 .. SCR-05 (TC-026 .. TC-040).

The LLM is a scripted fake. Where a test needs real model judgement (e.g. TC-033 consistency of a live model)
we test the deterministic rule scorer instead and say so in the report.
"""
import json

import pytest

from conftest import insert_job
from jobagent.core import statuses as st
from jobagent.core.notify import MemoryChannel
from jobagent.core.schemas import JDExtract, ScoreResult
from jobagent.flows.f2_scoring.digest import manual_apply, send_digest, skip_job
from jobagent.flows.f2_scoring.extractor import extract_jd
from jobagent.flows.f2_scoring.run import run_scoring
from jobagent.flows.f2_scoring.scorer import bucket, score

GOOD_JD = ("GenAI Engineer - Mumbai. We are building LLM agents. You will use Python, LangGraph and LangChain to build "
           "retrieval pipelines and agentic workflows. Requirements: 1-3 years of experience, strong Python, RAG and LLM knowledge. "
           "Hybrid role in Mumbai. Nice to have: FastAPI.")
NO_SALARY_JD = GOOD_JD
SAP_JD = ("SAP Consultant - Pune. Implement SAP FICO modules for enterprise clients. Requirements: 5-8 years of experience in SAP, "
          "Oracle and Excel reporting. Client travel required. This is an onsite functional consulting role in Pune.")


def http_ok(text):
    return lambda url: (200, f"<html><body><p>{text}</p></body></html>")


def jd_reply(**kw):
    base = dict(title="GenAI Engineer", company="Acme AI Labs", must_have_skills=["Python", "LangGraph", "LangChain"],
                nice_to_have=["FastAPI"], exp_min=1, exp_max=3, salary_range=None, location="Mumbai",
                remote_type="hybrid", apply_type="unknown", role_category="genai_agent", red_flags=[])
    base.update(kw)
    return base


# ---------------- SCR-01 ----------------
def test_tc026_clear_jd_extracts_skills_experience_and_location(make_llm):
    llm = make_llm([jd_reply()])
    jd = extract_jd(GOOD_JD, "GenAI Engineer", "Acme AI Labs", "Mumbai", llm)
    assert set(jd.must_have_skills) == {"Python", "LangGraph", "LangChain"}
    assert (jd.exp_min, jd.exp_max) == (1, 3) and jd.location == "Mumbai"


def test_tc026_rule_extractor_matches_on_the_same_jd():
    jd = extract_jd(GOOD_JD, "GenAI Engineer", "Acme", "Mumbai", llm=None)
    assert {"python", "langgraph", "langchain", "rag", "llm"} <= set(jd.must_have_skills)
    assert (jd.exp_min, jd.exp_max) == (1, 3)
    assert jd.role_category == "genai_agent" and jd.remote_type == "hybrid"


def test_tc027_jd_without_salary_keeps_salary_null_even_if_llm_hallucinates(make_llm):
    llm = make_llm([jd_reply(salary_range="20-30 LPA")])
    jd = extract_jd(NO_SALARY_JD, "GenAI Engineer", "Acme", "Mumbai", llm)
    assert jd.salary_range is None
    assert extract_jd(NO_SALARY_JD, "t", "c", None, None).salary_range is None


def test_tc027_real_salary_in_jd_is_kept(make_llm):
    text = GOOD_JD + " Salary: 15-25 LPA."
    jd = extract_jd(text, "t", "c", None, make_llm([jd_reply(salary_range="15-25 LPA")]))
    assert jd.salary_range == "15-25 LPA"


def test_tc028_invalid_json_retries_once_then_extraction_failed(db, make_llm, profile, settings):
    jid = insert_job(db, snippet="s")
    llm = make_llm(["this is not json", "{still not json"])
    summary = run_scoring(db, profile, http_ok(GOOD_JD), llm, settings)
    assert len(llm.backend_obj.calls) == 2  # original + exactly 1 retry
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.EXTRACTION_FAILED
    assert summary.extraction_failed == 1


def test_tc028_second_attempt_can_succeed(make_llm):
    llm = make_llm(["garbage", jd_reply()])
    assert extract_jd(GOOD_JD, "t", "c", None, llm).must_have_skills
    assert len(llm.backend_obj.calls) == 2


def test_tc029_login_wall_falls_back_to_snippet_with_jd_partial_and_continues(db, profile, settings):
    jid = insert_job(db, snippet="GenAI Engineer | Acme AI Labs | Mumbai | Python LangGraph LangChain 1-3 years " * 3)
    wall = lambda url: (200, "<html><body>Sign in to view this job. Join now to see more.</body></html>")
    run_scoring(db, profile, wall, None, settings)
    hist = [r["to_status"] for r in db.query("SELECT to_status FROM job_history WHERE job_id=? ORDER BY id", (jid,))]
    assert hist[0] == st.JD_PARTIAL
    assert hist[-1] in (st.SCORED, st.MAYBE, st.REJECTED)  # it moved on instead of stalling
    assert "Python" in db.scalar("SELECT jd_raw FROM jobs WHERE id=?", (jid,))  # scored from the snippet


def test_tc029_http_403_also_gives_jd_partial(db, profile, settings):
    jid = insert_job(db, snippet="AI Engineer at Acme, Python, 1-3 years, Mumbai. " * 6)
    run_scoring(db, profile, lambda u: (403, "Forbidden"), None, settings)
    assert db.scalar("SELECT COUNT(*) FROM job_history WHERE job_id=? AND to_status='JD_PARTIAL'", (jid,)) == 1


# ---------------- SCR-02 ----------------
def test_tc030_perfect_match_jd_scores_80_or_more(db, profile, settings):
    jid = insert_job(db)
    run_scoring(db, profile, http_ok(GOOD_JD), None, settings)
    total = db.scalar("SELECT llm_score FROM job_scores WHERE job_id=?", (jid,))
    assert total >= 80
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.SCORED


def test_tc030_score_has_a_reason_of_at_most_two_lines(db, profile, settings):
    jid = insert_job(db)
    run_scoring(db, profile, http_ok(GOOD_JD), None, settings)
    reason = db.scalar("SELECT reason FROM job_scores WHERE job_id=?", (jid,))
    assert reason and len(reason.splitlines()) <= 2


def test_tc031_irrelevant_sap_jd_scores_below_50(db, profile, settings):
    jid = insert_job(db, title="SAP Consultant", company="Zeta")
    run_scoring(db, profile, http_ok(SAP_JD), None, settings)
    assert db.scalar("SELECT llm_score FROM job_scores WHERE job_id=?", (jid,)) < 50
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.REJECTED


def test_tc032_wrong_llm_total_is_recomputed_from_components(profile, make_llm, clock):
    llm = make_llm([dict(skills=30, seniority=10, salary=8, role_type=12, company=5, total=99, reason="great")])
    jd = JDExtract(title="GenAI Engineer", role_category="genai_agent")
    assert score(jd, "GenAI Engineer", profile, clock(), llm).total == 65


def test_tc032_out_of_range_component_is_rejected_and_retried(profile, make_llm, clock):
    llm = make_llm([dict(skills=90, seniority=10, salary=8, role_type=12, company=5, total=125),
                    dict(skills=35, seniority=10, salary=8, role_type=12, company=5)])
    jd = JDExtract(title="GenAI Engineer")
    assert score(jd, "GenAI Engineer", profile, clock(), llm).total == 70
    assert len(llm.backend_obj.calls) == 2


def test_tc033_same_jd_scored_twice_differs_by_less_than_5(profile, clock):
    jd = extract_jd(GOOD_JD, "GenAI Engineer", "Acme", "Mumbai", None)
    a, b = score(jd, "GenAI Engineer", profile, clock()), score(jd, "GenAI Engineer", profile, clock())
    assert abs(a.total - b.total) <= 5  # rule scorer is deterministic (0). A live LLM was not measured.


def test_tc034_ai_labelled_support_job_gets_low_role_type_even_if_llm_says_high(profile, make_llm, clock):
    llm = make_llm([dict(skills=20, seniority=10, salary=8, role_type=14, company=5)])
    jd = JDExtract(title="AI Customer Support Associate", role_category="genai_agent")
    sr = score(jd, "AI Customer Support Associate", profile, clock(), llm)
    assert sr.role_type <= 3
    assert sr.total == 20 + 10 + 8 + sr.role_type + 5


def test_missing_salary_is_neutral_8_even_if_llm_gives_other(profile, make_llm, clock):
    llm = make_llm([dict(skills=20, seniority=10, salary=15, role_type=10, company=5)])
    assert score(JDExtract(title="AI Engineer"), "AI Engineer", profile, clock(), llm).salary == 8


# ---------------- SCR-03 ----------------
def _components_for(total):
    table = {70: (30, 15, 8, 12, 5), 69: (29, 15, 8, 12, 5), 50: (20, 10, 8, 7, 5), 49: (19, 10, 8, 7, 5)}
    s, se, sa, r, c = table[total]
    return dict(skills=s, seniority=se, salary=sa, role_type=r, company=c, total=0, reason="x")


def _llm_by_title(make_llm):
    def reply(model, system, user):
        if "Fixed rubric" in system:
            title = json.loads(user)["jd"]["title"]
            return _components_for(int(title.removeprefix("Job")))
        return {}
    return make_llm(reply)


def test_tc035_scores_70_and_69_land_in_apply_and_maybe(db, profile, settings, make_llm):
    j70, j69 = insert_job(db, title="Job70"), insert_job(db, title="Job69")
    run_scoring(db, profile, http_ok(GOOD_JD), _llm_by_title(make_llm), settings)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (j70,)) == st.SCORED
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (j69,)) == st.MAYBE
    assert (bucket(70, settings), bucket(69, settings)) == (st.SCORED, st.MAYBE)


def test_tc036_scores_50_and_49_land_in_maybe_and_reject(db, profile, settings, make_llm):
    j50, j49 = insert_job(db, title="Job50"), insert_job(db, title="Job49")
    run_scoring(db, profile, http_ok(GOOD_JD), _llm_by_title(make_llm), settings)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (j50,)) == st.MAYBE
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (j49,)) == st.REJECTED


# ---------------- SCR-04 ----------------
def _scored_job(db, title, status, total, reason="Good skill overlap.\nSalary not stated."):
    jid = insert_job(db, title=title, status=status)
    db.write("INSERT INTO job_scores(job_id, llm_score, reason, scored_at) VALUES (?,?,?,?)", (jid, total, reason, db.now_iso()))
    return jid


def test_tc037_digest_with_10_scored_jobs_lists_apply_first_with_score_and_reason(db):
    for i in range(4):
        _scored_job(db, f"Apply{i}", st.SCORED, 90 - i)
    for i in range(6):
        _scored_job(db, f"Maybe{i}", st.MAYBE, 65 - i)
    ch = MemoryChannel()
    assert send_digest(db, ch) is True
    subject, body = ch.sent[0]
    assert "10 new matches" in subject
    assert body.index("APPLY") < body.index("MAYBE")
    assert body.index("Apply0") < body.index("Apply3") < body.index("Maybe0")
    assert "[90]" in body and "Good skill overlap." in body
    assert db.scalar("SELECT COUNT(*) FROM job_scores WHERE digested_at IS NULL") == 0


def test_tc038_no_new_scored_jobs_sends_no_new_matches_not_an_empty_digest(db):
    ch = MemoryChannel()
    assert send_digest(db, ch) is False
    assert ch.sent == [("Job digest: no new matches", "No new matches today.")]
    _scored_job(db, "A", st.SCORED, 90)
    send_digest(db, ch)
    assert send_digest(db, ch) is False  # already digested => nothing new again
    assert len(ch.sent) == 3 and "No new matches" in ch.sent[-1][1]


# ---------------- SCR-05 ----------------
def test_tc039_manual_apply_moves_a_rejected_job_forward(db):
    jid = _scored_job(db, "Rejected one", st.REJECTED, 30)
    manual_apply(db, jid)
    row = db.one("SELECT status, manual FROM jobs WHERE id=?", (jid,))
    assert (row["status"], row["manual"]) == (st.SCORED, 1)
    assert st.TAILORED in st.TRANSITIONS[row["status"]]  # can proceed to tailoring


def test_tc040_skipping_an_apply_job_sets_skipped_and_it_does_not_come_back(db, notifier):
    from helpers import FakeMail, linkedin_email
    from jobagent.flows.f0_profile.prefs import SearchPrefs
    from jobagent.flows.f1_discovery.run import run_discovery
    em = linkedin_email([("GenAI Engineer", "Acme", "Mumbai", 1, "https://www.linkedin.com/jobs/view/777")])
    run_discovery(db, FakeMail([em]), SearchPrefs(), notifier)
    jid = db.scalar("SELECT id FROM jobs")
    db.write("UPDATE jobs SET status='SCORED' WHERE id=?", (jid,))
    db.write("INSERT INTO job_scores(job_id, llm_score, reason) VALUES (?,90,'x')", (jid,))
    skip_job(db, jid)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.SKIPPED
    em2 = linkedin_email([("GenAI Engineer", "Acme", "Mumbai", 1, "https://www.linkedin.com/jobs/view/777?trk=again")], "li-again")
    run_discovery(db, FakeMail([em2]), SearchPrefs(), notifier)
    assert db.scalar("SELECT COUNT(*) FROM jobs") == 1 and db.scalar("SELECT status FROM jobs") == st.SKIPPED
    ch = MemoryChannel()
    send_digest(db, ch)
    assert "GenAI Engineer" not in ch.sent[0][1]
