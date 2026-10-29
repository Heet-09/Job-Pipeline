"""Field -> category/profile_key. Regex shortcuts for known labels (no LLM call); optional LLM only for the rest."""
import re
from pathlib import Path

from jobagent.core.llm import LLMClient, LLMError
from jobagent.core.schemas import FieldMap, FieldSpec

# (pattern, category, profile_key). First match wins, so order matters.
RULES: list[tuple[str, str, str | None]] = [
    (r"e-?\s?mail", "personal", "personal.email"),
    (r"first\s*name|given\s*name|forename", "personal", "personal.first_name"),
    (r"last\s*name|surname|family\s*name", "personal", "personal.last_name"),
    (r"linked\s*in", "personal", "personal.links.linkedin"),
    (r"git\s*hub", "personal", "personal.links.github"),
    (r"portfolio|personal\s*(web)?site|website|blog", "personal", "personal.links.portfolio"),
    (r"phone|mobile|contact\s*(no|number|num|#)|telephone|whats\s*app|\bcell\b", "personal", "personal.phone"),
    (r"^(your |full |candidate |legal )?name$|\bfull\s*name\b|^your name", "personal", "personal.name"),
    (r"current\s*(location|city)|^location(\s*\(city\))?$|^city$|where are you (based|located)|city of residence|place of residence", "personal", "personal.location"),
    (r"notice\s*period|(how soon|when) can you (join|start)|joining time|available to (join|start)|earliest (joining|start)", "sensitive", "sensitive.notice_period_days"),
    (r"expected\s*(ctc|salary|compensation|package|pay|remuneration)|salary\s*expectation|desired (salary|ctc)", "sensitive", "sensitive.expected_ctc"),
    (r"current\s*(ctc|salary|compensation|package)|present\s*(ctc|salary)|last\s*drawn|existing (ctc|salary)", "sensitive", "sensitive.current_ctc"),
    (r"relocat", "sensitive", "sensitive.relocation"),
    (r"work\s*(authori[sz]ation|permit)|authori[sz]ed\s*to\s*work|legally\s*(authori[sz]ed|allowed)|eligible\s*to\s*work|right\s*to\s*work|visa|sponsorship", "sensitive", "sensitive.work_auth"),
    (r"years?\s*of\s*(total |relevant |professional |work )?experience|total\s*experience|experience\s*\(?in\s*years|how many years", "experience", "experience.total_years"),
    (r"gender|race|ethnic|hispanic|latino|disabilit|veteran|pronoun|sexual orientation|caste|marital", "skip", None),
]
NOT_A_VALUE_RE = re.compile(r"(phone|mobile|contact)\s*(device\s*)?type|country\s*(phone\s*)?code|dial(ing)?\s*code|phone\s*code", re.I)  # choices ABOUT a phone, not the number
CONSENT_RE = re.compile(r"agree|consent|acknowledge|privacy|terms|i confirm|i certify|i declare|data processing", re.I)
RESUME_RE = re.compile(r"resume|\bcv\b|curriculum", re.I)
VALID_KEYS = {k for _, _, k in RULES if k}


def map_field(spec: FieldSpec) -> FieldMap | None:
    """Rule-based mapping. None means 'no rule matched'."""
    label = spec.label.strip().lower()
    if spec.type == "file":
        return FieldMap(ref=spec.ref, category="file_resume" if RESUME_RE.search(label) else "skip")
    if spec.type == "checkbox" and CONSENT_RE.search(label):
        return FieldMap(ref=spec.ref, category="consent")
    if spec.type == "checkbox" and not re.search(r"e-?mail|phone|name|ctc|salary|relocat|notice", label):
        return None
    if NOT_A_VALUE_RE.search(label):
        return None
    for pattern, category, key in RULES:
        if re.search(pattern, label):
            return FieldMap(ref=spec.ref, category=category, profile_key=key)
    return None


_PROMPT = Path(__file__).resolve().parents[4] / "prompts" / "field_map.md"


def map_fields(specs: list[FieldSpec], llm: LLMClient | None = None) -> dict[str, FieldMap]:
    out: dict[str, FieldMap] = {}
    for spec in specs:
        fm = map_field(spec)
        if fm is None and llm is not None:
            try:
                got = llm.call("small", _PROMPT.read_text(encoding="utf-8"),
                               f"label: {spec.label}\ntype: {spec.type}\noptions: {spec.options}\nvalid profile_keys: {sorted(VALID_KEYS)}",
                               FieldMap, flow="map_field")
                key_ok = got.profile_key in VALID_KEYS or got.profile_key is None
                if got.category == "sensitive" and not got.profile_key:
                    key_ok = False
                if key_ok and got.category in ("personal", "experience", "sensitive") and not got.profile_key:
                    key_ok = False
                fm = FieldMap(ref=spec.ref, category=got.category, profile_key=got.profile_key) if key_ok else None
            except LLMError:
                fm = None
        out[spec.ref] = fm or FieldMap(ref=spec.ref, category="custom_question")
    return out
