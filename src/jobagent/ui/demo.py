"""Fake data so the dashboard can be explored (and tested) without running the pipeline. NEVER written to your real database."""
import json
from datetime import timedelta
from pathlib import Path

from jobagent.core.db import Database

JOBS = [  # title, company, location, status, score, role_category
    ("Agentic AI Engineer", "Northwind Labs", "Bengaluru", "SCORED", 88, "genai_agent"),
    ("GenAI Engineer", "Contoso AI", "Mumbai", "SCORED", 82, "genai_agent"),
    ("LLM Application Developer", "Fabrikam Tech", "Remote", "MAYBE", 66, "genai_agent"),
    ("Machine Learning Engineer", "Tailspin Data", "Pune", "MAYBE", 58, "ml"),
    ("AI Support Associate", "Wingtip Services", "Chennai", "REJECTED", 31, "other"),
    ("Data Scientist", "Adventure Works", "Hyderabad", "REJECTED", 44, "ml"),
    ("AI Engineer", "Litware Systems", "Mumbai", "TAILORED", 91, "genai_agent"),
    ("NLP Engineer", "Proseware", "Bengaluru", "FILLED", 85, "ml"),
    ("GenAI Developer", "Lucerne Publishing", "Pune", "FILLED", 79, "genai_agent"),
    ("Agent Developer", "Woodgrove Bank", "Mumbai", "NEEDS_HUMAN", 84, "genai_agent"),
    ("LLM Engineer", "Coho Winery Tech", "Remote", "SUBMITTED", 90, "genai_agent"),
    ("AI Research Engineer", "Relecloud", "Bengaluru", "SUBMITTED", 87, "genai_agent"),
    ("Applied AI Engineer", "Margie Travel", "Mumbai", "SUBMITTED", 83, "genai_agent"),
    ("Python AI Developer", "VanArsdel", "Pune", "SUBMITTED", 81, "backend"),
    ("GenAI Platform Engineer", "Humongous Insurance", "Mumbai", "SUBMIT_UNCERTAIN", 80, "genai_agent"),
    ("ML Engineer", "Blue Yonder", "Delhi", "SKIPPED", 72, "ml"),
    ("AI Engineer", "Tailwind Traders", "Gurugram", "FAILED", None, "other"),
    ("LLM Engineer", "Graphic Design Inst", "Remote", "DISCOVERED", None, "other"),
]
APPS = {  # company -> (status, days since submit)
    "Coho Winery Tech": ("INTERVIEW", 6), "Relecloud": ("SHORTLISTED", 5), "Margie Travel": ("RECEIVED", 12), "VanArsdel": ("SUBMITTED", 3),
    "Humongous Insurance": (None, 1),
}


