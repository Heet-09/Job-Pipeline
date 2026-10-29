"""tailor -> validate -> (retry once) -> fallback to the base resume. A plain loop; the graph has only one cycle."""
from jobagent.core.llm import LLMClient, LLMError
from jobagent.core.logging import get_logger
from jobagent.core.schemas import JDExtract, Profile
from jobagent.flows.f3_resume.models import TailoredResume, Violation
from jobagent.flows.f3_resume.tailor import apply_ordering, base_draft, tailor_draft
from jobagent.flows.f3_resume.validator import Checker, validate

log = get_logger("jobagent.tailor")
MAX_ATTEMPTS = 2


def run_tailor_loop(profile: Profile, jd: JDExtract, llm: LLMClient | None = None, checker: Checker | None = None,
                    job_id: int | None = None, max_attempts: int = MAX_ATTEMPTS) -> tuple[TailoredResume, list[Violation]]:
    """Returns (resume, last_violations). If every attempt fails validation the BASE resume is returned with fallback=True."""
    feedback: list[Violation] = []
    for attempt in range(1, max_attempts + 1):
        try:
            draft = tailor_draft(profile, jd, llm, feedback, job_id)
        except LLMError as e:
            feedback = [Violation("llm_error", str(e))]
            log.warning("tailor attempt %d failed: %s", attempt, e)
            continue
        feedback = validate(draft, profile, checker)
        if not feedback:
            return apply_ordering(draft, profile, jd), []
        log.warning("tailor attempt %d rejected: %s", attempt, "; ".join(map(str, feedback)))
    fallback = base_draft(profile)
    fallback.fallback = True
    return fallback, feedback
