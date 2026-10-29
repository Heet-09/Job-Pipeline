"""ATS-friendly PDF (RES-05) and resume diff (RES-04).

Deviation from the LLD: reportlab instead of Jinja2 -> HTML -> Playwright, because it produces a plain
single-column text PDF with no browser dependency. Output has no tables and no images.
"""
import difflib
import html
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from jobagent.flows.f3_resume.models import ResolvedResume

MAX_PAGES = 2
SIZES = [(10, 12.5), (9, 11), (8.5, 10)]  # (font, leading), tried in order until it fits in 2 pages


@dataclass
class RenderInfo:
    path: Path
    pages: int
    font_size: float
    bullets_trimmed: int


def resume_text(r: ResolvedResume) -> str:
    """Plain-text form used for diffs. One line per bullet."""
    lines = [r.name, r.contact, "", "SUMMARY", r.summary, "", "SKILLS", ", ".join(r.skills), "", "EXPERIENCE"]
    for heading, dates, bullets in r.experience:
        lines.append(f"{heading} ({dates})")
        lines += [f"- {b}" for b in bullets]
    lines += ["", "PROJECTS"]
    for name, bullets in r.projects:
        lines.append(name)
        lines += [f"- {b}" for b in bullets]
    lines += ["", "EDUCATION", *r.education]
    return "\n".join(lines)


def _story(r: ResolvedResume, size: float, leading: float):
    e = lambda s: html.escape(s)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=size, leading=leading)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=size + 6, leading=leading + 7)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=size + 1, leading=leading + 2, spaceBefore=6)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2)
    st = [Paragraph(e(r.name), h1), Paragraph(e(r.contact), body), Paragraph("Summary", h2), Paragraph(e(r.summary), body),
          Paragraph("Skills", h2), Paragraph(e(", ".join(r.skills)), body), Paragraph("Experience", h2)]
    for heading, dates, bullets in r.experience:
        st.append(Paragraph(f"<b>{e(heading)}</b> ({e(dates)})", body))
        st += [Paragraph(e(b), bullet, bulletText="-") for b in bullets]
        st.append(Spacer(1, 3))
    st.append(Paragraph("Projects", h2))
    for name, bullets in r.projects:
        st.append(Paragraph(f"<b>{e(name)}</b>", body))
        st += [Paragraph(e(b), bullet, bulletText="-") for b in bullets]
    st.append(Paragraph("Education", h2))
    st += [Paragraph(e(x), body) for x in r.education]
    return st


def _build(r: ResolvedResume, path: Path, size: float, leading: float) -> int:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=45, rightMargin=45, topMargin=40, bottomMargin=40,
                            title=f"{r.name} - Resume", author=r.name)
    doc.build(_story(r, size, leading))
    return len(PdfReader(str(path)).pages)


def _trim_one(r: ResolvedResume) -> bool:
    """Drop the last bullet of the least important section (projects first, then oldest experience)."""
    for name, bullets in reversed(r.projects):
        if len(bullets) > 1:
            bullets.pop()
            return True
    for _, _, bullets in reversed(r.experience):
        if len(bullets) > 1:
            bullets.pop()
            return True
    return False


def render_pdf(r: ResolvedResume, path: Path) -> RenderInfo:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for size, leading in SIZES:
        pages = _build(r, path, size, leading)
        if pages <= MAX_PAGES:
            return RenderInfo(path, pages, size, 0)
    work = ResolvedResume(**{**r.__dict__, "projects": [(n, list(b)) for n, b in r.projects],
                             "experience": [(h, d, list(b)) for h, d, b in r.experience]})
    trimmed = 0
    size, leading = SIZES[-1]
    while _trim_one(work):
        trimmed += 1
        pages = _build(work, path, size, leading)
        if pages <= MAX_PAGES:
            return RenderInfo(path, pages, size, trimmed)
    return RenderInfo(path, pages, size, trimmed)


# ---------------- diff ----------------
@dataclass
class DiffLine:
    tag: str      # 'same' | 'add' | 'del'
    text: str

    @property
    def changed(self) -> bool:
        return self.tag != "same"


def diff_lines(base: str, tailored: str) -> list[DiffLine]:
    a, b = base.splitlines(), tailored.splitlines()
    out: list[DiffLine] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out += [DiffLine("same", x) for x in a[i1:i2]]
        else:
            out += [DiffLine("del", x) for x in a[i1:i2]] + [DiffLine("add", x) for x in b[j1:j2]]
    return out


def unified_diff(base: str, tailored: str) -> str:
    return "\n".join(difflib.unified_diff(base.splitlines(), tailored.splitlines(), "original", "tailored", lineterm="", n=0))


def diff_html(base: str, tailored: str) -> str:
    cls = {"same": "same", "add": "chg add", "del": "chg del"}
    mark = {"same": " ", "add": "+", "del": "-"}
    rows = "".join(f'<div class="{cls[d.tag]}">{mark[d.tag]} {html.escape(d.text)}</div>' for d in diff_lines(base, tailored))
    return ('<style>.chg.add{background:#d4f8d4}.chg.del{background:#fbd5d5;text-decoration:line-through}</style>'
            f'<div class="resume-diff">{rows}</div>')
