"""Module 10: PLT-01 .. PLT-04 (TC-112 .. TC-115)."""
import itertools
import logging
import shutil

import pytest

import forms
from conftest import insert_job
from helpers import FakeMail, linkedin_email, naukri_email, load_eml
from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.db import Database
from jobagent.core.llm import RateLimitError
from jobagent.core.notify import MemoryChannel
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f0_profile.versioning import record_version
from jobagent.flows.f1_discovery.run import run_discovery
from jobagent.flows.f2_scoring.digest import send_digest
from jobagent.flows.f2_scoring.run import run_scoring
from jobagent.flows.f3_resume.run import run_tailoring
from jobagent.flows.f4_formfill.run import fill_application
from jobagent.flows.f5_review.decide import approve
from jobagent.flows.f6_status.run import run_status_check
from jobagent.flows.f7_feedback.cleanup import cleanup_answer_bank

TABLES = ["jobs", "job_history", "job_scores", "applications", "form_answers", "answer_bank", "status_events",
          "llm_calls", "processed_emails", "manual_review", "profile_versions"]
GOOD_JD = ("GenAI Engineer - Mumbai. Build LLM agents with Python, LangGraph and LangChain for retrieval pipelines. "
           "Requirements: 1-3 years of experience, strong Python, RAG and LLM knowledge. Hybrid role in Mumbai. Nice to have: FastAPI.")


def counts(db):
    return {t: db.scalar(f"SELECT COUNT(*) FROM {t}") for t in TABLES}


def http_ok(url):
    return 200, f"<html><body><p>{GOOD_JD}</p></body></html>"


# ---------------- PLT-01 ----------------
def test_tc112_running_any_step_twice_creates_no_duplicate_data(db, profile, settings, notifier, page, tmp_path, make_llm, clock):
    emails = [load_eml("linkedin_1.eml"), load_eml("naukri_1.eml")]
    ch = MemoryChannel()
    llm = make_llm(lambda m, s, u: {"answer": "Yes"})
    steps = {
        "discovery": lambda: run_discovery(db, FakeMail(emails), SearchPrefs(), notifier),
        "scoring": lambda: run_scoring(db, profile, http_ok, None, settings),
        "digest": lambda: send_digest(db, ch),
        "profile_version": lambda: record_version(db, profile),
        "bank_cleanup": lambda: cleanup_answer_bank(db),
        "status_check": lambda: run_status_check(db, FakeMail([]), notifier, settings),
    }
    for name, step in steps.items():
        step()
        first = counts(db)
        step()
        assert counts(db) == first, f"step '{name}' changed data on its second run"
    # tailoring / fill / submit on one real job
    jid = db.scalar("SELECT id FROM jobs ORDER BY id LIMIT 1")
    db.write("UPDATE jobs SET manual=1, status='SCORED' WHERE id=?", (jid,))
    db.write("UPDATE jobs SET apply_url=? WHERE id=?", (forms.write_form(tmp_path, forms.greenhouse_form()), jid))
    for name, step in {
        "tailoring": lambda: run_tailoring(db, profile, None, tmp_path / "pdf", settings),
        "fill": lambda: fill_application(db, jid, profile, str(tmp_path / "pdf" / f"job_{jid}.pdf"), settings, notifier, llm=llm, page=page, shots_dir=tmp_path / "s"),
    }.items():
        step()
        first = counts(db)
        step()
        assert counts(db) == first, f"step '{name}' changed data on its second run"
    approve(db, jid, settings, notifier, tmp_path / "s", page=page, sleep=lambda s: None, confirm_timeout=1.5)
    first = counts(db)
    with pytest.raises(Exception):
        approve(db, jid, settings, notifier, tmp_path / "s", page=page, sleep=lambda s: None, confirm_timeout=1.5)
    assert counts(db) == first


