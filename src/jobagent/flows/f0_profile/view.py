"""Read-only helpers over a Profile. profile_for_llm() is the ONLY shape of profile data sent to an LLM."""
from datetime import datetime

from jobagent.core.schemas import Profile


def profile_for_llm(profile: Profile) -> dict:
    """Profile without the `sensitive` section and without contact details (SAF-02)."""
    d = profile.model_dump(mode="json", exclude={"sensitive"})
    d["personal"] = {"name": d["personal"]["name"]}
    return d


def all_skills(profile: Profile) -> set[str]:
    skills = {s.lower() for s in profile.skills.core + profile.skills.familiar}
    for e in profile.experience:
        for b in e.bullets:
            skills |= {s.lower() for s in b.skills}
    for p in profile.projects:
        for b in p.bullets:
            skills |= {s.lower() for s in b.skills}
    return skills


def _month(s: str | None, now: datetime) -> int | None:
    if not s:
        return None
    if s == "present":
        return now.year * 12 + now.month
    parts = s.split("-")
    return int(parts[0]) * 12 + (int(parts[1]) if len(parts) > 1 else 1)


def total_years(profile: Profile, now: datetime) -> float:
    months = 0
    for e in profile.experience:
        a, b = _month(e.start, now), _month(e.end, now)
        if a is not None and b is not None and b >= a:
            months += b - a
    return round(months / 12, 1)
