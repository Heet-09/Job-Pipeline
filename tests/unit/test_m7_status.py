"""Module 7: STA-01 .. STA-05 (TC-081 .. TC-093)."""
from datetime import timedelta

import pytest

from conftest import NOW, insert_job
from helpers import FakeMail, MailAuthError
from jobagent.core.mail import Email
from jobagent.flows.f6_status.classifier import classify, extract_datetime
from jobagent.flows.f6_status.matcher import match
from jobagent.flows.f6_status.run import check_ghosted, run_status_check


def add_app(db, company="Acme AI Labs", title="GenAI Engineer", status="SUBMITTED", submitted_days_ago=1):
    jid = insert_job(db, title=title, company=company, status="SUBMITTED")
    cur = db.write("INSERT INTO applications(job_id, current_status, submitted_at) VALUES (?,?,?)",
                   (jid, status, (db.now() - timedelta(days=submitted_days_ago)).isoformat(timespec="seconds")))
    return cur.lastrowid


def mail(subject, body="", sender="Acme AI Labs Careers <jobs@acmeailabs.com>", mid=None, hours_ago=2):
    return Email(mid or f"m-{abs(hash((subject, body, sender)))}", sender, subject, NOW - timedelta(hours=hours_ago), text=body)


def status_of(db, app_id):
    return db.scalar("SELECT current_status FROM applications WHERE id=?", (app_id,))


# ---------------- STA-01 ----------------
def test_tc081_three_company_emails_within_48_hours_are_all_fetched_and_processed(db, notifier, settings):
    a1, a2, a3 = add_app(db, "Acme AI Labs", "GenAI Engineer"), add_app(db, "Beta Systems", "ML Engineer"), add_app(db, "Cyan Robotics", "AI Engineer")
    emails = [
        mail("Your application for GenAI Engineer was received", "Thank you for applying to Acme.", "Acme Careers <jobs@acmeailabs.com>", "e1"),
        mail("Application update: ML Engineer", "We have received your application for ML Engineer.", "Beta Systems HR <hr@betasystems.io>", "e2", 30),
        mail("AI Engineer - your application", "Your application for AI Engineer is under review.", "Cyan Robotics <talent@cyanrobotics.com>", "e3", 47),
    ]
    fm = FakeMail(emails)
    res = run_status_check(db, fm, notifier, settings)
    assert res.fetched == 3 and res.updated == 3
    assert [status_of(db, a) for a in (a1, a2, a3)] == ["RECEIVED"] * 3
    assert "newer_than:2d" in fm.queries[0]


def test_tc082_newsletters_and_unrelated_emails_are_ignored(db, notifier, settings):
    app = add_app(db)
    emails = [mail("This week in AI: our newsletter", "Top stories. Unsubscribe anytime.", "AI Weekly <news@aiweekly.com>", "n1"),
              mail("50% off cloud credits - webinar today", "Register now for the webinar.", "Cloud Co <promo@cloudco.com>", "n2")]
    res = run_status_check(db, FakeMail(emails), notifier, settings)
    assert res.ignored == 2 and res.updated == 0 and res.manual == 0
    assert status_of(db, app) == "SUBMITTED" and db.scalar("SELECT COUNT(*) FROM manual_review") == 0


def test_auth_failure_alerts_instead_of_silent_skip(db, notifier, settings):
    res = run_status_check(db, FakeMail(error=MailAuthError("401")), notifier, settings)
    assert res.auth_failed and notifier.kinds() == ["auth_failed"]


def test_rerunning_the_same_emails_changes_nothing(db, notifier, settings):
    app = add_app(db)
    fm = FakeMail([mail("Your application for GenAI Engineer was received", "Thank you for applying.", mid="e1")])
    run_status_check(db, fm, notifier, settings)
    events = db.scalar("SELECT COUNT(*) FROM status_events")
    second = run_status_check(db, fm, notifier, settings)
    assert second.fetched == 0 and db.scalar("SELECT COUNT(*) FROM status_events") == events


