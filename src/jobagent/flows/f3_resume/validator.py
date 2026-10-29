"""Claim verification (RES-03, SAF-03). Rule-based first, optional LLM second pass.

A draft is rejected if it contains ANY claim that cannot be traced to the profile:
new numbers, new tools/skills, new proper nouns, changed company/role/dates, unknown bullet ids,
or skills outside the profile.
"""
import re
from typing import Callable

from jobagent.core.lexicon import TECH_TERMS, canon
from jobagent.core.llm import LLMClient
from jobagent.core.schemas import Profile
from jobagent.flows.f0_profile.view import all_skills
from jobagent.flows.f3_resume.models import ClaimCheck, TailoredResume, Violation

_NUM = re.compile(r"\d+(?:[.,]\d+)*\s*%?")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#./\-]*")
_TECH = {canon(t) for t in TECH_TERMS}

Checker = Callable[[list[tuple[str, str, str]]], list[Violation]]


def numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", n) for n in _NUM.findall(text)}


def words(text: str) -> set[str]:
    return {w.lower().strip(".-/") for w in _WORD.findall(text)}


def _corpus(profile: Profile) -> str:
    parts = [profile.summary, profile.personal.name, *profile.skills.core, *profile.skills.familiar]
    for e in profile.experience:
        parts += [e.company, e.role, *[b.text for b in e.bullets], *[s for b in e.bullets for s in b.skills]]
    for p in profile.projects:
        parts += [p.name, *[b.text for b in p.bullets], *[s for b in p.bullets for s in b.skills]]
    for ed in profile.education:
        parts += [ed.institution, ed.degree]
    return "\n".join(parts)


def _proper_like(text: str) -> set[str]:
    """Capitalised mid-sentence words, ALLCAPS and camelCase tokens - the usual shape of a tool or company name."""
    out = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        ws = _WORD.findall(sentence)
        for i, w in enumerate(ws):
            core = w.strip(".-/")
            if len(core) < 2:
                continue
            if (i > 0 and core[0].isupper()) or (core.isupper() and len(core) >= 2) or re.search(r"[a-z][A-Z]", core):
                out.add(core.lower())
    return out


def _new_claims(new_text: str, base_text: str, allowed_skills: set[str], corpus_words: set[str], label: str) -> list[Violation]:
    v: list[Violation] = []
    extra_nums = numbers(new_text) - numbers(base_text)
    if extra_nums:
        v.append(Violation("new_number", f"{label}: number(s) {sorted(extra_nums)} not in the original"))
    base_words = words(base_text)
    for w in sorted(words(new_text) - base_words):
        c = canon(w)
        if c in _TECH and c not in allowed_skills and w not in corpus_words:
            v.append(Violation("new_skill", f"{label}: '{w}' is not a skill in the profile"))
    for w in sorted(_proper_like(new_text) - base_words - corpus_words):
        if canon(w) not in allowed_skills and not any(x.code == "new_skill" and f"'{w}'" in x.detail for x in v):
            v.append(Violation("new_entity", f"{label}: '{w}' does not appear anywhere in the profile"))
    return v


def validate(draft: TailoredResume, profile: Profile, checker: Checker | None = None) -> list[Violation]:
    v: list[Violation] = []
    allowed = {canon(s) for s in all_skills(profile)}
    corpus = _corpus(profile)
    corpus_words = words(corpus)
    bullets = {}
    for e in profile.experience:
        for b in e.bullets:
            bullets[b.id] = (e.company, b.text)
    for p in profile.projects:
        for b in p.bullets:
            bullets[b.id] = (p.name, b.text)

    def check_ids(owner: str, ids: list[str], rewrites: dict[str, str]):
        if len(set(ids)) != len(ids):
            v.append(Violation("duplicate_bullet", f"{owner}: bullet ids repeated"))
        for bid in list(ids) + list(rewrites):
            if bid not in bullets:
                v.append(Violation("unknown_bullet", f"{owner}: bullet id '{bid}' is not in the profile"))
            elif bullets[bid][0] != owner:
                v.append(Violation("wrong_owner", f"{owner}: bullet '{bid}' belongs to '{bullets[bid][0]}'"))
        for bid, text in rewrites.items():
            if bid in bullets:
                v.extend(_new_claims(text, bullets[bid][1], allowed, corpus_words, f"bullet {bid}"))

    real = {e.company: e for e in profile.experience}
    for e in draft.experience:
        orig = real.get(e.company)
        if orig is None:
            v.append(Violation("company_changed", f"company '{e.company}' is not in the profile"))
            continue
        for fld in ("role", "start", "end"):
            if getattr(e, fld) != getattr(orig, fld):
                v.append(Violation(f"{fld}_changed", f"{e.company}: {fld} '{getattr(e, fld)}' != profile '{getattr(orig, fld)}'"))
        check_ids(e.company, e.bullet_ids, e.rewrites)

    real_projects = {p.name for p in profile.projects}
    for p in draft.projects:
        if p.name not in real_projects:
            v.append(Violation("project_changed", f"project '{p.name}' is not in the profile"))
            continue
        check_ids(p.name, p.bullet_ids, p.rewrites)

    for s in draft.skills_order:
        if canon(s) not in {canon(x) for x in profile.skills.core + profile.skills.familiar}:
            v.append(Violation("skill_not_in_profile", f"skills_order contains '{s}' which the profile does not list"))

    if draft.summary:
        v += _new_claims(draft.summary, profile.summary, allowed, corpus_words, "summary")
        extra = numbers(draft.summary) - numbers(corpus)
        if extra and not any(x.code == "new_number" and x.detail.startswith("summary") for x in v):
            v.append(Violation("new_number", f"summary: number(s) {sorted(extra)} not in the profile"))

    if checker and not v:  # LLM second pass only on drafts the rules accepted
        pairs = [(bid, bullets[bid][1], text) for e in draft.experience + draft.projects for bid, text in e.rewrites.items() if bid in bullets]
        v += checker(pairs)
    return v


class LLMClaimChecker:
    """LLD step 4: ask a small model 'does this rewrite add a claim that is not in the original?'"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def __call__(self, pairs):
        out = []
        for bid, original, rewrite in pairs:
            res = self.llm.call("small", "Does the REWRITE add any claim not in the ORIGINAL? Reply JSON {\"adds_claim\": bool, \"which\": str}.",
                                f"ORIGINAL: {original}\nREWRITE: {rewrite}", ClaimCheck, flow="claim_check")
            if res.adds_claim:
                out.append(Violation("llm_claim", f"bullet {bid}: {res.which}"))
        return out
