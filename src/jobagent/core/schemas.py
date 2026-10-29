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
