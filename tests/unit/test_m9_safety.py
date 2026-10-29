"""Module 9: SAF-01 .. SAF-05 (TC-102, TC-104, TC-105, TC-107 .. TC-111). TC-103 is in test_m6_review.py, TC-106 in test_m4_resume.py."""
import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest

import forms
from conftest import insert_job, make_profile
from helpers import FakeMail, naukri_email
from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.config import Settings, load_settings
from jobagent.core.llm import LLMClient, LLMResponse, SensitiveLeak
from jobagent.core.logging import RedactingFilter, redact, register_secret, setup_logging
from jobagent.core.schemas import JDExtract
from jobagent.flows.f0_profile.loader import load_profile, save_profile
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f0_profile.sensitive import register_profile_secrets, sensitive_values
from jobagent.flows.f1_discovery.run import run_discovery
from jobagent.flows.f2_scoring.run import run_scoring
from jobagent.flows.f3_resume.run import run_tailoring
from jobagent.flows.f4_formfill.run import fill_application
from jobagent.flows.f5_review.decide import approve

# Values chosen so they cannot appear in a prompt by coincidence.
SENTINEL = dict(current_ctc=7391.5, expected_ctc=8642.25, notice_period_days=777, relocation=True, work_auth="SENTINEL-VISA-XYZ")

GOOD_JD = ("GenAI Engineer - Mumbai. Build LLM agents with Python, LangGraph and LangChain for retrieval pipelines. "
           "Requirements: 1-3 years of experience, strong Python, RAG and LLM knowledge. Hybrid role in Mumbai. Nice to have: FastAPI.")


def http_ok(text=GOOD_JD):
    return lambda url: (200, f"<html><body><p>{text}</p></body></html>")


# ---------------- SAF-01 ----------------
def test_tc102_fresh_install_has_auto_submit_false(tmp_path):
    assert Settings().auto_submit is False                               # code default
    assert load_settings().auto_submit is False                          # shipped config/settings.yaml
    assert load_settings(tmp_path / "does_not_exist.yaml").auto_submit is False   # no config file at all
    assert "auto_submit: false" in (Path(__file__).resolve().parents[2] / "config" / "settings.yaml").read_text(encoding="utf-8")


def test_tc102_only_an_explicit_config_value_turns_it_on(tmp_path):
    cfg = tmp_path / "s.yaml"
    cfg.write_text("auto_submit: true\n", encoding="utf-8")
    assert load_settings(cfg).auto_submit is True
    cfg.write_text("limits: {daily_submit_cap: 5}\n", encoding="utf-8")
    s = load_settings(cfg)
    assert s.auto_submit is False and s.daily_submit_cap == 5


# ---------------- SAF-02 ----------------
def test_tc104_no_sensitive_value_appears_in_any_logged_llm_prompt(db, make_llm, settings, notifier, page, tmp_path):
    profile = make_profile(**SENTINEL)

    def llm_reply(model, system, user):
        if "Extract structured details" in system:
            return dict(must_have_skills=["Python", "LangGraph"], exp_min=1, exp_max=3, role_category="genai_agent")
        if "Score how well" in system:
            return dict(skills=35, seniority=18, salary=8, role_type=14, company=5, reason="Good fit.")
        if "Tailor the candidate" in system:
            from jobagent.flows.f3_resume.tailor import base_draft
            return base_draft(profile).model_dump()
        if "Draft an answer" in system:
            return {"answer": "I enjoy building agents."}
        return {}
    llm = make_llm(llm_reply)
    # score -> tailor -> fill, all with LLM calls, on a profile whose sensitive section is fully populated
    jid = insert_job(db, snippet="s", apply_url=forms.write_form(tmp_path, forms.page(
        forms.field("Email", "em", typ="email") + forms.field("Expected CTC (LPA)", "ec", typ="number") +
        forms.field("Notice period (days)", "np", typ="number") + forms.field("Work authorization", "wa") +
        forms.field("Why do you want to join us?", "q", kind="textarea", required=False) + forms.SUBMIT)))
    run_scoring(db, profile, http_ok(), llm, settings)
    db.write("UPDATE jobs SET manual=1 WHERE id=?", (jid,))
    db.write("UPDATE jobs SET status='SCORED' WHERE id=? AND status<>'SCORED'", (jid,))
    run_tailoring(db, profile, llm, tmp_path / "pdf", settings)
    resume = db.scalar("SELECT resume_path FROM applications WHERE job_id=?", (jid,))
    fill_application(db, jid, profile, resume, settings, notifier, llm=llm, page=page, shots_dir=tmp_path / "s")
    prompts = [r["prompt"] for r in db.query("SELECT prompt FROM llm_calls")]
    assert len(prompts) >= 4                                              # extract + score + tailor + form answer
    flows = {r["flow"] for r in db.query("SELECT flow FROM llm_calls")}
    assert {"extract", "score", "tailor", "form_answer"} <= flows
    blob = "\n".join(prompts)
    for secret in ("7391.5", "8642.25", "777", "SENTINEL-VISA-XYZ"):
        assert secret not in blob, f"{secret} leaked into an LLM prompt"
    for key in ("current_ctc", "expected_ctc", "notice_period_days", "work_auth", '"sensitive"'):
        assert key not in blob