# ---------------- STA-02 ----------------
def test_tc083_application_received_email_sets_received(db, notifier, settings):
    app = add_app(db)
    run_status_check(db, FakeMail([mail("Thanks for applying - GenAI Engineer", "Your application was received.", mid="e1")]), notifier, settings)
    assert status_of(db, app) == "RECEIVED"
    assert db.one("SELECT status, email_id FROM status_events")["status"] == "RECEIVED"


def test_tc084_interview_email_sets_interview_scheduled_and_extracts_datetime(db, notifier, settings):
    app = add_app(db)
    body = "We would like to invite you for an interview for the GenAI Engineer role on 5 November 2026 at 3:00 PM IST."
    run_status_check(db, FakeMail([mail("Interview invitation - GenAI Engineer", body, mid="e1")]), notifier, settings)
    assert status_of(db, app) == "INTERVIEW"
    k = classify(mail("Interview invitation", body))
    assert k.label == "interview_scheduled" and k.interview_datetime == "2026-11-05T15:00"


@pytest.mark.parametrize("text,expected", [
    ("on 5 November 2026 at 3:00 PM", "2026-11-05T15:00"), ("Nov 5, 2026 at 10:30 AM", "2026-11-05T10:30"),
    ("2026-11-05 14:00", "2026-11-05T14:00"), ("on 12th December 2026, 11:00 AM", "2026-12-12T11:00"),
    ("sometime next week", None), ("on 5 November 2026", None),
])
def test_datetime_extraction(text, expected):
    assert extract_datetime(text) == expected


def test_tc085_rejection_email_sets_rejected(db, notifier, settings):
    app = add_app(db)
    body = "Thank you for your interest. Unfortunately, we have decided to move forward with other candidates."
    run_status_check(db, FakeMail([mail("Update on your GenAI Engineer application", body, mid="e1")]), notifier, settings)
    assert status_of(db, app) == "REJECTED"


def test_tc086_ambiguous_email_is_labelled_other_and_status_is_not_updated(db, notifier, settings):
    app = add_app(db)
    em = mail("Update on your GenAI Engineer application", "Hi, just touching base about a few things. Let's talk soon.", mid="e1")
    assert classify(em).label == "other"
    run_status_check(db, FakeMail([em]), notifier, settings)
    assert status_of(db, app) == "SUBMITTED" and db.scalar("SELECT COUNT(*) FROM status_events") == 0


def test_status_never_moves_backwards(db, notifier, settings):
    app = add_app(db, status="INTERVIEW")
    run_status_check(db, FakeMail([mail("GenAI Engineer application received", "We have received your application.", mid="e1")]), notifier, settings)
    assert status_of(db, app) == "INTERVIEW"


# ---------------- STA-03 ----------------
def test_tc087_interview_email_raises_immediate_alert_with_calendar_suggestion(db, notifier, settings):
    add_app(db)
    body = "Please join the interview for GenAI Engineer on 5 November 2026 at 3:00 PM."
    run_status_check(db, FakeMail([mail("Interview - GenAI Engineer", body, mid="e1")]), notifier, settings)
    alert = next(a for a in notifier.alerts if a["kind"] == "interview")
    assert "GenAI Engineer @ Acme AI Labs" in alert["message"]
    assert alert["calendar_event"] == {"summary": "Interview: GenAI Engineer @ Acme AI Labs",
                                       "start": "2026-11-05T15:00", "end": "2026-11-05T16:00"}


def test_tc088_interview_email_without_datetime_alerts_but_creates_no_blank_event(db, notifier, settings):
    app = add_app(db)
    run_status_check(db, FakeMail([mail("Interview - GenAI Engineer", "We'd like to schedule an interview with you soon.", mid="e1")]), notifier, settings)
    alert = next(a for a in notifier.alerts if a["kind"] == "interview")
    assert alert["calendar_event"] is None and "no date/time" in alert["message"]
    assert status_of(db, app) == "INTERVIEW"


