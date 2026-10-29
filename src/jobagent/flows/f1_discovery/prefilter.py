"""Zero-LLM prefilter: age, title blacklist/whitelist, location and experience from the user's preferences."""
import re
from datetime import datetime, timedelta

from jobagent.core.schemas import JobRaw
from jobagent.flows.f0_profile.prefs import SearchPrefs

TITLE_BLACKLIST = ["sales", "bpo", "support", "recruiter", "telecaller", "telesales", "customer care",
                   "business development", "bde", "data entry"]
DEFAULT_WHITELIST = ["ai", "genai", "llm", "ml", "agent", "nlp", "python"]


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])", text.lower()) is not None


def _exp_range(text: str | None):
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", text or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def passes(job: JobRaw, prefs: SearchPrefs, now: datetime) -> tuple[bool, str, list[str]]:
    """Returns (keep, reason, flags).

    Rules, in this order (documented because TC-023 needs a deterministic outcome):
      1. age     - older than prefs.max_age_days is dropped (exactly N days old is kept).
                   Unknown posted date is KEPT and flagged 'posted_date_missing'.
      2. title blacklist - any blacklisted word drops the job, even if a whitelist word is present
                   ("Senior AI Sales Engineer" is rejected: blacklist wins).
      3. title whitelist - at least one keyword must appear (prefs.keywords, else the default list).
      4. location - if prefs.locations is set, the job must be in one of them or remote; unknown location is kept.
      5. experience - if the alert shows an experience range and it does not overlap prefs, drop.
    """
    flags: list[str] = []
    if job.posted_at is None:
        flags.append("posted_date_missing")
    elif now - job.posted_at > timedelta(days=prefs.max_age_days):
        return False, f"older than {prefs.max_age_days} days", flags

    for w in TITLE_BLACKLIST:
        if _has_word(job.title, w):
            return False, f"blacklisted title word '{w}'", flags

    whitelist = prefs.keywords or DEFAULT_WHITELIST
    if not any(_has_word(job.title, w) for w in whitelist):
        return False, "title matches no keyword", flags

    if prefs.locations and job.location:
        loc = job.location.lower()
        if not any(l.lower() in loc for l in prefs.locations) and "remote" not in loc:
            return False, f"location '{job.location}' not in preferences", flags

    rng = _exp_range(job.exp_text)
    if rng and (rng[1] < prefs.exp_min or rng[0] > prefs.exp_max):
        return False, f"experience {job.exp_text} outside {prefs.exp_min}-{prefs.exp_max}", flags
    return True, "ok", flags
