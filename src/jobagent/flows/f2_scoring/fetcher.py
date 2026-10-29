"""Fetch a JD. Login walls / blocks fall back to the alert-email snippet and mark the job JD_PARTIAL."""
import re
from typing import Callable

from bs4 import BeautifulSoup

HttpGet = Callable[[str], tuple[int, str]]  # url -> (status_code, body)

LOGIN_WALL = re.compile(r"sign in to view|join now to see|log in to (see|view|apply)|login to (see|view|apply)|authwall|please sign in", re.I)
MIN_TEXT = 200


def html_to_text(body: str) -> str:
    soup = BeautifulSoup(body, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return re.sub(r"\n{2,}", "\n", soup.get_text("\n")).strip()


def fetch_jd(url: str, snippet: str | None, http_get: HttpGet, browser_get: HttpGet | None = None) -> tuple[str, bool]:
    """Returns (text, partial). partial=True means the text is only the email snippet."""
    try:
        status, body = http_get(url)
        text = html_to_text(body) if status < 400 else ""
        if status < 400 and len(text) < 500 and browser_get:  # JS-rendered page: try the browser fallback
            status, body = browser_get(url)
            text = html_to_text(body) if status < 400 else ""
    except Exception:
        status, text = 599, ""
    if status >= 400 or LOGIN_WALL.search(text) or len(text) < MIN_TEXT:
        return (snippet or ""), True
    return text, False
