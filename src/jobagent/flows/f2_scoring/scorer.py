"""Scoring (0-100). The total is ALWAYS recomputed in code from the components; the LLM's total is never trusted."""
import json
import re
from datetime import datetime
from pathlib import Path

from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.llm import LLMClient
from jobagent.core.schemas import JDExtract, Profile, ScoreResult
from jobagent.flows.f0_profile.view import all_skills, profile_for_llm, total_years

PROMPT = (Path(__file__).resolve().parents[4] / "prompts" / "score.md").read_text(encoding="utf-8")
NEUTRAL_SALARY = 8
LOW_VALUE_TITLE = re.compile(r"\b(support|qa|quality assurance|tester|testing|data entry|bpo|helpdesk|help desk|customer|operations executive)\b", re.I)
ROLE_POINTS = {"genai_agent": 15, "ml": 11, "backend": 7, "data": 6, "other": 2}
LOW_ROLE_CAP = 3


def parse_salary_lpa(s: str | None) -> tuple[float, float] | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)", s or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def rule_components(jd: JDExtract, profile: Profile, now: datetime) -> ScoreResult:
    have = all_skills(profile)
    core = {s.lower() for s in profile.skills.core}
    must = [s.lower() for s in jd.must_have_skills]
    if must:
        pts = sum(1.0 if s in core else 0.7 if s in have else 0.0 for s in must)
        skills = round(40 * pts / len(must))
    else:
        skills = 20

    years = total_years(profile, now)
    if jd.exp_min is None and jd.exp_max is None:
        seniority = 10
    else:
        lo, hi = jd.exp_min or 0, jd.exp_max if jd.exp_max is not None else 99
        seniority = 20 if lo <= years <= hi else max(0, round(20 - 5 * (lo - years))) if years < lo else max(8, round(20 - 2 * (years - hi)))

    sal = parse_salary_lpa(jd.salary_range)
    expected = profile.sensitive.expected_ctc  # used only in local code, never sent to an LLM
    if not sal or expected is None:
        salary = NEUTRAL_SALARY
    else:
        salary = 15 if sal[1] >= expected else 10 if sal[1] >= 0.8 * expected else 4

    role = ROLE_POINTS.get(jd.role_category, 2)
    company = max(0, 5 - 2 * len(jd.red_flags))
    return ScoreResult(skills=skills, seniority=seniority, salary=salary, role_type=role, company=company)


def llm_components(llm: LLMClient, jd: JDExtract, profile: Profile, job_id: int | None = None) -> ScoreResult:
    user = json.dumps({"profile": profile_for_llm(profile), "jd": jd.model_dump(mode="json")})
    return llm.call("small", PROMPT, user, ScoreResult, flow="score", job_id=job_id)


def finalize(sr: ScoreResult, jd: JDExtract, title: str, now_reason: str | None = None) -> ScoreResult:
    """Code-side guards applied to ANY scorer output."""
    sr = sr.model_copy()
    if LOW_VALUE_TITLE.search(title or "") or LOW_VALUE_TITLE.search(jd.title or ""):
        sr.role_type = min(sr.role_type, LOW_ROLE_CAP)  # an "AI" label on a support job is still a support job
    if not parse_salary_lpa(jd.salary_range) and not jd.salary_range:
        sr.salary = NEUTRAL_SALARY                        # missing salary is neutral, not good or bad
    sr.total = sr.skills + sr.seniority + sr.salary + sr.role_type + sr.company
    reason = (sr.reason or now_reason or "").strip()
    sr.reason = "\n".join(reason.splitlines()[:2])
    return sr


def reason_text(sr: ScoreResult, jd: JDExtract) -> str:
    return (f"Skills {sr.skills}/40, seniority {sr.seniority}/20, role fit {sr.role_type}/15 ({jd.role_category}).\n"
            f"Salary {sr.salary}/15{' (not stated, neutral)' if not jd.salary_range else ''}, company {sr.company}/10.")


def score(jd: JDExtract, title: str, profile: Profile, now: datetime, llm: LLMClient | None = None,
          job_id: int | None = None) -> ScoreResult:
    sr = llm_components(llm, jd, profile, job_id) if llm else rule_components(jd, profile, now)
    sr = finalize(sr, jd, title)
    if not sr.reason:
        sr.reason = reason_text(sr, jd)
    return sr


def bucket(total: int, settings: Settings) -> str:
    if total >= settings.score_go:
        return st.SCORED
    if total >= settings.score_maybe:
        return st.MAYBE
    return st.REJECTED
