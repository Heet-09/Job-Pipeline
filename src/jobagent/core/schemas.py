from pydantic import BaseModel, Field


class Bullet(BaseModel):
    id: str
    text: str
    skills: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    company: str
    role: str
    start: str | None = None
    end: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    bullets: list[Bullet] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str = ""
    start: str | None = None
    end: str | None = None


class Skills(BaseModel):
    core: list[str] = Field(default_factory=list)
    familiar: list[str] = Field(default_factory=list)


class Personal(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: dict[str, str] = Field(default_factory=dict)


class Sensitive(BaseModel):
    """Filled only by the user (PRF-02). Never populated from a resume or an LLM."""
    current_ctc: float | None = None
    expected_ctc: float | None = None
    notice_period_days: int | None = None
    relocation: bool | None = None
    work_auth: str | None = None


class Profile(BaseModel):
    version: int = 1
    personal: Personal = Field(default_factory=Personal)
    sensitive: Sensitive = Field(default_factory=Sensitive)
    summary: str = ""
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: Skills = Field(default_factory=Skills)
    education: list[Education] = Field(default_factory=list)


# ---- What the LLM is allowed to return. Deliberately has no `sensitive` and no bullet ids. ----

class ExtractedBullet(BaseModel):
    text: str
    skills: list[str] = Field(default_factory=list)


class ExtractedExperience(BaseModel):
    company: str = ""
    role: str = ""
    start: str = ""
    end: str = ""
    bullets: list[ExtractedBullet] = Field(default_factory=list)


class ExtractedProject(BaseModel):
    name: str = ""
    bullets: list[ExtractedBullet] = Field(default_factory=list)


class ExtractedEducation(BaseModel):
    institution: str = ""
    degree: str = ""
    start: str = ""
    end: str = ""


class ResumeExtract(BaseModel):
    personal: Personal = Field(default_factory=Personal)
    summary: str = ""
    experience: list[ExtractedExperience] = Field(default_factory=list)
    projects: list[ExtractedProject] = Field(default_factory=list)
    skills: Skills = Field(default_factory=Skills)
    education: list[ExtractedEducation] = Field(default_factory=list)


# ---------------- Pipeline schemas (LLD section 4) ----------------
from datetime import datetime  # noqa: E402
from typing import Literal  # noqa: E402


class JobRaw(BaseModel):
    url: str
    source: str
    title: str
    company: str
    location: str | None = None
    posted_at: datetime | None = None
    snippet: str | None = None
    exp_text: str | None = None
    jd_text: str | None = None   # full job description when the source already has it (scraper)


class JDExtract(BaseModel):
    title: str = ""
    company: str = ""
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    exp_min: float | None = None
    exp_max: float | None = None
    salary_range: str | None = None
    location: str | None = None
    remote_type: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    apply_type: Literal["easy_apply", "external_ats", "email", "unknown"] = "unknown"
    role_category: Literal["genai_agent", "ml", "backend", "data", "other"] = "other"
    red_flags: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    skills: int = Field(ge=0, le=40)
    seniority: int = Field(ge=0, le=20)
    salary: int = Field(ge=0, le=15)
    role_type: int = Field(ge=0, le=15)
    company: int = Field(ge=0, le=10)
    total: int = 0
    reason: str = ""


class FieldSpec(BaseModel):
    ref: str
    label: str
    type: Literal["text", "textarea", "select", "radio", "checkbox", "file", "date"]
    required: bool = False
    options: list[str] = Field(default_factory=list)


class FieldMap(BaseModel):
    ref: str
    category: Literal["personal", "experience", "sensitive", "custom_question", "file_resume", "consent", "skip"]
    profile_key: str | None = None


class FieldAnswer(BaseModel):
    ref: str
    answer: str | None
    source: Literal["profile", "bank", "llm", "human"]
    confidence: float = 1.0
    needs_review: bool = False


class EmailClass(BaseModel):
    label: Literal["received", "under_review", "shortlisted", "interview_scheduled", "rejected", "other"]
    interview_datetime: str | None = None