# ---------------- PLT-02 ----------------
def test_tc113_dry_run_executes_the_flow_but_writes_nothing_and_logs_instead(tmp_path, profile, settings, notifier, clock, caplog):
    path = tmp_path / "agent.db"
    seed = Database(path, clock=clock)
    insert_job(seed, status="DISCOVERED", snippet="GenAI Engineer Acme Python LangGraph 1-3 years " * 8)
    seed.close()
    before_db = Database(path, clock=clock)
    before = counts(before_db)
    before_db.close()

    dry = Database(path, dry_run=True, clock=clock)
    with caplog.at_level(logging.INFO, logger="jobagent"):
        disc = run_discovery(dry, FakeMail([load_eml("linkedin_1.eml")]), SearchPrefs(), notifier)
        scored = run_scoring(dry, profile, lambda u: (403, "blocked"), None, settings)
        send_digest(dry, MemoryChannel())
    assert disc.inserted == 3 and scored.processed == 1               # the flows really ran ("would insert 3", "would score 1")
    assert dry.skipped_writes, "dry run recorded no intended writes"
    assert "[dry-run] would execute" in caplog.text                    # and printed what they would have done
    dry.close()

    after_db = Database(path, clock=clock)
    assert counts(after_db) == before                                  # zero writes reached the database
    assert after_db.scalar("SELECT status FROM jobs") == "DISCOVERED"
    after_db.close()


# ---------------- PLT-03 ----------------
def test_tc114_llm_429_is_retried_with_exponential_backoff(db, make_llm):
    sleeps = []
    llm = make_llm([RateLimitError("429 too many requests"), RateLimitError("429"), {"must_have_skills": ["Python"]}])
    llm.sleep = sleeps.append
    from jobagent.core.schemas import JDExtract
    out = llm.call("small", "s", "u", JDExtract, flow="extract")
    assert out.must_have_skills == ["Python"]
    assert sleeps == [1.0, 2.0]                                        # 1s, then 2s: exponential
    assert len(llm.backend_obj.calls) == 3
    oks = [r["ok"] for r in db.query("SELECT ok FROM llm_calls ORDER BY id")]
    assert oks == [0, 0, 1]


def test_tc114_persistent_429_gives_up_after_3_retries_with_doubling_delays(db, make_llm):
    sleeps = []
    llm = make_llm([RateLimitError("429")])
    llm.sleep = sleeps.append
    from jobagent.core.schemas import JDExtract
    with pytest.raises(RateLimitError):
        llm.call("small", "s", "u", JDExtract, flow="extract")
    assert sleeps == [1.0, 2.0, 4.0] and len(llm.backend_obj.calls) == 4


def test_tc114_a_job_whose_llm_keeps_429ing_gets_attempts_incremented_not_lost(db, profile, settings, make_llm):
    jid = insert_job(db, snippet="s")
    llm = make_llm([RateLimitError("429")])
    run_scoring(db, profile, http_ok, llm, settings)
    row = db.one("SELECT status, attempts, last_error FROM jobs WHERE id=?", (jid,))
    assert row["attempts"] == 1 and row["status"] in (st.DISCOVERED, st.JD_PARTIAL) and "429" in row["last_error"]


def test_tc114_source_429_when_fetching_a_jd_is_backed_off_too(db, profile, settings):
    jid = insert_job(db, snippet="s")
    replies = iter([(429, ""), (429, ""), (200, f"<p>{GOOD_JD}</p>")])
    sleeps = []
    run_scoring(db, profile, lambda url: next(replies), None, settings, sleep=sleeps.append)
    assert sleeps == [1.0, 2.0]
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) in (st.SCORED, st.MAYBE)


# ---------------- PLT-04 ----------------
def test_tc115_discovered_straight_to_submitted_raises_and_leaves_status_unchanged(db):
    jid = insert_job(db, status=st.DISCOVERED)
    history_before = db.scalar("SELECT COUNT(*) FROM job_history")
    with pytest.raises(st.InvalidTransition, match="DISCOVERED -> SUBMITTED"):
        queue.advance(db, jid, st.SUBMITTED)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.DISCOVERED
    assert db.scalar("SELECT COUNT(*) FROM job_history") == history_before


def test_tc115_every_pair_of_statuses_behaves_exactly_as_the_table_says():
    all_status = list(st.TRANSITIONS)
    for a, b in itertools.product(all_status, all_status):
        if b in st.TRANSITIONS[a]:
            st.check_transition(a, b)
        else:
            with pytest.raises(st.InvalidTransition):
                st.check_transition(a, b)
    assert st.TRANSITIONS[st.SUBMITTED] == set() and st.TRANSITIONS[st.SKIPPED] == set()   # terminal states are terminal


def test_tc115_unknown_status_is_rejected():
    with pytest.raises(st.InvalidTransition):
        st.check_transition("MADE_UP", st.SCORED)
