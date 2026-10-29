"""PRF-01: build data/profile.json from a resume PDF."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from jobagent.core.schemas import (
    Bullet, Education, Experience, Profile, Project, ResumeExtract, Sensitive,
)
from jobagent.flows.f0_profile.extractor import ResumeExtractor
from jobagent.flows.f0_profile.loader import DEFAULT_PROFILE_PATH, load_profile, save_profile

MIN_TEXT_CHARS = 100  # fewer extractable characters than this => scanned/image-only PDF

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_PRESENT = {"present", "current", "currently", "now", "till date", "to date", "ongoing"}


class ProfileBuildError(Exception):
    """Raised when no usable profile can be built. Nothing is written to disk."""


@dataclass
class BuildResult:
    profile: Profile
    warnings: list[str] = field(default_factory=list)
    path: Path | None = None


def extract_text(pdf_path: Path) -> str:
    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            raise ProfileBuildError(f"{pdf_path}: PDF is password protected")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except ProfileBuildError:
        raise
    except FileNotFoundError:
        raise ProfileBuildError(f"{pdf_path}: file not found")
    except Exception as e:
        raise ProfileBuildError(f"{pdf_path}: could not read PDF (corrupt or not a PDF): {e}") from e
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise ProfileBuildError(
            f"{pdf_path}: no readable text found - this looks like a scanned/image-only PDF. "
            "Please provide a text-based PDF.")
    return text


def normalize_date(raw: str) -> str | None:
    """'Jan 2022' / '01/2022' / '2022-01' -> 'YYYY-MM'; 'Present' -> 'present'; bare year -> 'YYYY'. None if unparseable."""
    s = (raw or "").strip().lower().replace(".", "")
    if not s:
        return None
    if s in _PRESENT:
        return "present"
    m = re.fullmatch(r"([a-z]{3})[a-z]*[ ,'-]*(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"
    m = re.fullmatch(r"(\d{1,2})[/-](\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{4})[/-](\d{1,2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    if re.fullmatch(r"\d{4}", s):
        return s
    return None


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _assemble(ex: ResumeExtract, text: str, warnings: list[str]) -> Profile:
    squashed = _squash(text)

    def date(raw: str, where: str) -> str | None:
        if not raw.strip():
            return None
        d = normalize_date(raw)
        if d is None:
            warnings.append(f"Could not parse date '{raw}' for {where}; left empty.")
        return d

    personal = ex.personal.model_copy()
    if personal.email and personal.email.lower() not in text.lower():
        warnings.append("Email returned by the extractor is not present in the resume text; dropped.")
        personal.email = ""

    experience = []
    for i, e in enumerate(ex.experience, 1):
        if not e.company.strip():
            continue
        if _squash(e.company) not in squashed:
            warnings.append(f"Company '{e.company}' not found in resume text; entry dropped (possible hallucination).")
            continue
        label = f"{e.company} ({e.role})"
        experience.append(Experience(
            company=e.company.strip(), role=e.role.strip(),
            start=date(e.start, f"{label} start"), end=date(e.end, f"{label} end"),
            bullets=[Bullet(id=f"e{i}b{j}", text=b.text.strip(), skills=b.skills)
                     for j, b in enumerate(e.bullets, 1) if b.text.strip()],
        ))

    projects = []
    for i, p in enumerate(ex.projects, 1):
        if p.name.strip():
            projects.append(Project(
                name=p.name.strip(),
                bullets=[Bullet(id=f"p{i}b{j}", text=b.text.strip(), skills=b.skills)
                         for j, b in enumerate(p.bullets, 1) if b.text.strip()],
            ))

    education = [Education(institution=e.institution.strip(), degree=e.degree.strip(),
                           start=date(e.start, f"{e.institution} start"), end=date(e.end, f"{e.institution} end"))
                 for e in ex.education if e.institution.strip()]

    if not projects:
        warnings.append("No projects section found in the resume; profile built without projects.")
    if not experience:
        warnings.append("No work experience found in the resume.")

    return Profile(
        personal=personal,
        sensitive=Sensitive(),  # PRF-02: always empty here, whatever the resume or LLM says
        summary=ex.summary.strip(), experience=experience, projects=projects,
        skills=ex.skills, education=education,
    )


def build_profile(pdf_path: Path, extractor: ResumeExtractor, out_path: Path = DEFAULT_PROFILE_PATH,
                  *, dry_run: bool = False) -> BuildResult:
    pdf_path, out_path = Path(pdf_path), Path(out_path)
    text = extract_text(pdf_path)
    extract = extractor.extract(text)

    warnings: list[str] = []
    profile = _assemble(extract, text, warnings)

    if not (profile.experience or profile.projects or profile.education or profile.skills.core or profile.skills.familiar):
        raise ProfileBuildError(f"{pdf_path}: nothing usable could be extracted; profile not saved.")

    if out_path.exists():  # rebuilding must never wipe what the user typed in by hand
        try:
            existing = load_profile(out_path)
            profile.sensitive = existing.sensitive
            profile.version = existing.version
        except Exception:
            warnings.append(f"Existing {out_path} is unreadable; sensitive details were not carried over.")

    if not dry_run:
        save_profile(profile, out_path)
    return BuildResult(profile=profile, warnings=warnings, path=None if dry_run else out_path)