def seed_demo(db: Database, shots_dir: Path | None = None) -> None:
    now = db.now()
    ts = lambda days=0, hours=0: (now - timedelta(days=days, hours=hours)).isoformat(timespec="seconds")
    ids = {}
    for i, (title, company, loc, status, score, cat) in enumerate(JOBS):
        jd = {"must_have_skills": ["Python", "LangChain", "LangGraph"], "exp_min": 1, "exp_max": 4, "salary_range": None, "role_category": cat}
        jid = db.write(
            "INSERT INTO jobs(dedupe_key, canonical_url, source, title, company, location, posted_at, discovered_at, jd_raw, jd_json, apply_url,"
            " status, status_updated_at, attempts, last_error, flags, manual) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"demo{i}", f"https://naukri.com/job-listings-demo-{i}", "naukri_scraper", title, company, loc, ts(i % 3), ts(i % 3, 2),
             f"{title} at {company}. Build LLM agents with Python, LangChain and LangGraph. 1-4 years of experience. (demo data)", json.dumps(jd),
             f"https://naukri.com/job-listings-demo-{i}", status, ts(i % 3), 3 if status == "FAILED" else 0,
             "provider exploded" if status == "FAILED" else None, "posted_date_missing" if i == 3 else "", 0)).lastrowid
        ids[company] = jid
        steps = ["DISCOVERED", "EXTRACTED"] + ([status] if status not in ("DISCOVERED",) else [])
        prev = None
        for s in steps:
            db.write("INSERT INTO job_history(job_id, from_status, to_status, note, at) VALUES (?,?,?,?,?)", (jid, prev, s, f"score {score}" if s == status and score else None, ts(i % 3, 1)))
            prev = s
        if score is not None:
            parts = {"skills": min(40, round(score * .42)), "seniority": 18, "salary": 8, "role_type": 15 if cat == "genai_agent" else 6, "company": 5}
            db.write("INSERT INTO job_scores(job_id, llm_score, breakdown, reason, model, profile_hash, scored_at) VALUES (?,?,?,?,?,?,?)",
                     (jid, score, json.dumps(parts), "Strong overlap on LangGraph/LangChain.\nSalary not stated (neutral).", "rules", "demo", ts(i % 3)))
    for company, (status, days) in APPS.items():
        jid = ids[company]
        aid = db.write("INSERT INTO applications(job_id, current_status, submitted_at, approved_at, resume_path, profile_hash) VALUES (?,?,?,?,?,?)",
                       (jid, status, ts(days), ts(days, 1), None, "demo")).lastrowid
        if status in ("INTERVIEW", "SHORTLISTED", "RECEIVED"):
            db.write("INSERT INTO status_events(application_id, status, email_id, snippet, at) VALUES (?,?,?,?,?)",
                     (aid, "RECEIVED", f"e{aid}a", "Thank you for applying. We have received your application.", ts(days - 1)))
        if status in ("INTERVIEW", "SHORTLISTED"):
            db.write("INSERT INTO status_events(application_id, status, email_id, snippet, at) VALUES (?,?,?,?,?)",
                     (aid, status, f"e{aid}b", "We would like to invite you for an interview on 5 November 2026 at 3:00 PM." if status == "INTERVIEW" else "You have been shortlisted.", ts(1)))
    for company in ("Proseware", "Lucerne Publishing", "Woodgrove Bank"):
        jid = ids[company]
        shot = None
        if shots_dir:
            shot = _placeholder_png(Path(shots_dir) / f"demo_{jid}.png", company)
        db.write("INSERT INTO applications(job_id, resume_diff, current_status, profile_hash) VALUES (?,?,?,?)",
                 (jid, "@@ -8 +8 @@\n-- Developed REST APIs in Python and FastAPI.\n+- Built LangChain retrieval pipelines serving 5000 users.", None, "demo"))
        rows = [("First Name", "text", "Aarav", "profile", 1.0, 0), ("Email", "text", "aarav@example.com", "profile", 1.0, 0),
                ("Why do you want to join us?", "textarea", "I enjoy building reliable LLM agents and your team ships them to real users.", "llm", .5, 1),
                ("Notice period (days)", "text", None if company == "Woodgrove Bank" else "30", "profile", 0.0 if company == "Woodgrove Bank" else 1.0, 1 if company == "Woodgrove Bank" else 0)]
        for label, typ, ans, src, conf, nr in rows:
            db.write("INSERT INTO form_answers(job_id, page_no, field_ref, field_label, field_type, answer, source, confidence, needs_review, screenshot) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (jid, 1, f"{typ}:{label}:0", label, typ, ans, src, conf, nr, shot))
    db.write("UPDATE job_history SET note='required field Notice period (days) has no answer (sensitive) - needs the user' WHERE job_id=? AND to_status='NEEDS_HUMAN'", (ids["Woodgrove Bank"],))
    for sender, subj, reason in [("Hiring <hr@contoso-careers.com>", "Update on your application", "ambiguous: margin 0 <= 10 between two applications"),
                                 ("recruiter@somewhere.org", "Re: your profile", "best match score 41 <= 80")]:
        db.write("INSERT INTO manual_review(email_id, sender, subject, reason, created_at) VALUES (?,?,?,?,?)", (subj, sender, subj, reason, ts(1)))
    db.write("INSERT INTO answer_bank(canonical_question, answer, human_approved, use_count, needs_cleanup, updated_at) VALUES (?,?,?,?,?,?)",
             ("Why do you want to join us?", "I enjoy building reliable LLM agents.", 1, 4, 0, ts(2)))
    db.write("INSERT INTO answer_bank(canonical_question, answer, human_approved, use_count, needs_cleanup, updated_at) VALUES (?,?,?,?,?,?)",
             ("Describe a project you are proud of", "My job-application agent.", 0, 1, 1, ts(2)))
    db.write("INSERT INTO answer_bank(canonical_question, answer, human_approved, use_count, needs_cleanup, updated_at) VALUES (?,?,?,?,?,?)",
             ("Describe a project you are proud of.", "A RAG system for support tickets.", 0, 1, 1, ts(1)))
    for flow, model, n, cost in [("extract", "llama-3.1-8b-instant", 40, .0004), ("score", "llama-3.1-8b-instant", 40, .0005), ("tailor", "llama-3.3-70b-versatile", 6, .0121)]:
        for _ in range(n):
            db.write("INSERT INTO llm_calls(flow, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, ok, at) VALUES (?,?,?,?,?,?,?,?)",
                     (flow, model, 900, 150, cost / n, 350, 1, ts(1)))
    db.write("INSERT INTO profile_versions(hash, version, saved_at, profile_json) VALUES ('demo1', 1, ?, '{}')", (ts(9),))
    db.write("INSERT INTO profile_versions(hash, version, saved_at, profile_json) VALUES ('demo2', 2, ?, '{}')", (ts(2),))


def _placeholder_png(path: Path, label: str) -> str:
    from PIL import Image, ImageDraw
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 360), "#f4f6f8")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 620, 340], outline="#9aa5b1", width=2)
    d.text((40, 40), f"Application form (demo screenshot)\n{label}", fill="#333")
    for i, y in enumerate(range(100, 300, 50)):
        d.rectangle([40, y, 400, y + 28], outline="#9aa5b1")
    img.save(path)
    return str(path)