# ---------------- STA-04 ----------------
def test_tc089_no_reply_for_14_days_marks_ghosted(db, settings):
    app = add_app(db, submitted_days_ago=14)
    assert check_ghosted(db, settings) == 1 and status_of(db, app) == "GHOSTED"
    assert db.one("SELECT status FROM status_events WHERE application_id=?", (app,))["status"] == "GHOSTED"


def test_tc090_13_days_without_reply_changes_nothing(db, settings):
    app = add_app(db, submitted_days_ago=13)
    assert check_ghosted(db, settings) == 0 and status_of(db, app) == "SUBMITTED"


def test_tc091_reply_on_day_10_prevents_ghosting_at_day_14(db, notifier, settings, clock):
    app = add_app(db, submitted_days_ago=0)
    clock.advance(days=10)
    run_status_check(db, FakeMail([mail("GenAI Engineer application received", "We have received your application.", mid="e1")]), notifier, settings)
    clock.advance(days=4)  # day 14 since submit
    assert check_ghosted(db, settings) == 0 and status_of(db, app) == "RECEIVED"
    clock.advance(days=10)  # 14 days after the reply
    assert check_ghosted(db, settings) == 1


def test_ghosting_ignores_interview_and_rejected_applications(db, settings):
    a, b = add_app(db, "A Co", status="INTERVIEW", submitted_days_ago=30), add_app(db, "B Co", status="REJECTED", submitted_days_ago=30)
    assert check_ghosted(db, settings) == 0 and (status_of(db, a), status_of(db, b)) == ("INTERVIEW", "REJECTED")


# ---------------- STA-05 ----------------
def test_tc092_two_roles_at_one_company_and_an_unclear_email_goes_to_manual_list(db, notifier, settings):
    a1, a2 = add_app(db, "Acme AI Labs", "GenAI Engineer"), add_app(db, "Acme AI Labs", "ML Engineer")
    em = mail("Update on your application", "We have received your application and will be in touch.", mid="e1")
    res = run_status_check(db, FakeMail([em]), notifier, settings)
    assert res.manual == 1 and res.updated == 0
    assert (status_of(db, a1), status_of(db, a2)) == ("SUBMITTED", "SUBMITTED")
    row = db.one("SELECT * FROM manual_review")
    assert "ambiguous" in row["reason"] and row["resolved"] == 0 and row["email_id"] == "e1"


def test_tc092_the_same_company_email_that_names_the_role_is_matched(db, notifier, settings):
    a1, a2 = add_app(db, "Acme AI Labs", "GenAI Engineer"), add_app(db, "Acme AI Labs", "Data Platform Manager")
    em = mail("Your application for GenAI Engineer was received", "Thank you for applying.", mid="e1")
    run_status_check(db, FakeMail([em]), notifier, settings)
    assert (status_of(db, a1), status_of(db, a2)) == ("RECEIVED", "SUBMITTED")


def test_tc093_low_score_or_small_margin_goes_to_manual_list(db, notifier, settings):
    add_app(db, "Zeta Industries", "Backend Developer")
    stranger = mail("Re: your application", "We have received your application.", "Hiring <hr@somewhereelse.org>", "e-low")
    m = match(stranger, [{"company": "Zeta Industries", "title": "Backend Developer", "application_id": 1}])
    assert m.app is None and m.best <= 80 and "score" in m.reason
    res = run_status_check(db, FakeMail([stranger]), notifier, settings)
    assert res.manual == 1 and res.updated == 0
    assert "<= 80" in db.one("SELECT reason FROM manual_review")["reason"]
    # small margin: exactly two identical candidates
    apps = [{"company": "Acme AI Labs", "title": "GenAI Engineer", "application_id": 1}, {"company": "Acme AI Labs", "title": "GenAI Engineer", "application_id": 2}]
    assert match(mail("GenAI Engineer application", mid="x"), apps).app is None