def test_llm_client_refuses_a_prompt_containing_a_sensitive_value(db):
    profile = make_profile(**SENTINEL)
    client = LLMClient(lambda m, s, u: LLMResponse("{}"), db=db, forbidden=[str(v) for v in sensitive_values(profile)])
    with pytest.raises(SensitiveLeak):
        client.call("small", "sys", "my work auth is SENTINEL-VISA-XYZ", JDExtract, flow="x")
    assert client.call("small", "sys", "harmless", JDExtract, flow="x") is not None


def test_tc105_notice_period_and_expected_ctc_come_only_from_profile_json(db, settings, notifier, page, tmp_path, make_llm):
    path = tmp_path / "profile.json"
    save_profile(make_profile(**SENTINEL), path)
    profile = load_profile(path)                                          # values come from the file, not from memory
    url = forms.write_form(tmp_path, forms.SENSITIVE_FORM)
    jid = insert_job(db, status=st.TAILORED, apply_url=url)
    llm = make_llm(lambda m, s, u: {"answer": "999"})                      # if the LLM were ever asked, it would say 999
    res = fill_application(db, jid, profile, None, settings, notifier, llm=llm, page=page, shots_dir=tmp_path / "s")
    assert res.status == st.FILLED and llm.backend_obj.calls == []
    assert page.input_value("#np") == "777" and page.input_value("#ec") == "8642.25" and page.input_value("#cc") == "7391.5"
    assert page.input_value("#wa") == "SENTINEL-VISA-XYZ" and page.input_value("#rl") == "Yes"
    for row in db.query("SELECT * FROM form_answers WHERE job_id=? AND field_label IN ('Notice period (days)','Expected CTC (LPA)','Current CTC (LPA)')", (jid,)):
        assert row["source"] == "profile" and row["confidence"] == 1.0


# ---------------- SAF-04 ----------------
def poisoned(make_llm):
    """An LLM that crashes (not just returns bad JSON) on the one JD that contains CRASHME."""
    def reply(model, system, user):
        if "CRASHME" in user:
            raise RuntimeError("provider exploded")
        if "Score how well" in system:
            return dict(skills=35, seniority=18, salary=8, role_type=14, company=5, reason="ok")
        return dict(must_have_skills=["Python"], exp_min=1, exp_max=3, role_category="genai_agent")
    return make_llm(reply)


def poisoned_http(url):
    return 200, f"<p>{GOOD_JD}{' CRASHME' if 'bad.test' in url else ''}</p>"


