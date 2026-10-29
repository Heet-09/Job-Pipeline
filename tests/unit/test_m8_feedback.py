"""Module 8: FBK-01 .. FBK-04 (TC-094 .. TC-101)."""
from datetime import datetime, timedelta

import pytest

from conftest import insert_job
from jobagent.core.schemas import FieldMap
from jobagent.flows.f4_formfill.answer_bank import AnswerBank
from jobagent.flows.f7_feedback.cleanup import cleanup_answer_bank
from jobagent.flows.f7_feedback.evals import (
    check_regression, default_mapper, evaluate_mapper, load_golden, save_baseline,
)
from jobagent.flows.f7_feedback.metrics import bucket_response_rates, weekly_funnel

WEEK = datetime(2026, 10, 19, 0, 0, 0)  # Monday


def add_discovered(db, n, day=1):
    for _ in range(n):
        insert_job(db, discovered_at=(WEEK + timedelta(days=day, hours=3)).isoformat(timespec="seconds"))


def add_app(db, status, score=None, when=None):
    jid = insert_job(db, status="SUBMITTED")
    when = when or (WEEK + timedelta(days=2))
    db.write("INSERT INTO applications(job_id, current_status, submitted_at) VALUES (?,?,?)", (jid, status, when.isoformat(timespec="seconds")))
    if score is not None:
        db.write("INSERT INTO job_scores(job_id, llm_score) VALUES (?,?)", (jid, score))
    return jid


# ---------------- FBK-01 ----------------
def test_tc094_funnel_report_shows_exactly_the_known_numbers(db):
    add_discovered(db, 20)
    for status in ["INTERVIEW", "INTERVIEW", "SHORTLISTED", "REJECTED"] + ["RECEIVED"] * 3 + ["SUBMITTED"] * 3:
        add_app(db, status)
    # noise outside the week must not be counted
    add_discovered(db, 5, day=9)
    add_app(db, "INTERVIEW", when=WEEK + timedelta(days=10))
    f = weekly_funnel(db, WEEK)
    assert (f.discovered, f.applied, f.interviews, f.responses) == (20, 10, 2, 4)
    text = f.render()
    assert "Discovered: 20" in text and "Applied:    10" in text and "Interviews: 2" in text and "40%" in text


def test_tc095_empty_week_gives_a_report_of_zeros_without_crashing(db):
    f = weekly_funnel(db, WEEK)
    assert (f.discovered, f.applied, f.responses, f.interviews) == (0, 0, 0, 0)
    assert "Discovered: 0" in f.render() and "n/a" in f.render()


# ---------------- FBK-02 ----------------
def test_tc096_bucket_80_plus_with_5_applied_2_positive_shows_40_percent(db):
    for status in ["SHORTLISTED", "INTERVIEW", "REJECTED", "SUBMITTED", "GHOSTED"]:
        add_app(db, status, score=85)
    add_app(db, "INTERVIEW", score=72)  # another bucket must not leak in
    rates = {b.bucket: b for b in bucket_response_rates(db)}
    assert (rates["80+"].applied, rates["80+"].positive, rates["80+"].rate) == (5, 2, 40.0)
    assert "80+: 2/5 positive = 40%" == rates["80+"].render()
    assert rates["70-79"].rate == 100.0


def test_tc097_bucket_with_zero_applications_has_no_division_error(db):
    add_app(db, "INTERVIEW", score=85)
    rates = {b.bucket: b for b in bucket_response_rates(db)}
    assert rates["50-69"].applied == 0 and rates["50-69"].rate is None
    assert rates["50-69"].render() == "50-69: 0/0 positive = n/a"
    assert [b.bucket for b in bucket_response_rates(db)] == ["80+", "70-79", "50-69"]  # empty buckets are still listed


