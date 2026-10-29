"""Playwright actions: fill one field, find the 'next' button, move to the next page."""
import time

from jobagent.core.schemas import FieldSpec
from jobagent.flows.f4_formfill.guards import NEXT_RE, control_text, is_submit_text, safe_click
from jobagent.flows.f4_formfill.snapshot import PageSnapshot, take_snapshot

TRUTHY = {"yes", "true", "1", "on", "y", "checked"}
_BUTTONS = "button, input[type=submit], input[type=button], a[role=button], [role=button]"


def fill_field(page, spec: FieldSpec, answer: str, snap: PageSnapshot) -> None:
    tok = snap.tokens[spec.ref]
    if spec.type == "radio":
        idx = next(i for i, o in enumerate(spec.options) if o == answer)
        page.locator(f'[data-jaref="{tok}#{idx}"]').check()
        return
    loc = page.locator(f'[data-jaref="{tok}"]')
    if spec.type == "select":
        loc.select_option(label=answer)
    elif spec.type == "checkbox":
        loc.set_checked(answer.strip().lower() in TRUTHY)
    elif spec.type == "file":
        loc.set_input_files(answer)
    else:  # text, textarea, date
        loc.fill(answer)


def _visible_buttons(page):
    return [b for b in page.locator(_BUTTONS).all() if b.is_visible()]


def find_next_button(page):
    """Returns the 'next page' control, or None when the page only offers a final submit (or nothing)."""
    for b in _visible_buttons(page):
        text = control_text(b)
        if NEXT_RE.search(text) and not is_submit_text(text):
            return b
    return None


def submit_button(page):
    for b in _visible_buttons(page):
        if is_submit_text(control_text(b)):
            return b
    return None


def advance_page(page, button, before_refs: set[str], timeout_s: float = 3.0) -> bool:
    """Click 'next' (never a submit) and wait for the visible fields to change. False if the page did not move on."""
    safe_click(button)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        page.wait_for_timeout(100)
        try:
            if take_snapshot(page).refs != before_refs:
                return True
        except Exception:  # navigation in progress
            continue
    return False
