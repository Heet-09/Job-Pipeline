"""Local dummy application forms (Greenhouse-like). No real site is ever touched."""
from pathlib import Path

CONFIRM_JS = "document.body.innerHTML = '<h1>Thank you for applying!</h1><p>Your application has been received.</p>';"


def page(body: str, on_submit: str = CONFIRM_JS, title: str = "Apply") -> str:
    return f"""<!doctype html><html><head><title>{title}</title></head><body>
<form id="f" onsubmit="window.__submits=(window.__submits||0)+1; {on_submit} return false;">
{body}
</form></body></html>"""


def field(label: str, fid: str, kind: str = "input", required: bool = True, typ: str = "text", extra: str = "") -> str:
    star = " *" if required else ""
    req = " required" if required else ""
    if kind == "textarea":
        ctl = f'<textarea id="{fid}"{req}></textarea>'
    elif kind == "select":
        ctl = f'<select id="{fid}"{req}>{extra}</select>'
    else:
        ctl = f'<input id="{fid}" type="{typ}"{req} {extra}>'
    return f'<div><label for="{fid}">{label}{star}</label>{ctl}</div>\n'


YES_NO = '<option value="">Select...</option><option>Yes</option><option>No</option>'
SUBMIT = '<button type="submit" id="submit">Submit application</button>'


def greenhouse_form(question: str = "Why do you want to join us?", q_required: bool = False, submit_label: str = "Submit application",
                    on_submit: str = CONFIRM_JS, with_dropdown: bool = True) -> str:
    body = (field("First Name", "fn") + field("Last Name", "ln") + field("Email", "em", typ="email") +
            field("Phone", "ph", typ="tel", required=False) + field("LinkedIn Profile", "li", required=False) +
            field("Resume/CV", "rs", typ="file") +
            field(question, "q1", kind="textarea", required=q_required) +
            (field("Are you comfortable with hybrid work?", "hy", kind="select", required=False, extra=YES_NO) if with_dropdown else "") +
            f'<button type="submit" id="submit">{submit_label}</button>')
    return page(body, on_submit)


def multi_step_form(on_submit: str = CONFIRM_JS) -> str:
    return f"""<!doctype html><html><body>
<form id="f" onsubmit="window.__submits=(window.__submits||0)+1; {on_submit} return false;">
<section id="s1">{field("Full name", "nm")}{field("Email address", "em", typ="email")}
  <button type="button" onclick="go(1,2)">Next</button></section>
<section id="s2" hidden>{field("Mobile no.", "ph", typ="tel")}{field("Years of experience", "yoe")}
  <button type="button" onclick="go(2,3)">Continue</button></section>
<section id="s3" hidden>{field("Why do you want to join us?", "q1", kind="textarea", required=False)}
  <button type="submit" id="submit">Submit application</button></section>
</form>
<script>function go(a,b){{document.getElementById('s'+a).hidden=true;document.getElementById('s'+b).hidden=false;}}</script>
</body></html>"""


def phone_label_form(label: str) -> str:
    return page(field("Email", "em", typ="email") + field(label, "ph", typ="tel") + SUBMIT)


CAPTCHA_FORM = page(field("Email", "em", typ="email") +
                    '<div class="g-recaptcha" data-sitekey="abc">I\'m not a robot</div>' + SUBMIT)
CAPTCHA_IFRAME_FORM = page(field("Email", "em", typ="email") + '<iframe src="about:blank#recaptcha-anchor" width="300" height="80"></iframe>' + SUBMIT)
DATEPICKER_FORM = page(field("Email", "em", typ="email") +
                       '<div><label id="dl">Available start date</label>'
                       '<div class="custom-datepicker" data-widget="datepicker" tabindex="0" aria-labelledby="dl">Pick a date</div></div>' + SUBMIT)
LOGIN_FORM = page('<p>Please sign in to continue</p><label for="u">Username</label><input id="u"><label for="pw">Password</label><input id="pw" type="password">'
                  '<button type="button">Sign in</button>')
NOTICE_FORM = page(field("Email", "em", typ="email") + field("Notice period (days)", "np", typ="number") + SUBMIT)
SENSITIVE_FORM = page(field("Email", "em", typ="email") + field("Notice period (days)", "np", typ="number") +
                      field("Expected CTC (LPA)", "ec", typ="number") + field("Current CTC (LPA)", "cc", typ="number") +
                      field("Are you willing to relocate?", "rl", kind="select", required=False, extra=YES_NO) +
                      field("Work authorization", "wa", required=False) + SUBMIT)


def write_form(tmp_path: Path, html: str, name: str = "form.html") -> str:
    p = tmp_path / name
    p.write_text(html, encoding="utf-8")
    return p.as_uri()
