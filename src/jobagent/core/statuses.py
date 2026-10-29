"""Job status machine (PLT-04). Every status change must go through check_transition()."""

DISCOVERED = "DISCOVERED"
JD_PARTIAL = "JD_PARTIAL"
EXTRACTED = "EXTRACTED"
EXTRACTION_FAILED = "EXTRACTION_FAILED"
SCORED = "SCORED"          # Apply bucket
MAYBE = "MAYBE"
REJECTED = "REJECTED"
SKIPPED = "SKIPPED"
TAILORED = "TAILORED"
FILLED = "FILLED"
NEEDS_HUMAN = "NEEDS_HUMAN"
APPROVED = "APPROVED"
SUBMITTED = "SUBMITTED"
SUBMIT_UNCERTAIN = "SUBMIT_UNCERTAIN"
FAILED = "FAILED"

_SCORING = {SCORED, MAYBE, REJECTED, SKIPPED, FAILED}

TRANSITIONS: dict[str, set[str]] = {
    DISCOVERED: {EXTRACTED, JD_PARTIAL, EXTRACTION_FAILED, SKIPPED, FAILED},
    JD_PARTIAL: set(_SCORING),
    EXTRACTED: set(_SCORING),
    EXTRACTION_FAILED: {DISCOVERED, SKIPPED, FAILED},
    SCORED: {TAILORED, SKIPPED, NEEDS_HUMAN, FAILED},
    MAYBE: {SCORED, SKIPPED, FAILED},          # MAYBE -> SCORED only via manual apply (SCR-05)
    REJECTED: {SCORED, SKIPPED},               # REJECTED -> SCORED only via manual apply
    SKIPPED: set(),
    TAILORED: {FILLED, NEEDS_HUMAN, SKIPPED, FAILED},
    FILLED: {APPROVED, SKIPPED, NEEDS_HUMAN, FAILED},
    NEEDS_HUMAN: {TAILORED, FILLED, SKIPPED, FAILED},
    APPROVED: {SUBMITTED, SUBMIT_UNCERTAIN, NEEDS_HUMAN, FAILED},
    SUBMIT_UNCERTAIN: {SUBMITTED},             # only after a human confirms
    SUBMITTED: set(),
    FAILED: set(),
}


class InvalidTransition(Exception):
    pass


def check_transition(old: str, new: str) -> None:
    if old not in TRANSITIONS:
        raise InvalidTransition(f"unknown status {old!r}")
    if new not in TRANSITIONS[old]:
        raise InvalidTransition(f"illegal transition {old} -> {new}")
