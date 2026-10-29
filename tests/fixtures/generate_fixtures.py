"""Generates the synthetic alert-email fixtures in tests/fixtures/emails/*.eml (run once, files are committed).

NOTE: these imitate the structure of LinkedIn/Naukri alerts but are NOT real captured emails.
"""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

OUT = Path(__file__).parent / "emails"
OUT.mkdir(exist_ok=True)
DATE = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)

COMPANIES = ["Acme AI Labs", "Beta Systems", "Cyan Robotics", "Delta Cloud", "Echo Analytics",
             "Foxtrot Data", "Gamma Health", "Helix Bio", "Indigo Pay", "Juno Mobility",
             "Kappa Retail", "Lumen Edu", "Mango Media", "Nimbus Labs", "Orbit Space"]
TITLES = ["GenAI Engineer", "LLM Engineer", "AI Engineer", "ML Engineer", "Python Developer",
          "Agent Developer", "NLP Engineer", "AI Research Engineer", "Applied AI Engineer", "Machine Learning Engineer"]
CITIES = ["Mumbai, India", "Pune, India", "Bengaluru, India", "Remote", "Hyderabad, India"]


def jobs_for(n_email):
    out = []
    for j in range(3):
        k = n_email * 3 + j
        out.append((TITLES[k % len(TITLES)], COMPANIES[k % len(COMPANIES)], CITIES[k % len(CITIES)], 1 + (k % 2)))
    return out


def ago(d):
    return f"{d} day{'s' if d > 1 else ''} ago"


def linkedin_html(jobs, base):
    rows = ""
    for n, (t, c, loc, d) in enumerate(jobs):
        href = f"https://www.linkedin.com/comm/jobs/view/{base}{n}?trackingId=abc&refId=xyz&trk=eml-job_alerts"
        rows += f'<tr><td><a href="{href}">{t}</a><p>{c} · {loc}</p><p>{ago(d)}</p></td></tr>'
    return f"<html><body><table>{rows}</table></body></html>"


def naukri_html(jobs, base):
    rows = ""
    for n, (t, c, loc, d) in enumerate(jobs):
        slug = f"{t.lower().replace(' ', '-')}-{c.lower().replace(' ', '-')}"
        href = f"https://www.naukri.com/job-listings-{slug}-{base}{n}?src=jobAlert&sid=1"
        rows += (f'<tr><td><a href="{href}">{t}</a><span class="comp">{c}</span><span class="exp">Exp: 1-4 Yrs</span>'
                 f'<span class="loc">{loc.split(",")[0]}</span><span class="posted">{ago(d)}</span></td></tr>')
    return f"<html><body><table>{rows}</table></body></html>"


def write(name, sender, subject, html, msg_id):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = sender, "me@example.com", subject, msg_id
    m["Date"] = format_datetime(DATE)
    m.set_content("Plain text version of the alert")
    m.add_alternative(html, subtype="html")
    (OUT / name).write_bytes(bytes(m))


for i in range(5):
    write(f"linkedin_{i + 1}.eml", "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "3 new jobs for AI Engineer",
          linkedin_html(jobs_for(i), 4000 + i * 10), f"<li-{i + 1}@fixture>")
    write(f"naukri_{i + 1}.eml", "Naukri Job Alerts <info@naukri.com>", "Jobs for you: AI Engineer",
          naukri_html(jobs_for(i + 5), 5000 + i * 10), f"<nk-{i + 1}@fixture>")
# template changed: no job anchors any more
write("linkedin_changed_template.eml", "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "3 new jobs",
      "<html><body><div class='card-v2'><span>Open the app to view your jobs</span></div></body></html>", "<li-changed@fixture>")
