"""Module 6: REV-01 .. REV-06 (TC-067 .. TC-080). Real headless Chromium on local forms; submit is replayed for real."""
import random
import re
from pathlib import Path

import pytest

import forms
from conftest import insert_job
from jobagent.core import statuses as st
from jobagent.flows.f4_formfill.answer_bank import AnswerBank
from jobagent.flows.f4_formfill.run import fill_application
from jobagent.flows.f5_review.decide import (
    AutoSubmitDisabled, DailyLimitReached, approve, edit_answer, maybe_auto_submit, skip, submitted_today,
)
from jobagent.flows.f5_review.review import build_review, render_review_html, save_review_html
from jobagent.flows.f5_review.submit import DuplicateApplication

PAYLOAD_JS = "window.__payload=document.getElementById('q1').value;" + forms.CONFIRM_JS


@pytest.fixture
def resume(tmp_path):
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 dummy")
    return str(p)


def drafts(text="Draft answer."):
    return lambda model, system, user: {"answer": text} if "Draft an answer" in system else {}


@pytest.fixture
def filled(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    """Fills a Greenhouse-style form (LLM drafts the custom question) and returns (job_id, helpers)."""
    def make(html=None, name="form.html", llm_text="Draft answer."):
        url = forms.write_form(tmp_path, html or forms.greenhouse_form(on_submit=PAYLOAD_JS), name)
        jid = insert_job(db, status=st.TAILORED, apply_url=url, title="GenAI Engineer", company="Acme")
        db.write("INSERT INTO applications(job_id, resume_diff) VALUES (?, ?)", (jid, "@@ -1 +1 @@\n-old bullet\n+new bullet"))
        res = fill_application(db, jid, profile, resume, settings, notifier, llm=make_llm(drafts(llm_text)), page=page, shots_dir=tmp_path / "shots")
        assert res.status == st.FILLED
        return jid
    return make


def do_approve(db, jid, settings, notifier, page, tmp_path, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("confirm_timeout", 1.5)
    return approve(db, jid, settings, notifier, tmp_path / "shots", page=page, **kw)


def submits(page):
    return page.evaluate("window.__submits || 0")


# ---------------- REV-01 ----------------
def test_tc067_review_screen_shows_screenshot_field_table_and_resume_diff(db, filled, tmp_path):
    jid = filled()
    db.write("INSERT INTO job_scores(job_id, llm_score, reason) VALUES (?,?,?)", (jid, 88, "Strong LangGraph match."))
    out = save_review_html(db, jid, tmp_path / "review.html")
    doc = out.read_text(encoding="utf-8")
    assert '<img class="shot"' in doc and ".png" in doc                      # screenshot
    assert 'id="answers"' in doc and "First Name" in doc and "Aarav" in doc and "aarav.mehta@example.com" in doc  # field table
    assert 'id="resume-diff"' in doc and 'class="diff add">+new bullet' in doc and 'class="diff del">-old bullet' in doc  # diff
    assert "Strong LangGraph match." in doc and "88" in doc
    shot = Path(build_review(db, jid)["screenshots"][0])
    assert shot.exists() and shot.stat().st_size > 1000


def test_tc068_needs_review_rows_are_highlighted_and_editable_others_are_not(db, filled):
    jid = filled()
    doc = render_review_html(build_review(db, jid))
    rows = re.findall(r'<tr class="(needs-review|ok)" data-id="\d+"><td>([^<]*)</td>', doc)
    flagged = {label for cls, label in rows if cls == "needs-review"}
    assert flagged == {"Why do you want to join us?", "Are you comfortable with hybrid work?"}  # LLM drafts only
    assert "First Name" not in flagged and "Email" not in flagged
    assert '<textarea name="answer-' in doc and "tr.needs-review{background:#fff3b0}" in doc


# ---------------- REV-02 ----------------
def test_tc069_approve_runs_the_submit_flow(db, filled, settings, notifier, page, tmp_path):
    jid = filled()
    res = do_approve(db, jid, settings, notifier, page, tmp_path)
    assert res.status == st.SUBMITTED and submits(page) == 1
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.SUBMITTED
    assert [r["to_status"] for r in db.query("SELECT to_status FROM job_history WHERE job_id=? ORDER BY id", (jid,))] == [st.FILLED, st.APPROVED, st.SUBMITTED]


def test_tc070_skip_sets_skipped_and_nothing_is_submitted(db, filled, page):
    jid = filled()
    skip(db, jid)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.SKIPPED
    assert submits(page) == 0 and db.scalar("SELECT submitted_at FROM applications WHERE job_id=?", (jid,)) is None


def test_tc071_edited_answer_is_what_gets_submitted_not_the_original(db, filled, settings, notifier, page, tmp_path):
    jid = filled(llm_text="Original LLM draft.")
    aid = db.scalar("SELECT id FROM form_answers WHERE job_id=? AND field_label LIKE 'Why do you%'", (jid,))
    edit_answer(db, jid, aid, "My own edited answer.")
    res = do_approve(db, jid, settings, notifier, page, tmp_path)
    assert res.status == st.SUBMITTED
    assert page.evaluate("window.__payload") == "My own edited answer."


# ---------------- REV-03 ----------------
def test_tc072_edited_answer_is_saved_to_the_bank_with_human_approved(db, filled):
    jid = filled(llm_text="Original LLM draft.")
    aid = db.scalar("SELECT id FROM form_answers WHERE job_id=? AND field_label LIKE 'Why do you%'", (jid,))
    edit_answer(db, jid, aid, "My own edited answer.")
    row = db.one("SELECT * FROM answer_bank")
    assert row["answer"] == "My own edited answer." and row["human_approved"] == 1
    assert row["canonical_question"] == "Why do you want to join us?"
    fa = db.one("SELECT * FROM form_answers WHERE id=?", (aid,))
    assert (fa["source"], fa["needs_review"], fa["approved"]) == ("human", 0, 1)


def test_tc073_next_form_with_a_similar_question_gets_the_edited_answer(db, filled, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = filled(llm_text="Original LLM draft.")
    aid = db.scalar("SELECT id FROM form_answers WHERE job_id=? AND field_label LIKE 'Why do you%'", (jid,))
    edit_answer(db, jid, aid, "My own edited answer.")
    url2 = forms.write_form(tmp_path, forms.greenhouse_form(question="Why do you want to join?", with_dropdown=False), "form2.html")
    jid2 = insert_job(db, status=st.TAILORED, apply_url=url2)
    llm = make_llm(drafts("SHOULD NOT BE USED"))
    fill_application(db, jid2, profile, resume, settings, notifier, llm=llm, page=page, shots_dir=tmp_path / "shots2")
    assert page.input_value("#q1") == "My own edited answer." and llm.backend_obj.calls == []
    row = db.one("SELECT * FROM form_answers WHERE job_id=? AND field_label LIKE 'Why do you%'", (jid2,))
    assert row["source"] == "bank" and row["needs_review"] == 0


def test_editing_a_profile_sourced_field_does_not_pollute_the_bank(db, filled):
    jid = filled()
    aid = db.scalar("SELECT id FROM form_answers WHERE job_id=? AND field_label='First Name'", (jid,))
    edit_answer(db, jid, aid, "Aarav K")
    assert db.scalar("SELECT COUNT(*) FROM answer_bank") == 0


# ---------------- REV-04 ----------------
def test_tc074_sixteenth_application_is_blocked_with_a_limit_reached_message(db, filled, settings, notifier, page, tmp_path):
    jid = filled()
    for i in range(15):
        j = insert_job(db, status=st.SUBMITTED)
        db.write("INSERT INTO applications(job_id, submitted_at) VALUES (?,?)", (j, db.now_iso()))
    assert submitted_today(db) == 15
    with pytest.raises(DailyLimitReached, match="(?i)limit reached"):
        do_approve(db, jid, settings, notifier, page, tmp_path)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.FILLED  # untouched
    assert submits(page) == 0


def test_tc074_cap_is_configurable(db, filled, settings, notifier, page, tmp_path):
    settings.daily_submit_cap = 0
    jid = filled()
    with pytest.raises(DailyLimitReached):
        do_approve(db, jid, settings, notifier, page, tmp_path)


def test_tc075_two_consecutive_submits_are_45_to_120_seconds_apart(db, filled, settings, notifier, page, tmp_path, clock):
    waited = []

    def fake_sleep(s):
        waited.append(s)
        clock.advance(seconds=s)
    j1 = filled()
    do_approve(db, j1, settings, notifier, page, tmp_path, sleep=fake_sleep, rng=random.Random(7))
    j2 = filled(name="form2.html")
    do_approve(db, j2, settings, notifier, page, tmp_path, sleep=fake_sleep, rng=random.Random(7))
    t1, t2 = (db.scalar("SELECT submitted_at FROM applications WHERE job_id=?", (j,)) for j in (j1, j2))
    from datetime import datetime
    gap = (datetime.fromisoformat(t2) - datetime.fromisoformat(t1)).total_seconds()
    assert len(waited) == 1 and 45 <= gap <= 120
    assert settings.between_submits_sec == (45, 120)


# ---------------- REV-05 ----------------
def test_tc076_successful_submit_saves_confirmation_screenshot_and_timestamp(db, filled, settings, notifier, page, tmp_path, clock):
    jid = filled()
    res = do_approve(db, jid, settings, notifier, page, tmp_path)
    app = db.one("SELECT * FROM applications WHERE job_id=?", (jid,))
    assert app["submitted_at"] == clock().isoformat(timespec="seconds")
    assert app["confirmation_shot"] == res.confirmation_shot and Path(app["confirmation_shot"]).stat().st_size > 1000
    assert app["current_status"] == "SUBMITTED"
    assert (tmp_path / "shots" / f"job{jid}_presubmit.png").exists()


def no_confirmation_form():
    return forms.greenhouse_form(on_submit="")  # form accepts the click but never shows a confirmation


def test_tc077_no_confirmation_page_gives_submit_uncertain_and_no_retry(db, filled, settings, notifier, page, tmp_path):
    jid = filled(html=no_confirmation_form())
    res = do_approve(db, jid, settings, notifier, page, tmp_path)
    assert res.status == st.SUBMIT_UNCERTAIN
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.SUBMIT_UNCERTAIN
    assert submits(page) == 1                                  # clicked exactly once
    assert "submit_uncertain" in notifier.kinds()
    with pytest.raises(DuplicateApplication, match="uncertain"):
        do_approve(db, jid, settings, notifier, page, tmp_path)  # a second attempt is refused
    assert submits(page) == 1


# ---------------- REV-06 ----------------
def test_tc078_second_submit_on_the_same_job_is_blocked(db, filled, settings, notifier, page, tmp_path):
    jid = filled()
    assert do_approve(db, jid, settings, notifier, page, tmp_path).status == st.SUBMITTED
    with pytest.raises(DuplicateApplication, match="already submitted"):
        do_approve(db, jid, settings, notifier, page, tmp_path)
    assert submits(page) == 1


def test_tc079_submit_uncertain_job_is_never_auto_submitted(db, filled, settings, notifier, page, tmp_path):
    jid = filled(html=no_confirmation_form())
    do_approve(db, jid, settings, notifier, page, tmp_path)
    settings.auto_submit = True                                # even with auto-submit ON
    with pytest.raises(DuplicateApplication):
        maybe_auto_submit(db, jid, settings, notifier, tmp_path / "shots", page=page, sleep=lambda s: None)
    assert submits(page) == 1


def test_tc080_page_structure_changed_since_review_aborts_to_needs_human_without_submitting(db, filled, settings, notifier, page, tmp_path):
    jid = filled()
    url = db.scalar("SELECT apply_url FROM jobs WHERE id=?", (jid,))
    f = Path(tmp_path / "form.html")
    f.write_text(f.read_text(encoding="utf-8").replace("First Name", "Given name (legal)"), encoding="utf-8")  # employer changed the form
    res = do_approve(db, jid, settings, notifier, page, tmp_path)
    assert res.status == st.NEEDS_HUMAN and "form changed" in res.reason
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.NEEDS_HUMAN
    assert submits(page) == 0 and db.scalar("SELECT submitted_at FROM applications WHERE job_id=?", (jid,)) is None
    assert "needs_human" in notifier.kinds()


def test_tc080_new_required_field_appearing_also_aborts(db, filled, settings, notifier, page, tmp_path):
    jid = filled()
    f = Path(tmp_path / "form.html")
    f.write_text(f.read_text(encoding="utf-8").replace('<button type="submit"', forms.field("Favourite colour", "fc") + '<button type="submit"'), encoding="utf-8")
    assert do_approve(db, jid, settings, notifier, page, tmp_path).status == st.NEEDS_HUMAN and submits(page) == 0


# ---------------- SAF-01 (needs the submit flow) ----------------
def test_tc103_auto_submit_off_by_default_blocks_unreviewed_submit_and_on_allows_it(db, filled, settings, notifier, page, tmp_path):
    jid = filled()
    assert settings.auto_submit is False
    with pytest.raises(AutoSubmitDisabled):
        maybe_auto_submit(db, jid, settings, notifier, tmp_path / "shots", page=page, sleep=lambda s: None)
    assert submits(page) == 0 and db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.FILLED
    settings.auto_submit = True                               # only an explicit config change enables it
    res = maybe_auto_submit(db, jid, settings, notifier, tmp_path / "shots", page=page, sleep=lambda s: None, confirm_timeout=1.5)
    assert res.status == st.SUBMITTED and submits(page) == 1
