"""Dashboard: data layer (plain functions) and the Streamlit pages (driven with streamlit.testing.AppTest)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import make_profile
from jobagent.core import statuses as st
from jobagent.core.db import Database
from jobagent.flows.f0_profile.loader import save_profile
from jobagent.ui import data as D
from jobagent.ui.demo import seed_demo

APP = Path(__file__).resolve().parents[2] / "src" / "jobagent" / "ui" / "app.py"


@pytest.fixture
def demo(db, tmp_path):
    seed_demo(db, tmp_path / "shots")
    return db


# ---------------- data layer ----------------
def test_overview_numbers_on_demo_data(demo):
    o = D.overview(demo)
    assert o["total_jobs"] == 18 and o["counts"][st.FILLED] == 2 and o["counts"][st.SCORED] == 2
    assert o["submitted_total"] == 5 and o["applications"]["INTERVIEW"] == 1
    assert o["llm_calls"] == 86 and o["llm_cost"] > 0


def test_overview_on_an_empty_database_does_not_crash(db):
    o = D.overview(db)
    assert o["total_jobs"] == 0 and o["submitted_total"] == 0 and o["funnel_7d"].applied == 0
    assert all(b.rate is None for b in o["buckets"]) and D.attention_items(db) == []


def test_attention_items_are_sorted_high_first_and_cover_each_problem(demo, tmp_path):
    items = D.attention_items(demo)
    assert [i[0] for i in items] == sorted((i[0] for i in items), key={"high": 0, "medium": 1, "low": 2}.get)
    text = " | ".join(i[1] for i in items)
    for needle in ("need you", "no confirmation", "waiting for your approval", "could not be matched", "interview stage", "failed processing", "conflict"):
        assert needle in text


def test_attention_items_check_the_profile(db, tmp_path):
    assert any("No profile.json" in i[1] for i in D.attention_items(db, tmp_path / "none.json"))
    p = tmp_path / "profile.json"
    save_profile(make_profile(), p)
    assert any("Sensitive profile fields not set" in i[1] and "notice_period_days" in i[1] for i in D.attention_items(db, p))
    save_profile(make_profile(current_ctc=1.0, expected_ctc=2.0, notice_period_days=30, relocation=True, work_auth="x"), p)
    assert D.attention_items(db, p) == []
    p.write_text("{not json", encoding="utf-8")
    assert any("unreadable" in i[1] for i in D.attention_items(db, p))


def test_jobs_table_filters_and_orders_by_score(demo):
    rows = D.jobs_table(demo)
    scores = [r["score"] for r in rows if r["score"] is not None]
    assert scores == sorted(scores, reverse=True) and rows[0]["score"] == 91 and rows[-1]["score"] is None
    assert {r["status"] for r in D.jobs_table(demo, status=[st.FILLED])} == {st.FILLED}
    assert all(r["score"] >= 85 for r in D.jobs_table(demo, min_score=85))
    assert [r["company"] for r in D.jobs_table(demo, search="woodgrove")] == ["Woodgrove Bank"]
    assert D.jobs_table(demo, source="linkedin_alert") == [] and D.sources(demo) == ["naukri_scraper"]


def test_job_detail_has_score_breakdown_history_and_application(demo):
    jid = demo.scalar("SELECT id FROM jobs WHERE company='Coho Winery Tech'")
    d = D.job_detail(demo, jid)
    assert d["score"]["llm_score"] == 90 and set(d["breakdown"]) == {"skills", "seniority", "salary", "role_type", "company"}
    assert [h["to_status"] for h in d["history"]] == ["DISCOVERED", "EXTRACTED", "SUBMITTED"]
    assert d["application"]["current_status"] == "INTERVIEW" and d["jd"]["role_category"] == "genai_agent"
    assert D.job_detail(demo, 99999) is None


def test_applications_table_shows_days_until_ghosted(demo):
    rows = {r["company"]: r for r in D.applications_table(demo)}
    assert rows["Margie Travel"]["status"] == "RECEIVED" and rows["Margie Travel"]["days_since_submit"] == 12
    assert rows["Margie Travel"]["ghost_in_days"] == 3            # last reply 11 days ago, ghosted after 14
    assert rows["VanArsdel"]["ghost_in_days"] == 11 and rows["Coho Winery Tech"]["ghost_in_days"] is None
    assert rows["Humongous Insurance"]["status"] == "SUBMIT_UNCERTAIN"   # never shown as blank
    assert len(rows) == 5


def test_set_application_status_logs_an_event_and_rejects_unknown_status(demo):
    aid = demo.scalar("SELECT id FROM applications WHERE current_status='SUBMITTED'")
    D.set_application_status(demo, aid, "REJECTED")
    assert demo.scalar("SELECT current_status FROM applications WHERE id=?", (aid,)) == "REJECTED"
    assert D.application_events(demo, aid)[-1]["status"] == "REJECTED"
    with pytest.raises(ValueError):
        D.set_application_status(demo, aid, "MADE_UP")


def test_review_queue_puts_needs_human_first_with_counts(demo):
    q = D.review_queue(demo)
    assert [r["status"] for r in q] == ["NEEDS_HUMAN", "FILLED", "FILLED"]
    assert q[0]["company"] == "Woodgrove Bank" and q[0]["to_review"] == 2 and q[0]["fields"] == 4


def test_resolve_manual_attach_updates_the_application_and_dismiss_does_not(demo):
    first, second = [r["id"] for r in D.manual_review_rows(demo)][::-1]
    aid = demo.scalar("SELECT id FROM applications WHERE current_status='SUBMITTED'")
    D.resolve_manual(demo, first, aid, "SHORTLISTED")
    assert demo.scalar("SELECT current_status FROM applications WHERE id=?", (aid,)) == "SHORTLISTED"
    D.resolve_manual(demo, second)  # dismiss
    assert D.manual_review_rows(demo) == [] and len(D.manual_review_rows(demo, include_resolved=True)) == 2
    with pytest.raises(KeyError):
        D.resolve_manual(demo, 999)


def test_bank_update_marks_human_approved_and_clears_cleanup_flag_and_delete(demo):
    flagged = [r for r in D.bank_rows(demo) if r["needs_cleanup"]][0]
    D.update_bank_answer(demo, flagged["id"], "My final answer.")
    row = demo.one("SELECT * FROM answer_bank WHERE id=?", (flagged["id"],))
    assert (row["answer"], row["human_approved"], row["needs_cleanup"]) == ("My final answer.", 1, 0)
    D.delete_bank_answer(demo, flagged["id"])
    assert demo.one("SELECT 1 FROM answer_bank WHERE id=?", (flagged["id"],)) is None


def test_llm_summary_and_history_and_versions(demo):
    s = {r["flow"]: r for r in D.llm_summary(demo)}
    assert s["tailor"]["calls"] == 6 and s["tailor"]["cost_usd"] > s["extract"]["cost_usd"]
    assert D.recent_history(demo, 5)[0]["title"] and len(D.profile_versions(demo)) == 2


# ---------------- Streamlit pages ----------------
@pytest.fixture
def run_app(monkeypatch, tmp_path):
    def make(seed=True, profile=False):
        path = tmp_path / "ui.db"
        d = Database(path)
        if seed:
            seed_demo(d, tmp_path / "shots")
        d.close()
        monkeypatch.setenv("JOBAGENT_DB", str(path))
        pp = tmp_path / "profile.json"
        if profile:
            save_profile(make_profile(), pp)
        monkeypatch.setenv("JOBAGENT_PROFILE", str(pp))
        return AppTest.from_file(str(APP), default_timeout=30).run(), path
    return make


def goto(at, page):
    at.sidebar.radio[0].set_value(page).run()
    return at


@pytest.mark.parametrize("page", ["Overview", "Jobs", "Review", "Applications", "Inbox", "Answer Bank", "Health"])
def test_every_page_renders_without_errors_on_demo_data(run_app, page):
    at, _ = run_app()
    goto(at, page)
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == page


@pytest.mark.parametrize("page", ["Overview", "Jobs", "Review", "Applications", "Inbox", "Answer Bank", "Health"])
def test_every_page_renders_on_an_empty_database(run_app, page):
    at, _ = run_app(seed=False)
    goto(at, page)
    assert not at.exception, [e.value for e in at.exception]


def test_overview_shows_attention_items_metrics_and_sidebar_count(run_app):
    at, _ = run_app(profile=True)
    assert "Needs your attention" in [s.value for s in at.subheader]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Jobs found"] == "18" and metrics["Submitted"] == "5" and metrics["Interviews"] == "1" and metrics["Ready to review"] == "2"
    assert any("need you" in m.value for m in at.markdown)
    assert "item(s) need attention" in at.sidebar.caption[0].value


def test_open_button_on_an_attention_item_navigates_to_that_page(run_app):
    at, _ = run_app()
    btn = next(b for b in at.button if b.key.startswith("open-") and "need you" in b.key)
    btn.click().run()
    assert at.sidebar.radio[0].value == "Review" and at.title[0].value == "Review"


def test_jobs_page_lists_jobs_and_search_filters(run_app):
    at, _ = run_app()
    goto(at, "Jobs")
    assert len(at.dataframe[0].value) == 15  # 18 jobs, default view hides the 2 REJECTED and 1 SKIPPED
    at.text_input[0].set_value("Woodgrove").run()
    assert list(at.dataframe[0].value["company"]) == ["Woodgrove Bank"]


def test_review_page_shows_the_needs_human_reason_and_approve_is_locked_until_confirmed(run_app):
    at, _ = run_app()
    goto(at, "Review")
    assert any("needs you" in e.value and "Notice period" in e.value for e in at.error)
    at.selectbox[0].select_index(1).run()                      # a FILLED application
    assert not at.exception
    approve = next(b for b in at.button if b.label == "Approve and submit")
    assert approve.disabled is True
    at.checkbox[0].check().run()
    assert next(b for b in at.button if b.label == "Approve and submit").disabled is False   # (never clicked here: it would open a browser)


def test_editing_an_answer_on_the_review_page_saves_it_and_remembers_it(run_app):
    at, path = run_app()
    goto(at, "Review")
    at.selectbox[0].select_index(1).run()
    area = next(t for t in at.text_area if (t.value or "").startswith("I enjoy building reliable LLM agents and your team"))
    area.set_value("A better, human-written answer.").run()
    next(b for b in at.button if b.key and b.key.startswith("save-")).click().run()
    d = Database(path)
    row = d.one("SELECT * FROM form_answers WHERE answer='A better, human-written answer.'")
    assert row["source"] == "human" and row["needs_review"] == 0
    assert d.one("SELECT human_approved FROM answer_bank WHERE answer='A better, human-written answer.'")["human_approved"] == 1


def test_inbox_attach_and_resolve_updates_the_application(run_app):
    at, path = run_app()
    goto(at, "Inbox")
    assert len(at.expander) == 2
    at.selectbox[0].select_index(1).run()                       # first real application
    at.selectbox[1].select("SHORTLISTED").run()
    next(b for b in at.button if b.key.startswith("attach-")).click().run()
    d = Database(path)
    assert d.scalar("SELECT COUNT(*) FROM manual_review WHERE resolved=0") == 1
    assert d.scalar("SELECT COUNT(*) FROM status_events WHERE snippet LIKE 'from email%'") == 1


def test_answer_bank_cleanup_button_runs(run_app):
    at, path = run_app()
    goto(at, "Answer Bank")
    next(b for b in at.button if b.label == "Run cleanup").click().run()
    assert not at.exception and any("flagged" in s.value for s in at.success)


def test_health_page_warns_when_auto_submit_is_on_or_profile_is_missing(run_app):
    at, _ = run_app()
    goto(at, "Health")
    assert any("No profile" in w.value for w in at.warning)
    assert {m.label: m.value for m in at.metric}["Auto-submit"] == "off"


def test_app_imports_when_launched_directly_without_pythonpath(tmp_path):
    """Regression: `streamlit run src/jobagent/ui/app.py` used to fail with ModuleNotFoundError: No module named 'jobagent'."""
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(JOBAGENT_DB=str(tmp_path / "x.db"), JOBAGENT_PROFILE=str(tmp_path / "p.json"))
    r = subprocess.run([sys.executable, str(APP)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert "ModuleNotFoundError" not in r.stderr, r.stderr[-600:]
