"""Module 4: RES-01 .. RES-05 (TC-041 .. TC-051) and SAF-03 (TC-106)."""
import json
import re

import pytest
from pypdf import PdfReader

from conftest import make_profile, insert_job
from jobagent.core import statuses as st
from jobagent.core.lexicon import TECH_TERMS, canon, find_terms
from jobagent.core.schemas import Bullet, Education, Experience, JDExtract, Personal, Profile, Project, Skills
from jobagent.flows.f0_profile.view import all_skills
from jobagent.flows.f3_resume.graph import run_tailor_loop
from jobagent.flows.f3_resume.models import TailoredResume
from jobagent.flows.f3_resume.renderer import diff_html, diff_lines, render_pdf, resume_text, unified_diff
from jobagent.flows.f3_resume.run import run_tailoring
from jobagent.flows.f3_resume.tailor import base_draft, resolve
from jobagent.flows.f3_resume.validator import LLMClaimChecker, numbers, validate

LANGCHAIN_JD = JDExtract(title="LLM Engineer", must_have_skills=["LangChain", "Python"], nice_to_have=["RAG"], role_category="genai_agent")
K8S_JD = JDExtract(title="Platform GenAI Engineer", must_have_skills=["Kubernetes", "Python", "LangChain"], role_category="genai_agent")


def draft_json(profile, rewrites=None, **over):
    d = base_draft(profile).model_dump()
    for e in d["experience"]:
        e["rewrites"] = {k: v for k, v in (rewrites or {}).items() if k in e["bullet_ids"]}
    d.update(over)
    return d


def ids_of(resume: TailoredResume, company):
    return next(e.bullet_ids for e in resume.experience if e.company == company)


# ---------------- RES-01 ----------------
def test_tc041_langchain_heavy_jd_puts_langchain_bullets_first(profile):
    resume, violations = run_tailor_loop(profile, LANGCHAIN_JD)
    assert violations == [] and not resume.fallback
    assert ids_of(resume, "Acme AI Labs")[0] == "e1b3"          # was third in the profile
    assert resume.projects[0].name == "Job Pipeline Agent"       # LangChain project before the SQL one
    assert resume.skills_order[0] == "Python" and resume.skills_order.index("LangChain") < resume.skills_order.index("FastAPI")


def test_tc041_ordering_is_enforced_even_if_the_llm_returns_a_different_order(profile, make_llm):
    d = draft_json(profile)
    d["experience"][0]["bullet_ids"] = ["e1b2", "e1b1", "e1b3"]
    resume, _ = run_tailor_loop(profile, LANGCHAIN_JD, make_llm([d]))
    assert ids_of(resume, "Acme AI Labs")[0] == "e1b3"


def test_tc042_every_output_bullet_traces_back_to_an_original_id(profile, make_llm):
    d = draft_json(profile, rewrites={"e1b3": "Engineered LangChain retrieval pipelines for 5000 users."})
    resume, violations = run_tailor_loop(profile, LANGCHAIN_JD, make_llm([d]))
    assert violations == [] and not resume.fallback
    original_ids = {b.id for e in profile.experience for b in e.bullets} | {b.id for p in profile.projects for b in p.bullets}
    used = [i for e in resume.experience for i in e.bullet_ids] + [i for p in resume.projects for i in p.bullet_ids]
    assert set(used) <= original_ids and len(used) == len(set(used))
    assert set(resume.experience[0].rewrites) <= set(ids_of(resume, "Acme AI Labs"))
    assert "Engineered LangChain" in resume_text(resolve(resume, profile))


# ---------------- RES-02 ----------------
def test_tc043_kubernetes_in_jd_but_not_in_profile_never_reaches_the_resume(profile, make_llm):
    assert "kubernetes" not in all_skills(profile)
    clean, _ = run_tailor_loop(profile, K8S_JD)                       # reorder-only path
    assert "kubernetes" not in resume_text(resolve(clean, profile)).lower()
    assert "Kubernetes" not in clean.skills_order
    bad = draft_json(profile, rewrites={"e1b1": "Built a LangGraph agent deployed on Kubernetes."}, skills_order=["Python", "Kubernetes"])
    llm = make_llm([bad])
    resume, violations = run_tailor_loop(profile, K8S_JD, llm)        # LLM tries to add it -> rejected twice -> base resume
    assert resume.fallback and violations
    assert "kubernetes" not in resume_text(resolve(resume, profile)).lower()
    assert len(llm.backend_obj.calls) == 2


def test_tc044_rewrite_with_a_number_not_in_the_original_is_rejected(profile):
    for rewrite in ("Reduced latency by 60% using caching.", "Reduced latency by 40% using caching for 200 customers."):
        d = TailoredResume(**draft_json(profile, rewrites={"e1b2": rewrite}))
        assert any(v.code == "new_number" for v in validate(d, profile)), rewrite
    ok = TailoredResume(**draft_json(profile, rewrites={"e1b2": "Cut latency by 40% through caching."}))
    assert validate(ok, profile) == []