def test_tc107_a_job_failing_three_times_becomes_failed_and_others_keep_going(db, profile, settings, clock, make_llm):
    bad = insert_job(db, title="Bad", apply_url="https://bad.test/1", snippet="s")
    good = insert_job(db, title="Good", apply_url="https://good.test/1", snippet="s")
    llm, http = poisoned(make_llm), poisoned_http
    for attempt in (1, 2, 3):
        run_scoring(db, profile, http, llm, settings)
        clock.advance(seconds=settings.lease_min * 60 + 1)                  # next scheduled run
        if attempt < 3:
            assert db.scalar("SELECT status FROM jobs WHERE id=?", (bad,)) in (st.DISCOVERED, st.JD_PARTIAL)
    row = db.one("SELECT status, attempts, last_error FROM jobs WHERE id=?", (bad,))
    assert row["status"] == st.FAILED and row["attempts"] == 3
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (good,)) in (st.SCORED, st.MAYBE)   # processed normally on run 1


def test_tc107_a_failing_job_does_not_block_the_batch_within_one_run(db, profile, settings, make_llm):
    bad = insert_job(db, title="Bad", apply_url="https://bad.test/1", snippet="s")
    goods = [insert_job(db, title=f"Good{i}", apply_url=f"https://good.test/{i}", snippet="s") for i in range(3)]
    summary = run_scoring(db, profile, poisoned_http, poisoned(make_llm), settings)
    assert summary.failed == 1 and summary.processed == 3
    assert all(db.scalar("SELECT status FROM jobs WHERE id=?", (g,)) in (st.SCORED, st.MAYBE) for g in goods)
    assert db.scalar("SELECT attempts FROM jobs WHERE id=?", (bad,)) == 1       # one failure per run, retried on the next run


def test_tc108_job_locked_by_a_crashed_worker_is_picked_up_again_after_the_lease(db, settings, clock):
    jid = insert_job(db)
    first = queue.claim(db, st.DISCOVERED, "worker-1", settings.lease_min)
    assert first["id"] == jid and first["locked_by"] == "worker-1"
    # worker-1 crashes here: it never calls advance()/fail()
    assert queue.claim(db, st.DISCOVERED, "worker-2", settings.lease_min) is None           # still leased
    clock.advance(seconds=settings.lease_min * 60 - 1)
    assert queue.claim(db, st.DISCOVERED, "worker-2", settings.lease_min) is None           # lease not yet expired
    clock.advance(seconds=2)
    again = queue.claim(db, st.DISCOVERED, "worker-2", settings.lease_min)
    assert again is not None and again["id"] == jid and again["locked_by"] == "worker-2"    # reclaimed


# ---------------- SAF-05 ----------------
def test_tc109_every_llm_call_logs_tokens_cost_and_latency(db, make_llm):
    llm = make_llm([dict(must_have_skills=["Python"])], models={"small": "llama-3.1-8b-instant", "large": "llama-3.3-70b-versatile"})
    llm.call("small", "sys", "user text", JDExtract, flow="extract", job_id=5)
    llm.call("large", "sys", "user text", JDExtract, flow="tailor", job_id=5)
    rows = db.query("SELECT * FROM llm_calls ORDER BY id")
    assert [r["flow"] for r in rows] == ["extract", "tailor"] and all(r["job_id"] == 5 and r["ok"] == 1 for r in rows)
    for r in rows:
        assert r["prompt_tokens"] == 100 and r["completion_tokens"] == 50
        assert r["cost_usd"] > 0 and r["latency_ms"] is not None and r["latency_ms"] >= 0 and r["model"]
    assert rows[1]["cost_usd"] > rows[0]["cost_usd"]                       # large model costs more


def test_tc109_failed_calls_are_logged_too(db, make_llm):
    llm = make_llm([RuntimeError("provider down")])
    with pytest.raises(RuntimeError):
        llm.call("small", "s", "u", JDExtract, flow="extract")
    r = db.one("SELECT ok, error FROM llm_calls")
    assert r["ok"] == 0 and "provider down" in r["error"]


