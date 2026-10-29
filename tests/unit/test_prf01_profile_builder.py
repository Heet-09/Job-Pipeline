"""Tests for PRF-01 (TC-001 .. TC-003) and the PRF-02 guarantee TC-004 that PRF-01 must not break.

The LLM is replaced by FakeExtractor, so these tests check our code (PDF reading, validation,
assembly, safety rules) - not the accuracy of a real model.
"""
import json

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from jobagent.core.schemas import (
    ExtractedBullet, ExtractedExperience, ExtractedProject, Personal, ResumeExtract, Skills,
)
from jobagent.flows.f0_profile.builder import ProfileBuildError, build_profile, normalize_date
from jobagent.flows.f0_profile.loader import load_profile, save_profile

RESUME_WITH_PROJECTS = [
    "Aarav Mehta",
    "aarav.mehta@example.com | +91 98765 43210 | Mumbai",
    "github.com/aarav | linkedin.com/in/aarav",
    "Summary",
    "GenAI engineer with 2 years of experience building LLM agents.",
    "Experience",
    "Acme AI Labs - GenAI Engineer (Jan 2022 - Present)",
    "- Built a LangGraph agent that automated support triage.",
    "- Reduced latency by 40% using caching.",
    "Beta Systems - Software Engineer (Jun 2020 - Dec 2021)",
    "- Developed REST APIs in Python and FastAPI.",
    "Projects",
    "Job Pipeline Agent",
    "- Automated job applications with Playwright and LangChain.",
    "Skills",
    "Python, LangChain, LangGraph, FastAPI, SQL",
    "Education",
    "B.Tech Computer Science, Mumbai University (2016 - 2020)",
]


def make_pdf(path, lines):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return path


def full_extract(**over):
    data = dict(
        personal=Personal(name="Aarav Mehta", email="aarav.mehta@example.com", phone="+91 98765 43210",
                          location="Mumbai", links={"github": "github.com/aarav", "linkedin": "linkedin.com/in/aarav"}),
        summary="GenAI engineer with 2 years of experience building LLM agents.",
        experience=[
            ExtractedExperience(company="Acme AI Labs", role="GenAI Engineer", start="Jan 2022", end="Present", bullets=[
                ExtractedBullet(text="Built a LangGraph agent that automated support triage.", skills=["LangGraph"]),
                ExtractedBullet(text="Reduced latency by 40% using caching.", skills=[])]),
            ExtractedExperience(company="Beta Systems", role="Software Engineer", start="Jun 2020", end="Dec 2021", bullets=[
                ExtractedBullet(text="Developed REST APIs in Python and FastAPI.", skills=["Python", "FastAPI"])]),
        ],
        projects=[ExtractedProject(name="Job Pipeline Agent", bullets=[
            ExtractedBullet(text="Automated job applications with Playwright and LangChain.", skills=["Playwright", "LangChain"])])],
        skills=Skills(core=["Python", "LangGraph", "FastAPI"], familiar=["SQL"]),
    )
    data.update(over)
    return ResumeExtract(**data)


class FakeExtractor:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def extract(self, text):
        self.calls += 1
        return self.result


@pytest.fixture
def out(tmp_path):
    return tmp_path / "data" / "profile.json"


# ---------------- TC-001 ----------------
def test_tc001_valid_resume_builds_profile_with_dates(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    res = build_profile(pdf, FakeExtractor(full_extract()), out)

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert [e["company"] for e in saved["experience"]] == ["Acme AI Labs", "Beta Systems"]
    assert (saved["experience"][0]["start"], saved["experience"][0]["end"]) == ("2022-01", "present")
    assert (saved["experience"][1]["start"], saved["experience"][1]["end"]) == ("2020-06", "2021-12")
    assert saved["projects"][0]["name"] == "Job Pipeline Agent"
    assert saved["skills"]["core"] == ["Python", "LangGraph", "FastAPI"]
    assert saved["personal"]["email"] == "aarav.mehta@example.com"
    assert res.warnings == []
    # bullets get stable ids the tailor (F3) will rely on
    assert saved["experience"][0]["bullets"][0]["id"] == "e1b1"
    assert saved["projects"][0]["bullets"][0]["id"] == "p1b1"
    assert load_profile(out) == res.profile  # file round-trips through the schema


# ---------------- TC-002 ----------------
def test_tc002_corrupt_pdf_gives_clear_error_and_saves_nothing(tmp_path, out):
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"this is definitely not a pdf \x00\x01\x02")
    ex = FakeExtractor(full_extract())
    with pytest.raises(ProfileBuildError, match="could not read PDF"):
        build_profile(bad, ex, out)
    assert not out.exists() and ex.calls == 0


