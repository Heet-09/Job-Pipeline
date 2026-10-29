"""JD -> JDExtract. LLM when available; a rule-based extractor otherwise. Both pass through the same guards."""
import re
from pathlib import Path

from jobagent.core.lexicon import find_terms
from jobagent.core.llm import LLMClient
from jobagent.core.schemas import JDExtract

PROMPT = (Path(__file__).resolve().parents[4] / "prompts" / "jd_extract.md").read_text(encoding="utf-8")

_EXP = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", re.I)
_EXP_MIN = re.compile(r"(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)|(?:minimum|at least)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", re.I)
_SALARY = re.compile(r"(?:₹|rs\.?|inr|usd|\$)?\s*\d[\d,.]*\s*(?:-|to|–)\s*\d[\d,.]*\s*(?:lpa|lakhs?|lacs?|per annum|k|ctc)\b[^\n.]*", re.I)


def regex_experience(text: str) -> tuple[float | None, float | None]:
    m = _EXP.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _EXP_MIN.search(text)
    if m:
        return float(m.group(1) or m.group(2)), None
    return None, None


def regex_salary(text: str) -> str | None:
    m = _SALARY.search(text)
    return m.group(0).strip() if m else None


def _category(title: str, text: str) -> str:
    t = f"{title} {text[:600]}".lower()
    if re.search(r"genai|generative ai|llm|agent|langchain|langgraph|rag\b", t):
        return "genai_agent"
    if re.search(r"machine learning|\bml\b|deep learning|nlp|data scientist", t):
        return "ml"
    if re.search(r"backend|back-end|api|fastapi|django|spring", t):
        return "backend"
    if re.search(r"data engineer|analyst|etl|warehouse|bi developer", t):
        return "data"
    return "other"


def rule_extract(title: str, company: str, location: str | None, text: str) -> JDExtract:
    lo, hi = regex_experience(text)
    skills = find_terms(text)
    remote = "remote" if re.search(r"\bremote\b|work from home", text, re.I) else "hybrid" if re.search(r"\bhybrid\b", text, re.I) else "onsite"
    return JDExtract(title=title, company=company, must_have_skills=skills, exp_min=lo, exp_max=hi,
                     salary_range=regex_salary(text), location=location, remote_type=remote,
                     role_category=_category(title, text))


def sanitize(jd: JDExtract, text: str) -> JDExtract:
    """Drop anything the model claims that the JD text does not support (no hallucinated skills or salary)."""
    low = text.lower()
    jd.must_have_skills = [s for s in jd.must_have_skills if s.lower() in low]
    jd.nice_to_have = [s for s in jd.nice_to_have if s.lower() in low]
    if jd.salary_range:
        nums = re.findall(r"\d[\d,.]*", jd.salary_range)
        if not nums or any(n.replace(",", "") not in low.replace(",", "") for n in nums):
            jd.salary_range = None
    if jd.exp_min is None and jd.exp_max is None:
        jd.exp_min, jd.exp_max = regex_experience(text)
    return jd


def extract_jd(text: str, title: str, company: str, location: str | None, llm: LLMClient | None = None,
               job_id: int | None = None) -> JDExtract:
    """Raises ExtractionFailed when the LLM output is invalid twice (caller sets EXTRACTION_FAILED)."""
    if llm is None:
        jd = rule_extract(title, company, location, text)
    else:
        jd = llm.call("small", PROMPT, text, JDExtract, flow="extract", job_id=job_id)
        jd.title, jd.company = jd.title or title, jd.company or company
        jd.location = jd.location or location
    return sanitize(jd, text)
