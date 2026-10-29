"""Module 5: FRM-01 .. FRM-07 (TC-052 .. TC-066). Real headless Chromium on local dummy forms; LLM is a scripted fake."""
import pytest
from playwright.sync_api import sync_playwright

import forms
from conftest import insert_job, make_profile
from jobagent.core import statuses as st
from jobagent.core.schemas import FieldSpec
from jobagent.flows.f4_formfill.answer_bank import AnswerBank
from jobagent.flows.f4_formfill.guards import SubmitBlocked, safe_click
from jobagent.flows.f4_formfill.mapper import map_field
from jobagent.flows.f4_formfill.resolver import choose_option, truncate_words
from jobagent.flows.f4_formfill.run import fill_application


@pytest.fixture
def resume(tmp_path):
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 dummy")
    return str(p)


def start(db, tmp_path, html, status=st.TAILORED, name="form.html"):
    url = forms.write_form(tmp_path, html, name)
    return insert_job(db, status=status, apply_url=url, title="GenAI Engineer", company="Acme")


def run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, **kw):
    return fill_application(db, jid, profile, resume, settings, notifier, page=page, shots_dir=tmp_path / "shots", **kw)


def answers(db, jid):
    return {r["field_label"]: r for r in db.query("SELECT * FROM form_answers WHERE job_id=?", (jid,))}


def draft_reply(text):
    return lambda model, system, user: {"answer": text} if "Draft an answer" in system else {}


# ---------------- FRM-01 ----------------
def test_tc052_greenhouse_style_form_gets_name_email_phone_links_filled(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.greenhouse_form())
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply("I like building agents.")))
    assert res.status == st.FILLED
    assert page.input_value("#fn") == "Aarav" and page.input_value("#ln") == "Mehta"
    assert page.input_value("#em") == "aarav.mehta@example.com" and page.input_value("#ph") == "+91 98765 43210"
    assert page.input_value("#li") == "linkedin.com/in/aarav"
    assert page.evaluate("document.getElementById('rs').files.length") == 1  # resume attached
    assert page.evaluate("window.__submits || 0") == 0                         # stopped before submit


def test_tc053_three_page_form_is_crossed_and_agent_stops_at_submit(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.multi_step_form())
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply("Agents are fun.")))
    assert res.status == st.FILLED and res.pages == 3
    assert page.input_value("#nm") == "Aarav Mehta" and page.input_value("#ph") == "+91 98765 43210"
    assert page.input_value("#yoe") in ("2.3", "2.4", "2.2", "2.5", "2.1")  # computed from profile dates
    assert page.is_visible("#s3") and page.is_visible("#submit")             # parked on the last page
    assert page.evaluate("window.__submits || 0") == 0
    assert {r["page_no"] for r in db.query("SELECT page_no FROM form_answers WHERE job_id=?", (jid,))} == {1, 2, 3}
    assert len(list((tmp_path / "shots").glob("*.png"))) == 3                # screenshot per page


# ---------------- FRM-02 ----------------
def test_tc054_email_comes_from_the_profile_with_zero_llm_calls(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.page(forms.field("Email", "em", typ="email") + forms.SUBMIT))
    llm = make_llm(lambda m, s, u: {})
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=llm, map_with_llm=True)
    assert res.status == st.FILLED and page.input_value("#em") == "aarav.mehta@example.com"
    assert llm.backend_obj.calls == []
    row = answers(db, jid)["Email"]
    assert (row["source"], row["confidence"]) == ("profile", 1.0)


@pytest.mark.parametrize("label", ["Mobile no.", "Contact number", "Phone"])
def test_tc055_different_phone_labels_all_map_to_the_same_profile_key(label, db, profile, resume, settings, notifier, page, tmp_path):
    spec = FieldSpec(ref=f"text:{label}:0", label=label, type="text")
    assert map_field(spec).profile_key == "personal.phone"
    jid = start(db, tmp_path, forms.phone_label_form(label))
    assert run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path).status == st.FILLED
    assert page.input_value("#ph") == "+91 98765 43210"


