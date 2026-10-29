"""Fetch a JD. Login walls / blocks fall back to the alert-email snippet and mark the job JD_PARTIAL."""
import re
import time
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


def _get_with_backoff(url: str, http_get: HttpGet, sleep, retries: int = 3, base_delay: float = 1.0) -> tuple[int, str]:
    """HTTP 429 (source rate limit) -> exponential backoff and retry."""
    for attempt in range(retries + 1):
        status, body = http_get(url)
        if status != 429 or attempt == retries:
            return status, body
        sleep(base_delay * (2 ** attempt))
    return status, body


def fetch_jd(url: str, snippet: str | None, http_get: HttpGet, browser_get: HttpGet | None = None,
             sleep=time.sleep) -> tuple[str, bool]:
    """Returns (text, partial). partial=True means the text is only the email snippet."""
    try:
        status, body = _get_with_backoff(url, http_get, sleep)
        text = html_to_text(body) if status < 400 else ""
        if status < 400 and len(text) < 500 and browser_get:  # JS-rendered page: try the browser fallback
            status, body = browser_get(url)
            text = html_to_text(body) if status < 400 else ""
    except Exception:
        status, text = 599, ""
    if status >= 400 or LOGIN_WALL.search(text) or len(text) < MIN_TEXT:
        return (snippet or ""), True
    return text, False


def default_http_get(url: str) -> tuple[int, str]:
    """Plain urllib GET (fine for static pages). LinkedIn/Naukri usually answer 4xx or a login wall -> JD_PARTIAL."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
