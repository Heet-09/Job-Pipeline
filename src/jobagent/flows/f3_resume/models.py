from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class TailoredExperience(BaseModel):
    company: str
    role: str = ""
    start: str | None = None
    end: str | None = None
    bullet_ids: list[str] = Field(default_factory=list)
    rewrites: dict[str, str] = Field(default_factory=dict)


class TailoredProject(BaseModel):
    name: str
    bullet_ids: list[str] = Field(default_factory=list)
    rewrites: dict[str, str] = Field(default_factory=dict)


class TailoredResume(BaseModel):
    summary: str = ""
    experience: list[TailoredExperience] = Field(default_factory=list)
    projects: list[TailoredProject] = Field(default_factory=list)
    skills_order: list[str] = Field(default_factory=list)
    fallback: bool = False  # True when the validator failed twice and the base resume was used


class ClaimCheck(BaseModel):
    adds_claim: bool = False
    which: str = ""


@dataclass
class Violation:
    code: str
    detail: str

    def __str__(self):
        return f"{self.code}: {self.detail}"


@dataclass
class ResolvedResume:
    """Final text of the resume, ready to render or diff."""
    name: str
    contact: str
    summary: str
    skills: list[str]
    experience: list[tuple[str, str, list[str]]] = field(default_factory=list)   # (heading, dates, bullets)
    projects: list[tuple[str, list[str]]] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    fallback: bool = False
