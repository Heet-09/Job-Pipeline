"""Naukri job-page scraper (logic moved here from the original naukri_scraper.py, behaviour unchanged).

Naukri renders client side and blocks headless browsers, so a visible Chrome window is used.
Scraping may be against Naukri's terms of service - small-scale personal use only.
"""
import json
import re
import time
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd

COLUMNS = [
    "link", "job_role", "company", "exp_min_years", "exp_max_years", "package",
    "work_mode", "location", "apply_on_company_site", "posted", "job_description",
    "key_skills", "status",
]


def find_link_column(df):
    for c in df.columns:
        if str(c).strip().lower() in ("link", "links", "url", "urls", "job link"):
            return c
    return df.columns[0]


def read_links(src: str | Path) -> list[str]:
    """Links from an Excel file: a 'link'/'url' column, else the first column; no header row also works. De-duplicated."""
    df = pd.read_excel(src)
    if str(df.columns[0]).startswith("http"):  # no header row - first cell is a link
        df = pd.read_excel(src, header=None)
    return list(dict.fromkeys(str(u).strip() for u in df[find_link_column(df)].dropna() if str(u).strip().startswith("http")))


def parse_exp(text):
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*(?:Yrs?|years?)", text or "", re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*\+?\s*(?:Yrs?|years?)", text or "", re.I)
    return (int(m.group(1)), None) if m else (None, None)


def jsonld_job(page):
    """Return the JobPosting JSON-LD block if the page has one."""
    for raw in page.eval_on_selector_all(
        'script[type="application/ld+json"]', "els => els.map(e => e.textContent)"
    ):
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return {}


def first_text(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                t = el.inner_text().strip()
                if t:
                    return t
        except Exception:
            pass
    return ""


def extract_job(page, url):
    """Read the fields of an already-loaded Naukri job page."""
    ld = jsonld_job(page)
    body = page.inner_text("body")

    role = first_text(page, ["h1", "[class*='jd-header-title']"]) or ld.get("title", "")
    company = first_text(page, ["[class*='jd-header-comp-name'] a", "[class*='comp-name']"])
    if not company:
        company = (ld.get("hiringOrganization") or {}).get("name", "")

    exp_text = first_text(page, ["[class*='styles_jhc__exp__']"])
    if not re.search(r"\d", exp_text):
        m = re.search(r"\d+\s*-\s*\d+\s*(?:Yrs?|years?)", body, re.I)
        exp_text = m.group(0) if m else ""
    exp_min, exp_max = parse_exp(exp_text)

    salary = first_text(page, ["[class*='styles_jhc__salary__']"])
    if not salary:
        m = re.search(r"(Not Disclosed|[\d.,]+\s*-\s*[\d.,]+\s*(?:Lacs?|LPA)[^\n]*)", body, re.I)
        salary = m.group(0) if m else ""

    location = first_text(page, ["[class*='styles_jhc__location__']"])
    if not location:
        loc = ld.get("jobLocation")
        loc = loc[0] if isinstance(loc, list) and loc else loc
        if isinstance(loc, dict):
            location = (loc.get("address") or {}).get("addressLocality", "")
    if ld.get("jobLocationType") == "TELECOMMUTE" or re.search(r"\bremote\b", location, re.I):
        mode = "Remote"
    elif re.search(r"work from home|\bwfh\b", body[:3000], re.I):
        mode = "Remote"
    elif re.search(r"\bhybrid\b", body[:3000], re.I):
        mode = "Hybrid"
    else:
        mode = "Office"

    posted = ""
    m = re.search(r"Posted:\s*([^\n]+)", body)
    if m:
        posted = m.group(1).strip()
    elif ld.get("datePosted"):
        posted = ld["datePosted"]

    # Naukri shows "Apply on company site" when the application is external, otherwise a plain "Apply" button.
    apply_site = "Yes" if (page.query_selector("#company-site-button") or page.query_selector("text=/apply on company site/i")) else "No"

    desc = first_text(page, ["[class*='job-desc']", "[class*='JDC__dang-inner-html']", "[class*='dang-inner-html']"])
    if not desc and ld.get("description"):
        desc = re.sub(r"<[^>]+>", "\n", ld["description"]).strip()

    skills = page.eval_on_selector_all(
        "[class*='key-skill'] a, [class*='chip'] span", "els => els.map(e => e.innerText.trim())"
    )
    skills = ", ".join(dict.fromkeys(s for s in skills if s))
    if not skills and ld.get("skills"):
        skills = ld["skills"] if isinstance(ld["skills"], str) else ", ".join(ld["skills"])

    return {
        "link": url, "job_role": role, "company": company,
        "exp_min_years": exp_min, "exp_max_years": exp_max, "package": salary,
        "work_mode": mode, "location": location, "apply_on_company_site": apply_site,
        "posted": posted, "job_description": desc, "key_skills": skills, "status": "ok",
    }


def scrape(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    if "job-listings" not in page.url:  # Naukri redirects expired jobs to a search page
        return {"link": url, "status": "job expired/removed (redirected to search page)"}
    # Naukri renders client side - wait until the description exists.
    page.wait_for_selector("[class*='job-desc'], [class*='JDC'], h1", timeout=30000)
    time.sleep(2)
    return extract_job(page, url)


def scrape_links(urls: list[str], headless: bool = False, delay: float = 3.0,
                 on_progress: Callable[[int, int, str], None] | None = None) -> Iterator[dict]:
    """Open a browser and yield one row per URL (rows are yielded as they are scraped, so a crash loses nothing)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            locale="en-IN", viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )
        page = ctx.new_page()
        try:
            for i, url in enumerate(urls, 1):
                if on_progress:
                    on_progress(i, len(urls), url)
                if "naukri.com/job-listings-" not in url:
                    yield {"link": url, "status": "skipped (not a Naukri job listing link)"}
                    continue
                try:
                    yield scrape(page, url)
                except Exception as e:
                    yield {"link": url, "status": f"error: {str(e)[:150]}"}
                time.sleep(delay)
        finally:
            browser.close()
