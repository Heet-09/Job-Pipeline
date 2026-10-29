"""PRF-02: sensitive details are typed in by the user only. Never filled from a resume or an LLM."""
import json
from pathlib import Path

from jobagent.core.schemas import Profile, Sensitive
from jobagent.core.logging import get_logger, register_secret
from jobagent.flows.f0_profile.loader import DEFAULT_PROFILE_PATH, load_profile, save_profile

log = get_logger("jobagent.profile")

SENSITIVE_KEYS = ["current_ctc", "expected_ctc", "notice_period_days", "relocation", "work_auth"]


class MissingSensitiveError(Exception):
    pass


def missing_sensitive(profile: Profile) -> list[str]:
    return [k for k in SENSITIVE_KEYS if getattr(profile.sensitive, k) is None]


def startup_check(profile: Profile, strict: bool = False) -> list[str]:
    """Fail fast (strict) or warn when sensitive fields are empty. Those forms will need a human."""
    missing = missing_sensitive(profile)
    msgs = [f"sensitive.{k} is not set - forms asking for it will need a human" for k in missing]
    if missing and strict:
        raise MissingSensitiveError("; ".join(msgs))
    for m in msgs:
        log.warning(m)
    return msgs


def set_sensitive(path: Path = DEFAULT_PROFILE_PATH, **values) -> Profile:
    """The only supported way to write sensitive.* - used by the user (CLI), validated by type."""
    unknown = set(values) - set(SENSITIVE_KEYS)
    if unknown:
        raise ValueError(f"unknown sensitive field(s): {sorted(unknown)}")
    profile = load_profile(path)
    data = profile.sensitive.model_dump()
    data.update(values)
    profile.sensitive = Sensitive(**data)  # pydantic validates types
    save_profile(profile, path)
    for v in values.values():
        if v is not None:
            register_secret(v)
    return profile


def register_profile_secrets(profile: Profile) -> None:
    """Make the logger mask this profile's sensitive values wherever they might appear."""
    for v in sensitive_values(profile):
        register_secret(v)


def sensitive_values(profile: Profile) -> list:
    return [v for v in profile.sensitive.model_dump().values() if v is not None]