# ---------------- FBK-03 ----------------
def bank_row(db, q, a, human=0, uses=0, ts="2026-10-01T00:00:00"):
    return db.write("INSERT INTO answer_bank(canonical_question, answer, human_approved, use_count, updated_at) VALUES (?,?,?,?,?)", (q, a, human, uses, ts)).lastrowid


def test_tc098_two_conflicting_answers_to_the_same_question_are_flagged(db):
    a = bank_row(db, "Why do you want to join us?", "Because of the mission.")
    b = bank_row(db, "Why do you want to join us?", "I want a higher salary.")
    rep = cleanup_answer_bank(db)
    assert rep.flagged == 2 and sorted(rep.flagged_ids) == [a, b]
    assert db.scalar("SELECT COUNT(*) FROM answer_bank WHERE needs_cleanup=1") == 2
    assert db.scalar("SELECT COUNT(*) FROM answer_bank") == 2  # nothing deleted or rewritten


def test_tc098_duplicates_with_the_same_answer_are_merged(db):
    a = bank_row(db, "Why do you want to join us?", "Because of the mission.", uses=2)
    b = bank_row(db, "Why do you want to join us", "because of the mission", uses=3, ts="2026-10-02T00:00:00")
    rep = cleanup_answer_bank(db)
    assert rep.merged == 1 and db.scalar("SELECT COUNT(*) FROM answer_bank") == 1
    assert db.scalar("SELECT use_count FROM answer_bank") == 5


def test_tc099_human_approved_answer_is_never_overwritten_by_cleanup(db):
    human = bank_row(db, "Why do you want to join us?", "My carefully written answer.", human=1)
    other = bank_row(db, "Why do you want to join us?", "Auto draft answer.")
    cleanup_answer_bank(db)
    row = db.one("SELECT * FROM answer_bank WHERE id=?", (human,))
    assert row["answer"] == "My carefully written answer." and row["human_approved"] == 1
    assert db.one("SELECT answer FROM answer_bank WHERE id=?", (other,))["answer"] == "Auto draft answer."  # also untouched, just flagged


def test_tc099_merging_duplicates_keeps_the_human_approved_flag(db):
    bank_row(db, "Notice question?", "30 days", human=0, uses=5)
    bank_row(db, "Notice question?", "30 days", human=1, uses=1)
    cleanup_answer_bank(db)
    row = db.one("SELECT * FROM answer_bank")
    assert row["human_approved"] == 1 and row["use_count"] == 6


def test_cleanup_leaves_unrelated_questions_alone(db):
    bank_row(db, "Why do you want to join us?", "A")
    bank_row(db, "What is your biggest strength?", "B")
    rep = cleanup_answer_bank(db)
    assert (rep.groups, rep.merged, rep.flagged) == (0, 0, 0)


# ---------------- FBK-04 ----------------
def test_tc100_mapper_accuracy_on_20_golden_forms_meets_the_90_percent_target(settings):
    forms = load_golden()
    assert len(forms) == 20
    res = evaluate_mapper()
    assert res.forms == 20 and res.total >= 150
    assert res.accuracy >= settings.mapper_accuracy_target, "\n".join(res.errors)


def test_tc101_a_change_that_lowers_accuracy_is_flagged_as_a_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    good = evaluate_mapper()
    save_baseline(good.accuracy, baseline)
    assert check_regression(good.accuracy, baseline).flagged is False

    def worse_mapper(spec):  # simulates a bad prompt/rule change: sensitive questions now look like free text
        fm = default_mapper(spec)
        return FieldMap(ref=spec.ref, category="custom_question") if fm.category == "sensitive" else fm
    bad = evaluate_mapper(worse_mapper)
    reg = check_regression(bad.accuracy, baseline)
    assert bad.accuracy < good.accuracy and reg.flagged is True and "REGRESSION" in reg.message


def test_regression_check_without_a_baseline_does_not_flag(tmp_path):
    r = check_regression(0.5, tmp_path / "missing.json")
    assert r.flagged is False and r.baseline is None
