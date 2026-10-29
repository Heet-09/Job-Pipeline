"""Tailoring: reorder bullets by relevance to the JD (always done in code) and optionally rephrase (LLM)."""
import json
from pathlib import Path

from jobagent.core.lexicon import canon, find_terms
from jobagent.core.llm import LLMClient
from jobagent.core.schemas import Bullet, JDExtract, Profile
from jobagent.flows.f0_profile.view import profile_for_llm
from jobagent.flows.f3_resume.models import (
    ResolvedResume, TailoredExperience, TailoredProject, TailoredResume, Violation,
)

PROMPT = (Path(__file__).resolve().parents[4] / "prompts" / "tailor.md").read_text(encoding="utf-8")


def jd_terms(jd: JDExtract) -> set[str]:
    return {canon(s) for s in jd.must_have_skills + jd.nice_to_have}


def relevance(b: Bullet, terms: set[str]) -> int:
    return 2 * len({canon(s) for s in b.skills} & terms) + len(set(find_terms(b.text)) & terms)


def base_draft(profile: Profile) -> TailoredResume:
    """The untouched resume: original order, no rewrites."""
    return TailoredResume(
        summary=profile.summary,
        experience=[TailoredExperience(company=e.company, role=e.role, start=e.start, end=e.end,
                                       bullet_ids=[b.id for b in e.bullets]) for e in profile.experience],
        projects=[TailoredProject(name=p.name, bullet_ids=[b.id for b in p.bullets]) for p in profile.projects],
        skills_order=profile.skills.core + profile.skills.familiar,
    )


def apply_ordering(draft: TailoredResume, profile: Profile, jd: JDExtract) -> TailoredResume:
    """Most JD-relevant bullets/projects/skills first. Stable: ties keep the original order."""
    terms = jd_terms(jd)
    by_id = {b.id: b for e in profile.experience for b in e.bullets} | {b.id: b for p in profile.projects for b in p.bullets}
    out = draft.model_copy(deep=True)

    def order(ids):
        return sorted(ids, key=lambda i: (-relevance(by_id[i], terms), ids.index(i)))

    for e in out.experience:
        e.bullet_ids = order(e.bullet_ids)
    for p in out.projects:
        p.bullet_ids = order(p.bullet_ids)
    out.projects.sort(key=lambda p: -max((relevance(by_id[i], terms) for i in p.bullet_ids), default=0))
    out.skills_order = sorted(out.skills_order, key=lambda s: (canon(s) not in terms, out.skills_order.index(s)))
    return out


def tailor_draft(profile: Profile, jd: JDExtract, llm: LLMClient | None = None,
                 feedback: list[Violation] | None = None, job_id: int | None = None) -> TailoredResume:
    """Without an LLM the draft is reorder-only (it cannot contain a new claim). With an LLM it may rephrase."""
    if llm is None:
        return base_draft(profile)
    user = json.dumps({"profile": profile_for_llm(profile), "job": jd.model_dump(mode="json"),
                       "fix_these_problems": [str(v) for v in feedback or []]})
    return llm.call("large", PROMPT, user, TailoredResume, flow="tailor", job_id=job_id)


def resolve(draft: TailoredResume, profile: Profile) -> ResolvedResume:
    """Turn ids + rewrites into final text."""
    text = {b.id: b.text for e in profile.experience for b in e.bullets} | {b.id: b.text for p in profile.projects for b in p.bullets}
    p = profile.personal
    contact = " | ".join(x for x in [p.email, p.phone, p.location, *p.links.values()] if x)
    exp = [(f"{e.role}, {e.company}", f"{e.start or ''} - {e.end or ''}".strip(" -"),
            [e.rewrites.get(i, text[i]) for i in e.bullet_ids]) for e in draft.experience]
    proj = [(pr.name, [pr.rewrites.get(i, text[i]) for i in pr.bullet_ids]) for pr in draft.projects]
    edu = [f"{ed.degree}, {ed.institution} ({ed.start or ''}-{ed.end or ''})".replace("(-)", "").strip() for ed in profile.education]
    return ResolvedResume(name=p.name, contact=contact, summary=draft.summary or profile.summary, skills=draft.skills_order,
                          experience=exp, projects=proj, education=edu, fallback=draft.fallback)
