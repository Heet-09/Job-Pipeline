"""Review screen (REV-01). Rendered as a standalone HTML page (Streamlit from the LLD is not installed here)."""
import html
from pathlib import Path

from jobagent.core.db import Database


def build_review(db: Database, job_id: int) -> dict:
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    score = db.one("SELECT llm_score, reason FROM job_scores WHERE job_id=?", (job_id,))
    app = db.one("SELECT * FROM applications WHERE job_id=?", (job_id,))
    answers = [dict(r) for r in db.query("SELECT * FROM form_answers WHERE job_id=? ORDER BY id", (job_id,))]
    shots = list(dict.fromkeys(a["screenshot"] for a in answers if a["screenshot"]))
    return {
        "job": {"id": job_id, "title": job["title"], "company": job["company"], "url": job["apply_url"], "status": job["status"]},
        "score": dict(score) if score else None,
        "screenshots": shots, "answers": answers,
        "resume_diff": (app["resume_diff"] if app else "") or "", "resume_pdf": app["resume_path"] if app else None,
        "resume_flag": app["resume_flag"] if app else None,
    }


def _diff_html(unified: str) -> str:
    if not unified.strip():
        return '<p class="muted">No changes from the base resume.</p>'
    rows = []
    for ln in unified.splitlines():
        cls = "add" if ln.startswith("+") and not ln.startswith("+++") else "del" if ln.startswith("-") and not ln.startswith("---") else "same"
        rows.append(f'<div class="diff {cls}">{html.escape(ln)}</div>')
    return "".join(rows)


def render_review_html(review: dict) -> str:
    j, e = review["job"], html.escape
    head = f"<h1>{e(j['title'] or '')} @ {e(j['company'] or '')}</h1><p>Status: <b>{e(j['status'])}</b> - <a href=\"{e(j['url'] or '')}\">job link</a></p>"
    if review["score"]:
        head += f"<p>Score <b>{review['score']['llm_score']}</b>: {e(review['score']['reason'] or '')}</p>"
    shots = "".join(f'<img class="shot" src="{Path(p).resolve().as_uri()}" alt="form screenshot {i + 1}" width="480">'
                    for i, p in enumerate(review["screenshots"]))
    rows = ""
    for a in review["answers"]:
        cls = "needs-review" if a["needs_review"] else "ok"
        cell = (f'<textarea name="answer-{a["id"]}">{e(a["answer"] or "")}</textarea>' if a["needs_review"] else e(a["answer"] or ""))
        rows += (f'<tr class="{cls}" data-id="{a["id"]}"><td>{e(a["field_label"] or "")}</td><td>{cell}</td>'
                 f'<td>{e(a["source"] or "")}</td><td>{(a["confidence"] or 0):.2f}</td></tr>')
    flag = f'<p class="warn">Resume flag: {e(review["resume_flag"])}</p>' if review["resume_flag"] else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Review job {j['id']}</title><style>
body{{font-family:sans-serif;margin:24px}} table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}
tr.needs-review{{background:#fff3b0}} .diff.add{{background:#d4f8d4}} .diff.del{{background:#fbd5d5}} .diff{{font-family:monospace;white-space:pre-wrap}}
.muted{{color:#777}} .warn{{color:#b00}}</style></head><body>{head}
<h2>Form screenshots</h2><section id="screenshots">{shots}</section>
<h2>Answers</h2><table id="answers"><tr><th>Question</th><th>Answer</th><th>Source</th><th>Confidence</th></tr>{rows}</table>
<h2>Resume diff</h2>{flag}<section id="resume-diff">{_diff_html(review['resume_diff'])}</section>
<p><button name="approve">Approve</button> <button name="edit">Save edits</button> <button name="skip">Skip</button></p></body></html>"""


def save_review_html(db: Database, job_id: int, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_review_html(build_review(db, job_id)), encoding="utf-8")
    return out_path