# ---------------- FRM-03 ----------------
def test_tc056_same_question_in_another_form_is_answered_from_the_bank_without_llm(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    AnswerBank(db).upsert("Why do you want to join?", "Because I enjoy building LLM agents.", human_approved=True)
    jid = start(db, tmp_path, forms.greenhouse_form(question="Why do you want to join?", with_dropdown=False))
    llm = make_llm(lambda m, s, u: {"answer": "SHOULD NOT BE USED"})
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=llm)
    assert page.input_value("#q1") == "Because I enjoy building LLM agents."
    assert llm.backend_obj.calls == []
    row = answers(db, jid)["Why do you want to join?"]
    assert row["source"] == "bank" and row["needs_review"] == 0 and row["confidence"] == pytest.approx(1.0, abs=0.01)
    assert db.scalar("SELECT use_count FROM answer_bank") == 1


def test_tc057_slightly_rephrased_question_above_0_90_reuses_the_bank_answer(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    from jobagent.core.similarity import similarity
    stored, asked = "Why do you want to join us?", "Why do you want to join?"
    assert similarity(stored, asked) > 0.90
    AnswerBank(db).upsert(stored, "Bank answer.", human_approved=False)
    jid = start(db, tmp_path, forms.greenhouse_form(question=asked, with_dropdown=False))
    llm = make_llm(lambda m, s, u: {"answer": "new draft"})
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=llm)
    assert page.input_value("#q1") == "Bank answer." and llm.backend_obj.calls == []
    assert answers(db, jid)[asked]["needs_review"] == 1  # not human-approved => still flagged


def test_tc058_question_below_0_90_similarity_gets_a_new_draft(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    from jobagent.core.similarity import similarity
    stored, asked = "Why do you want to join us?", "Why do you want to join our company?"
    assert similarity(stored, asked) < 0.90
    AnswerBank(db).upsert(stored, "Bank answer.", human_approved=True)
    jid = start(db, tmp_path, forms.greenhouse_form(question=asked, with_dropdown=False))
    llm = make_llm(draft_reply("Fresh draft."))
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=llm)
    assert page.input_value("#q1") == "Fresh draft." and len(llm.backend_obj.calls) == 1
    assert answers(db, jid)[asked]["source"] == "llm"


# ---------------- FRM-04 ----------------
def test_tc059_custom_question_draft_is_at_most_80_words_and_flagged_for_review(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    long_answer = " ".join(f"word{i}" for i in range(150))
    jid = start(db, tmp_path, forms.greenhouse_form(question="Describe a project you are proud of."))
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply(long_answer)))
    row = answers(db, jid)["Describe a project you are proud of."]
    assert len(row["answer"].split()) <= 80 and row["needs_review"] == 1 and row["source"] == "llm"
    assert len(truncate_words(long_answer).split()) <= 80


def test_tc060_dropdown_answer_is_always_one_of_the_options(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.greenhouse_form())
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply("Yes")))
    assert page.input_value("#hy") == "Yes"
    assert answers(db, jid)["Are you comfortable with hybrid work?"]["answer"] in ("Yes", "No")


def test_tc060_an_answer_outside_the_options_is_never_filled(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.greenhouse_form())
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply("Absolutely, I love hybrid!!!")))
    row = answers(db, jid)["Are you comfortable with hybrid work?"]
    assert row["answer"] is None and row["needs_review"] == 1 and page.input_value("#hy") == ""
    assert choose_option("yes please", ["Yes", "No"]) == "Yes" and choose_option("Maybe", ["Yes", "No"]) is None


# ---------------- FRM-05 ----------------
def test_tc061_every_field_gets_a_row_with_question_answer_source_confidence(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.greenhouse_form())
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply("Yes")))
    rows = db.query("SELECT * FROM form_answers WHERE job_id=? ORDER BY id", (jid,))
    assert len(rows) == res.rows == 8
    assert [r["field_label"] for r in rows][:3] == ["First Name", "Last Name", "Email"]
    for r in rows:
        assert r["field_label"] and r["field_type"] and r["source"] in ("profile", "bank", "llm", "human")
        assert r["confidence"] is not None and r["needs_review"] in (0, 1) and r["page_no"] == 1


# ---------------- FRM-06 ----------------
@pytest.mark.parametrize("html", [forms.CAPTCHA_FORM, forms.CAPTCHA_IFRAME_FORM], ids=["div", "iframe"])
def test_tc062_recaptcha_page_goes_to_needs_human_with_no_bypass_attempt(html, db, profile, resume, settings, notifier, page, tmp_path):
    jid = start(db, tmp_path, html)
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path)
    assert res.status == st.NEEDS_HUMAN and any("CAPTCHA" in p for p in res.problems)
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.NEEDS_HUMAN
    assert page.input_value("#em") == ""                      # nothing was typed on a captcha page
    assert page.evaluate("window.__submits || 0") == 0
    assert "needs_human" in notifier.kinds()