def test_tc045_changing_company_role_or_dates_is_rejected(profile):
    cases = {
        "company_changed": lambda d: d["experience"][0].update(company="Google"),
        "role_changed": lambda d: d["experience"][0].update(role="Senior Staff Engineer"),
        "start_changed": lambda d: d["experience"][0].update(start="2019-01"),
        "end_changed": lambda d: d["experience"][1].update(end="2025-12"),
    }
    for code, mutate in cases.items():
        d = draft_json(profile)
        mutate(d)
        assert code in {v.code for v in validate(TailoredResume(**d), profile)}, code


# ---------------- RES-03 ----------------
def _ten_bad_drafts(profile):
    def with_exp(**kw):
        d = draft_json(profile)
        d["experience"][0].update(kw)
        return d
    return [
        draft_json(profile, rewrites={"e1b1": "Built a LangGraph agent on Kubernetes."}),                     # 1 new tool
        draft_json(profile, rewrites={"e1b2": "Reduced latency by 60% using caching."}),                      # 2 new percent
        draft_json(profile, rewrites={"e1b3": "Built LangChain pipelines serving 90000 users."}),             # 3 new number
        with_exp(company="Google"),                                                                           # 4 company
        with_exp(role="Principal Engineer"),                                                                  # 5 role
        with_exp(start="2018-01"),                                                                            # 6 date
        with_exp(bullet_ids=["e1b1", "e9b9"]),                                                                # 7 unknown bullet id
        draft_json(profile, skills_order=["Python", "Docker"]),                                               # 8 skill not in profile
        draft_json(profile, summary="GenAI engineer with 10 years of experience building LLM agents."),       # 9 inflated years
        draft_json(profile, rewrites={"e1b1": "Built a LangGraph agent for Google support triage."}),         # 10 new entity
    ]


def test_tc046_validator_catches_all_10_deliberately_bad_drafts(profile):
    drafts = _ten_bad_drafts(profile)
    assert len(drafts) == 10
    missed = [i + 1 for i, d in enumerate(drafts) if not validate(TailoredResume(**d), profile)]
    assert missed == []
    assert validate(TailoredResume(**draft_json(profile)), profile) == []  # and the clean draft is accepted


def test_tc047_validator_failing_twice_uses_base_resume_and_flags_it(db, profile, make_llm, settings, tmp_path):
    jid = insert_job(db, status=st.SCORED, manual=1)
    db.write("UPDATE jobs SET jd_json=? WHERE id=?", (K8S_JD.model_dump_json(), jid))
    llm = make_llm([draft_json(profile, skills_order=["Python", "Kubernetes"])])
    summary = run_tailoring(db, profile, llm, tmp_path, settings)
    assert summary.tailored == 1 and summary.fallbacks == 1
    app = db.one("SELECT * FROM applications WHERE job_id=?", (jid,))
    assert app["resume_flag"] == "fallback_base_resume"
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == st.TAILORED
    assert len(llm.backend_obj.calls) == 2 and app["resume_diff"] == ""  # base resume => no diff


def test_llm_claim_checker_second_pass(profile, make_llm):
    d = TailoredResume(**draft_json(profile, rewrites={"e1b1": "Led a LangGraph agent for support triage."}))
    flagged = make_llm([{"adds_claim": True, "which": "'Led' implies leadership"}])
    assert [v.code for v in validate(d, profile, LLMClaimChecker(flagged))] == ["llm_claim"]
    clean = make_llm([{"adds_claim": False}])
    assert validate(d, profile, LLMClaimChecker(clean)) == []


# ---------------- RES-04 ----------------
def test_tc048_diff_highlights_changed_lines_and_not_unchanged_ones(profile):
    resume, _ = run_tailor_loop(profile, LANGCHAIN_JD)
    base, tailored = resume_text(resolve(base_draft(profile), profile)), resume_text(resolve(resume, profile))
    diffs = diff_lines(base, tailored)
    changed = {d.text for d in diffs if d.changed}
    unchanged = {d.text for d in diffs if not d.changed}
    assert "- Built LangChain retrieval pipelines serving 5000 users." in changed       # moved
    assert "EXPERIENCE" in unchanged and profile.personal.name in unchanged
    html = diff_html(base, tailored)
    assert 'class="chg add"' in html and 'class="same">  EXPERIENCE' in html.replace("+ ", "  ") or 'class="same"' in html
    assert re.search(r'class="same">[ ] EXPERIENCE', html)
    assert "@@" in unified_diff(base, tailored)


