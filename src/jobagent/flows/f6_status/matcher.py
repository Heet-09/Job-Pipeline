"""Match a reply email to one of our applications (LLD F6). Ambiguity goes to a human, never a guess."""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

_NOISE = re.compile(r"\b(careers?|recruit(?:ing|ment|er|ers)?|talent|hr|jobs?|team|no-?reply|notifications?|hiring|acquisition|via|greenhouse|lever|workday|mail)\b", re.I)
_GENERIC_DOMAINS = ("greenhouse", "lever.co", "workday", "ashby", "smartrecruiters", "gmail.com", "outlook.com", "icims", "myworkday", "linkedin", "naukri")


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def company_guess(sender: str, sender_domain: str) -> str:
    name = sender.split("<")[0].strip().strip('"')
    name = re.sub(r"\s+", " ", _NOISE.sub(" ", name)).strip()
    if name:
        return name
    return sender_domain.split(".")[0] if sender_domain else ""


def domain_match(sender_domain: str, company: str) -> float:
    if not sender_domain or any(g in sender_domain for g in _GENERIC_DOMAINS):
        return 0.0
    label = sender_domain.rsplit(".", 1)[0].split(".")[-1] if "." in sender_domain else sender_domain
    return 100.0 if fuzz.partial_ratio(_squash(company), _squash(label)) >= 85 and len(_squash(label)) >= 3 else 0.0


def score_email(subject: str, sender: str, sender_domain: str, company: str, title: str) -> float:
    guess = company_guess(sender, sender_domain)
    return (0.5 * fuzz.token_set_ratio(guess, company)
            + 0.3 * fuzz.partial_ratio(subject.lower(), title.lower())
            + 0.2 * domain_match(sender_domain, company))


@dataclass
class Match:
    app: dict | None
    best: float
    margin: float
    reason: str


def match(email, apps: list[dict], min_score: float = 80, min_margin: float = 10) -> Match:
    if not apps:
        return Match(None, 0, 0, "no open applications")
    scored = sorted(((score_email(email.subject, email.sender, email.sender_domain, a["company"], a["title"]), a) for a in apps),
                    key=lambda x: -x[0])
    best, app = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    margin = best - second
    if len(scored) > 1 and margin <= min_margin:
        return Match(None, best, margin, f"ambiguous: margin {margin:.0f} <= {min_margin:.0f} between two applications")
    if best <= min_score:
        return Match(None, best, margin, f"best match score {best:.0f} <= {min_score:.0f}")
    return Match(app, best, margin, "ok")