def test_tc063_unknown_widget_custom_datepicker_needs_human_without_crashing(db, profile, resume, settings, notifier, page, tmp_path):
    jid = start(db, tmp_path, forms.DATEPICKER_FORM)
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path)
    assert res.status == st.NEEDS_HUMAN and any("unknown widget" in p for p in res.problems)


def test_login_wall_needs_human(db, profile, resume, settings, notifier, page, tmp_path):
    jid = start(db, tmp_path, forms.LOGIN_FORM)
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path)
    assert res.status == st.NEEDS_HUMAN and any("login" in p for p in res.problems)


def test_tc064_sensitive_field_missing_in_profile_is_not_guessed_and_needs_human(db, resume, settings, notifier, page, tmp_path, make_llm):
    profile = make_profile()  # every sensitive value is null
    jid = start(db, tmp_path, forms.NOTICE_FORM)
    llm = make_llm(lambda m, s, u: {"answer": "30"})
    res = run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=llm)
    assert res.status == st.NEEDS_HUMAN and any("Notice period" in p for p in res.problems)
    assert page.input_value("#np") == ""                       # left empty, not guessed
    assert llm.backend_obj.calls == []                         # the LLM was never even asked
    row = answers(db, jid)["Notice period (days)"]
    assert row["answer"] is None and row["needs_review"] == 1 and row["source"] == "profile"


# ---------------- FRM-07 ----------------
def test_tc065_clicking_a_submit_button_in_the_fill_phase_raises_submit_blocked(page):
    page.set_content(forms.page(forms.field("Email", "em") + forms.SUBMIT))
    with pytest.raises(SubmitBlocked):
        safe_click(page.locator("#submit"))
    assert page.evaluate("window.__submits || 0") == 0


@pytest.mark.parametrize("label", ["Apply Now", "Send application", "Finish", "Submit", "Complete Application"])
def test_tc066_submit_like_button_texts_are_all_blocked(label, page):
    page.set_content(forms.page(f'<button type="submit" id="b">{label}</button>'))
    with pytest.raises(SubmitBlocked):
        safe_click(page.locator("#b"))


def test_tc066_input_type_submit_value_is_checked_too_and_next_is_allowed(page):
    page.set_content('<input type="submit" id="s" value="Send application"><button id="n" type="button" onclick="window.x=1">Next</button>')
    with pytest.raises(SubmitBlocked):
        safe_click(page.locator("#s"))
    safe_click(page.locator("#n"))
    assert page.evaluate("window.x") == 1
    safe_click(page.locator("#s"), allow_submit=True)  # only the review/submit step may pass this flag


def test_tc065_even_a_programmatic_submit_is_cancelled_during_fill(db, profile, resume, settings, notifier, page, tmp_path, make_llm):
    jid = start(db, tmp_path, forms.greenhouse_form())
    run_fill(db, jid, profile, resume, settings, notifier, page, tmp_path, llm=make_llm(draft_reply("Yes")))
    page.evaluate("document.getElementById('f').requestSubmit()")
    page.wait_for_timeout(200)
    assert page.evaluate("window.__submits || 0") == 0         # page-level guard swallowed it


# ---------------- unit-level mapper sanity (supports FRM-02) ----------------
@pytest.mark.parametrize("label,key", [
    ("Email Address", "personal.email"), ("First Name", "personal.first_name"), ("Surname", "personal.last_name"),
    ("LinkedIn URL", "personal.links.linkedin"), ("GitHub", "personal.links.github"), ("Full name", "personal.name"),
    ("Notice Period", "sensitive.notice_period_days"), ("Expected CTC (LPA)", "sensitive.expected_ctc"),
    ("Current salary", "sensitive.current_ctc"), ("Willing to relocate?", "sensitive.relocation"),
    ("Are you legally authorized to work in India?", "sensitive.work_auth"), ("Total years of experience", "experience.total_years"),
])
def test_mapper_rules(label, key):
    assert map_field(FieldSpec(ref="r", label=label, type="text")).profile_key == key


def test_unmatched_label_is_a_custom_question_by_default():
    from jobagent.flows.f4_formfill.mapper import map_fields
    spec = FieldSpec(ref="r", label="What excites you about agentic systems?", type="textarea")
    assert map_field(spec) is None and map_fields([spec])["r"].category == "custom_question"