def test_tc002_scanned_image_only_pdf_gives_clear_error_and_saves_nothing(tmp_path, out):
    scanned = tmp_path / "scanned.pdf"
    c = canvas.Canvas(str(scanned), pagesize=A4)
    c.rect(50, 50, 400, 600, fill=1)  # page with graphics but no text layer
    c.save()
    ex = FakeExtractor(full_extract())
    with pytest.raises(ProfileBuildError, match="scanned"):
        build_profile(scanned, ex, out)
    assert not out.exists() and ex.calls == 0


def test_tc002_missing_file(tmp_path, out):
    with pytest.raises(ProfileBuildError, match="not found"):
        build_profile(tmp_path / "nope.pdf", FakeExtractor(full_extract()), out)
    assert not out.exists()


def test_tc002_extractor_returns_nothing_usable_saves_nothing(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    with pytest.raises(ProfileBuildError, match="nothing usable"):
        build_profile(pdf, FakeExtractor(ResumeExtract()), out)
    assert not out.exists()


# ---------------- TC-003 ----------------
def test_tc003_no_projects_section_builds_profile_with_warning(tmp_path, out):
    lines = [ln for ln in RESUME_WITH_PROJECTS if ln not in
             ("Projects", "Job Pipeline Agent", "- Automated job applications with Playwright and LangChain.")]
    pdf = make_pdf(tmp_path / "resume.pdf", lines)
    res = build_profile(pdf, FakeExtractor(full_extract(projects=[])), out)
    assert out.exists() and res.profile.projects == []
    assert len(res.profile.experience) == 2
    assert any("No projects section" in w for w in res.warnings)


# ---------------- TC-004 (PRF-02 must hold for PRF-01 output) ----------------
def test_tc004_ctc_in_resume_never_reaches_sensitive_fields(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS + ["Current CTC: 12 LPA | Expected CTC: 18 LPA | Notice period: 30 days"])
    res = build_profile(pdf, FakeExtractor(full_extract()), out)
    s = json.loads(out.read_text(encoding="utf-8"))["sensitive"]
    assert s == {"current_ctc": None, "expected_ctc": None, "notice_period_days": None,
                 "relocation": None, "work_auth": None}
    assert res.profile.sensitive.current_ctc is None


def test_llm_output_schema_has_no_sensitive_field():
    assert "sensitive" not in ResumeExtract.model_fields


def test_rebuild_keeps_user_entered_sensitive_values(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    first = build_profile(pdf, FakeExtractor(full_extract()), out).profile
    first.sensitive.notice_period_days = 30
    first.sensitive.current_ctc = 12.0
    save_profile(first, out)
    again = build_profile(pdf, FakeExtractor(full_extract()), out).profile
    assert again.sensitive.notice_period_days == 30 and again.sensitive.current_ctc == 12.0


# ---------------- Guards ----------------
def test_hallucinated_company_is_dropped_with_warning(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    ex = full_extract()
    ex.experience.append(ExtractedExperience(company="Google DeepMind", role="Researcher", start="2019", end="2020"))
    res = build_profile(pdf, FakeExtractor(ex), out)
    assert [e.company for e in res.profile.experience] == ["Acme AI Labs", "Beta Systems"]
    assert any("Google DeepMind" in w for w in res.warnings)


def test_hallucinated_email_is_dropped(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    ex = full_extract(personal=Personal(name="Aarav Mehta", email="fake@invented.com"))
    res = build_profile(pdf, FakeExtractor(ex), out)
    assert res.profile.personal.email == "" and any("Email" in w for w in res.warnings)


def test_unparseable_date_warns_and_is_left_empty(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    ex = full_extract()
    ex.experience[0].start = "sometime in spring"
    res = build_profile(pdf, FakeExtractor(ex), out)
    assert res.profile.experience[0].start is None and any("sometime in spring" in w for w in res.warnings)


def test_dry_run_writes_nothing(tmp_path, out):
    pdf = make_pdf(tmp_path / "resume.pdf", RESUME_WITH_PROJECTS)
    res = build_profile(pdf, FakeExtractor(full_extract()), out, dry_run=True)
    assert res.profile.experience and not out.exists()


@pytest.mark.parametrize("raw,expected", [
    ("Jan 2022", "2022-01"), ("January 2022", "2022-01"), ("Sept 2021", "2021-09"), ("01/2022", "2022-01"),
    ("2022-03", "2022-03"), ("2022", "2022"), ("Present", "present"), ("till date", "present"),
    ("", None), ("13/2022", None), ("whenever", None),
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected
