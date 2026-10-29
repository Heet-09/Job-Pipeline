"""Read the visible form fields of the current page into FieldSpec objects (and detect blockers)."""
from dataclasses import dataclass, field

from jobagent.core.schemas import FieldSpec

# Runs in the page. Stamps every field with data-jaref so Playwright can re-locate it later.
_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = t => (t || '').replace(/\s+/g, ' ').replace(/[*:]\s*$/, '').replace(/\s*\*\s*$/, '').trim();
  const labelOf = el => {
    if (el.labels && el.labels.length) return el.labels[0].innerText;
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const n = document.getElementById(lb); if (n) return n.innerText; }
    const wrap = el.closest('label'); if (wrap) return wrap.innerText;
    if (el.placeholder) return el.placeholder;
    return el.name || el.id || '';
  };
  document.querySelectorAll('[data-jaref]').forEach(e => e.removeAttribute('data-jaref'));  // drop tokens from earlier pages
  const out = { fields: [], unknown: [], captcha: false, login: false };
  const seenRadio = {}; const counts = {}; let n = 0;
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const tag = el.tagName.toLowerCase(); let type = tag === 'input' ? (el.type || 'text').toLowerCase() : tag;
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) continue;
    if (type === 'password') { if (vis(el)) out.login = true; continue; }
    if (!vis(el) && type !== 'file') continue;
    if (type === 'file' && !el.closest('form') && !vis(el)) continue;
    let kind = ({select: 'select', textarea: 'textarea', checkbox: 'checkbox', radio: 'radio', file: 'file', date: 'date'})[type] || 'text';
    let label, options = [], tok;
    if (kind === 'radio') {
      const g = el.name || ('r' + n);
      if (seenRadio[g]) continue;
      const group = [...document.querySelectorAll('input[type=radio]')].filter(r => (r.name || '') === (el.name || '') && vis(r));
      const fs = el.closest('fieldset'); const leg = fs && fs.querySelector('legend');
      label = clean(leg ? leg.innerText : (el.closest('[data-question]') ? el.closest('[data-question]').getAttribute('data-question') : g));
      tok = 'r' + (n++); seenRadio[g] = 1;
      group.forEach((r, i) => { r.setAttribute('data-jaref', tok + '#' + i); options.push(clean(labelOf(r))); });
    } else {
      label = clean(labelOf(el)); tok = 'r' + (n++); el.setAttribute('data-jaref', tok);
      if (kind === 'select') options = [...el.options].filter(o => o.value !== '' && !/^select|^choose|^--/i.test(o.text.trim())).map(o => o.text.trim());
    }
    const raw = labelOf(el);
    const required = !!(el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test((raw || '').trim()));
    const key = kind + ':' + label; counts[key] = (counts[key] || 0);
    out.fields.push({ ref: kind + ':' + label + ':' + counts[key]++, token: tok, label, kind, required, options });
  }
  for (const el of document.querySelectorAll('[data-widget], [contenteditable="true"], [role="slider"], [role="listbox"], [role="combobox"]:not(input):not(select)')) {
    if (vis(el)) out.unknown.push(clean(el.getAttribute('data-widget') || el.getAttribute('aria-label') || el.className || el.tagName));
  }
  const text = document.body ? document.body.innerText : '';
  out.captcha = !!document.querySelector('.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[src*="captcha"]')
    || /verify you are human|i'?m not a robot|i am not a robot|complete the captcha/i.test(text);
  if (/sign in to continue|log in to continue|login required/i.test(text)) out.login = true;
  return out;
}
"""


@dataclass
class PageSnapshot:
    fields: list[FieldSpec] = field(default_factory=list)
    tokens: dict[str, str] = field(default_factory=dict)   # ref -> data-jaref token
    unknown_widgets: list[str] = field(default_factory=list)
    captcha: bool = False
    login_wall: bool = False

    @property
    def refs(self) -> set[str]:
        return {f.ref for f in self.fields}


def take_snapshot(page) -> PageSnapshot:
    raw = page.evaluate(_JS)
    snap = PageSnapshot(unknown_widgets=raw["unknown"], captcha=raw["captcha"], login_wall=raw["login"])
    for f in raw["fields"]:
        snap.fields.append(FieldSpec(ref=f["ref"], label=f["label"], type=f["kind"], required=f["required"], options=f["options"]))
        snap.tokens[f["ref"]] = f["token"]
    return snap
