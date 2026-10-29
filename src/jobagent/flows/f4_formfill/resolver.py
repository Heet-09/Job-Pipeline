"""Answer priority chain (LLD F4): profile -> Answer Bank -> LLM draft. Sensitive fields come from the profile ONLY."""
import difflib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from jobagent.core.llm import LLMClient, LLMError
from jobagent.core.schemas import FieldAnswer, FieldMap, FieldSpec, JDExtract, Profile
from jobagent.flows.f0_profile.view import profile_for_llm, total_years
from jobagent.flows.f4_formfill.answer_bank import AnswerBank

PROMPT = (Path(__file__).resolve().parents[4] / "prompts" / "form_answer.md").read_text(encoding="utf-8")
MAX_WORDS = 80


class DraftAnswer(BaseModel):
    answer: str = ""


@dataclass
class ResolveContext:
    profile: Profile
    now: datetime
    bank: AnswerBank | None = None
    llm: LLMClient | None = None
    jd: JDExtract | None = None
    resume_path: str | None = None
    job_id: int | None = None


def _fmt(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    return str(v)


def profile_lookup(profile: Profile, key: str, now: datetime) -> str | None:
    parts = key.split(".")
    if key == "experience.total_years":
        yrs = total_years(profile, now)
        return _fmt(yrs) if profile.experience else None
    if parts[0] == "personal":
        p = profile.personal
        if parts[1] == "first_name":
            return p.name.split()[0] if p.name.strip() else None
        if parts[1] == "last_name":
            return " ".join(p.name.split()[1:]) or None
        if parts[1] == "links":
            return p.links.get(parts[2]) or None
        return getattr(p, parts[1], None) or None
    if parts[0] == "sensitive":
        return _fmt(getattr(profile.sensitive, parts[1], None))
    return None


def choose_option(value: str, options: list[str]) -> str | None:
    """Pick the option that best matches value. None if nothing is close (never invent an option)."""
    if not options:
        return value
    v = value.strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    if re.fullmatch(r"\d+(\.\d+)?", v):
        for o in options:
            if re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.])", o):
                return o
    for o in options:
        if v and (v in o.strip().lower() or o.strip().lower() in v):
            return o
    close = difflib.get_close_matches(v, [o.lower() for o in options], n=1, cutoff=0.6)
    return next((o for o in options if o.lower() == close[0]), None) if close else None


def truncate_words(text: str, limit: int = MAX_WORDS) -> str:
    words = text.split()
    return text.strip() if len(words) <= limit else " ".join(words[:limit]).rstrip(",;:") + "..."


def _draft(spec: FieldSpec, ctx: ResolveContext) -> str | None:
    if ctx.llm is None:
        return None
    user = json.dumps({
        "question": spec.label, "field_type": spec.type, "options": spec.options,
        "candidate": profile_for_llm(ctx.profile),
        "job": ctx.jd.model_dump(mode="json", include={"title", "company", "must_have_skills"}) if ctx.jd else {},
    })
    try:
        text = ctx.llm.call("large", PROMPT, user, DraftAnswer, flow="form_answer", job_id=ctx.job_id).answer.strip()
    except LLMError:
        return None
    if not text:
        return None
    return choose_option(text, spec.options) if spec.options else truncate_words(text)


def resolve(spec: FieldSpec, fmap: FieldMap, ctx: ResolveContext) -> FieldAnswer:
    ref = spec.ref
    if fmap.category == "skip":
        return FieldAnswer(ref=ref, answer=None, source="profile", confidence=1.0, needs_review=False)
    if fmap.category == "file_resume":
        return FieldAnswer(ref=ref, answer=ctx.resume_path, source="profile", confidence=1.0, needs_review=ctx.resume_path is None)
    if fmap.category == "consent":
        return FieldAnswer(ref=ref, answer="Yes", source="profile", confidence=1.0, needs_review=True)

    if fmap.category in ("personal", "experience", "sensitive") and fmap.profile_key:
        v = profile_lookup(ctx.profile, fmap.profile_key, ctx.now)
        if v is not None and spec.options:
            v = choose_option(v, spec.options)
        # a missing value is never guessed: answer stays None and the job goes to NEEDS_HUMAN
        return FieldAnswer(ref=ref, answer=v, source="profile", confidence=1.0 if v is not None else 0.0, needs_review=v is None)

    if ctx.bank and (hit := ctx.bank.lookup(spec.label)):
        ans = choose_option(hit.answer, spec.options) if spec.options else hit.answer
        if ans is not None:
            ctx.bank.mark_used(hit.id)
            return FieldAnswer(ref=ref, answer=ans, source="bank", confidence=round(hit.sim, 3), needs_review=not hit.human_approved)

    draft = _draft(spec, ctx)
    return FieldAnswer(ref=ref, answer=draft, source="llm", confidence=0.5 if draft else 0.0, needs_review=True)