def test_tc048_identical_resumes_have_an_empty_diff(profile):
    t = resume_text(resolve(base_draft(profile), profile))
    assert not any(d.changed for d in diff_lines(t, t)) and unified_diff(t, t) == ""


# ---------------- RES-05 ----------------
def _pdf_for(profile, path):
    resume, _ = run_tailor_loop(profile, LANGCHAIN_JD)
    return render_pdf(resolve(resume, profile), path)


def test_tc049_pdf_text_has_correct_reading_order_and_all_sections(profile, tmp_path):
    info = _pdf_for(profile, tmp_path / "r.pdf")
    text = "\n".join(p.extract_text() for p in PdfReader(str(info.path)).pages)
    positions = [text.index(h) for h in ("Aarav Mehta", "Summary", "Skills", "Experience", "Projects", "Education")]
    assert positions == sorted(positions)
    for needle in ("Acme AI Labs", "Beta Systems", "Job Pipeline Agent", "Mumbai University", "LangChain retrieval pipelines"):
        assert needle in text
    assert text.index("Built LangChain retrieval") < text.index("Built a LangGraph agent")  # tailored order survives


def test_tc050_pdf_is_single_column_without_tables_or_images(profile, tmp_path):
    info = _pdf_for(profile, tmp_path / "r.pdf")
    reader = PdfReader(str(info.path))
    xs = []
    for page in reader.pages:
        res = page["/Resources"]
        assert "/XObject" not in res                      # no images / form xobjects
        page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: xs.append(tm[4] * cm[0] + cm[4]) if t.strip() else None)
    assert xs and min(xs) >= 40 and max(xs) < 120         # every line starts in the left margin => one column
    raw = info.path.read_bytes()
    assert b"/Subtype /Image" not in raw and b"/Subtype/Image" not in raw  # (/ImageB in /ProcSet is a standard header, not an image)


def _heavy_profile():
    exps = [Experience(company=f"Company {chr(65 + i)}", role="Engineer", start=f"{2010 + 2 * i}-01", end=f"{2011 + 2 * i}-12",
                       bullets=[Bullet(id=f"e{i}b{j}", text=f"Delivered measurable improvement number {j} across the platform using Python tooling and automation "
                                                              f"for the team and partners in project {i}.", skills=["Python"]) for j in range(8)]) for i in range(6)]
    projs = [Project(name=f"Project {chr(65 + i)}", bullets=[Bullet(id=f"p{i}b{j}", text=f"Built component {j} for project {i} with Python and clear documentation.", skills=["Python"])
                                                           for j in range(6)]) for i in range(5)]
    return Profile(personal=Personal(name="Heavy Profile", email="h@example.com"), summary="Experienced engineer.",
                   experience=exps, projects=projs, skills=Skills(core=["Python"]), education=[Education(institution="Uni", degree="BSc")])


def test_tc051_content_heavy_profile_still_renders_in_at_most_2_pages(tmp_path):
    p = _heavy_profile()
    resume, _ = run_tailor_loop(p, JDExtract(must_have_skills=["Python"]))
    info = render_pdf(resolve(resume, p), tmp_path / "heavy.pdf")
    assert len(PdfReader(str(info.path)).pages) <= 2 and info.pages <= 2
    assert info.bullets_trimmed > 0 or info.font_size < 10  # it had to shrink or trim to fit
    text = "\n".join(pg.extract_text() for pg in PdfReader(str(info.path)).pages)
    assert "Education" in text and "Projects" in text     # all sections survive trimming


# ---------------- SAF-03 ----------------
def _claims_are_subset(resolved, profile):
    original = resume_text(resolve(base_draft(profile), profile))
    allowed = {canon(s) for s in all_skills(profile)} | set(find_terms(original))
    nums_ok = numbers(resume_text(resolved)) - numbers(original) == set()
    tech_ok = set(find_terms(resume_text(resolved))) <= allowed
    return nums_ok and tech_ok


def test_tc106_every_tailored_resume_for_many_jds_only_contains_profile_claims(profile, make_llm):
    jds = [LANGCHAIN_JD, K8S_JD,
           JDExtract(title="ML Engineer", must_have_skills=["PyTorch", "TensorFlow", "Python"]),
           JDExtract(title="Data Engineer", must_have_skills=["Spark", "Airflow", "SQL"]),
           JDExtract(title="Backend Developer", must_have_skills=["Go", "Docker", "FastAPI"]),
           JDExtract(title="SAP Consultant", must_have_skills=["SAP", "Oracle"])]
    for jd in jds:
        sneaky = draft_json(profile, rewrites={"e1b1": f"Built a LangGraph agent using {(jd.must_have_skills or ['X'])[0]} at scale."})
        for llm in (None, make_llm([sneaky])):
            resume, _ = run_tailor_loop(profile, jd, llm)
            assert _claims_are_subset(resolve(resume, profile), profile), (jd.title, llm is None)
