"""FRM-07: the fill phase can never click a final-submit button. Only f5_review.submit passes allow_submit=True."""
import re

SUBMIT_RE = re.compile(r"submit|apply now|send application|finish|complete application", re.I)
NEXT_RE = re.compile(r"^\s*(next|continue|save\s*(&|and)\s*continue|proceed|go to next|next step)\b", re.I)

# Belt and braces: even if some code path clicked a submit control, the page-level submit event is cancelled
# unless the replay step has explicitly switched submission on.
BLOCK_SUBMIT_JS = """
document.addEventListener('submit', e => {
  if (!window.__jobagent_allow_submit) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
"""


class SubmitBlocked(Exception):
    """Raised when something tries to click a submit-like control during the fill phase."""


def control_text(locator) -> str:
    parts = [locator.inner_text() or "", locator.get_attribute("value") or "", locator.get_attribute("aria-label") or "",
             locator.get_attribute("title") or ""]
    return " ".join(p for p in parts if p).strip()


def is_submit_text(text: str) -> bool:
    return bool(SUBMIT_RE.search(text or ""))


def safe_click(locator, allow_submit: bool = False) -> None:
    text = control_text(locator)
    if not allow_submit and is_submit_text(text):
        raise SubmitBlocked(f"refusing to click '{text}' during the fill phase")
    locator.click()