def test_tc110_full_status_history_of_a_job_is_traceable_end_to_end(db, profile, settings, notifier, page, tmp_path, make_llm):
    em = naukri_email([("GenAI Engineer", "Acme AI Labs", "Mumbai", 1, "1-3 Yrs", "genai-engineer-acme-1")])
    run_discovery(db, FakeMail([em]), SearchPrefs(), notifier)
    jid = db.scalar("SELECT id FROM jobs")
    db.write("UPDATE jobs SET apply_url=? WHERE id=?", (forms.write_form(tmp_path, forms.greenhouse_form()), jid))
    run_scoring(db, profile, http_ok(), None, settings)
    run_tailoring(db, profile, None, tmp_path / "pdf", settings)
    llm = make_llm(lambda m, s, u: {"answer": "Yes"})
    resume = db.scalar("SELECT resume_path FROM applications WHERE job_id=?", (jid,))
    fill_application(db, jid, profile, resume, settings, notifier, llm=llm, page=page, shots_dir=tmp_path / "s")
    approve(db, jid, settings, notifier, tmp_path / "s", page=page, sleep=lambda s: None, confirm_timeout=1.5)
    hist = db.query("SELECT from_status, to_status, note, at FROM job_history WHERE job_id=? ORDER BY id", (jid,))
    assert [h["to_status"] for h in hist] == ["DISCOVERED", "EXTRACTED", "SCORED", "TAILORED", "FILLED", "APPROVED", "SUBMITTED"]
    assert [h["from_status"] for h in hist][1:] == ["DISCOVERED", "EXTRACTED", "SCORED", "TAILORED", "FILLED", "APPROVED"]
    assert all(h["at"] for h in hist) and hist[0]["note"] == "from naukri_alert"
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.SUBMITTED


def test_tc111_logs_never_contain_passwords_tokens_or_ctc_in_plain_text(tmp_path, db, settings, notifier, page, make_llm):
    logfile = tmp_path / "agent.log"
    root = logging.getLogger("jobagent")
    old_handlers, old_level = list(root.handlers), root.level
    setup_logging(str(logfile), logging.DEBUG)
    try:
        profile = make_profile(**SENTINEL)
        register_profile_secrets(profile)
        log = logging.getLogger("jobagent.test")
        # things a careless developer might log
        log.info("login with password=hunter2 for user bob")
        log.info("calling API Authorization: Bearer abc123.def456.ghi789")
        log.warning("refresh_token: 1//0gSECRETREFRESH and api_key=gsk_abcdefghijklmnop123456")
        log.info("candidate Current CTC: 7391.5 LPA, expected_ctc=8642.25, notice 777 days, visa SENTINEL-VISA-XYZ")
        # and a real run that touches sensitive data
        jid = insert_job(db, status=st.TAILORED, apply_url=forms.write_form(tmp_path, forms.SENSITIVE_FORM))
        fill_application(db, jid, profile, None, settings, notifier, page=page, shots_dir=tmp_path / "s")
        for h in root.handlers:
            h.flush()
        text = logfile.read_text(encoding="utf-8")
    finally:
        for h in list(root.handlers):
            if h not in old_handlers:
                h.close()
                root.removeHandler(h)
        root.setLevel(old_level)
    assert text.strip(), "nothing was logged"
    for secret in ("hunter2", "abc123.def456.ghi789", "SECRETREFRESH", "gsk_abcdefghijklmnop123456", "7391.5", "8642.25", "SENTINEL-VISA-XYZ"):
        assert secret not in text, f"{secret!r} found in the log file"
    assert "***" in text or "[REDACTED]" in text


@pytest.mark.parametrize("raw,must_not_contain", [
    ("password=hunter2", "hunter2"), ("Authorization: Bearer abc.def-123", "abc.def-123"), ("api_key=sk-12345678901234567890", "12345678901234567890"),
    ("Current CTC: 18 LPA", "18"), ("expected_ctc=2345.5", "2345.5"), ("token: eyJhbGciOi", "eyJhbGciOi"),
])
def test_redact_masks_secrets(raw, must_not_contain):
    assert must_not_contain not in redact(raw)


def test_redact_leaves_normal_text_alone():
    msg = "job 12: DISCOVERED -> SCORED score 85"
    assert redact(msg) == msg
