"""Scraper job source: Naukri job links (from an Excel file) -> scraped rows -> JobRaw with the FULL job description."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from jobagent.core.schemas import JobRaw
from jobagent.flows.f1_discovery.normalizer import parse_posted

ScrapeFn = Callable[[list[str]], Iterable[dict]]  # urls -> one row dict per url (same columns as naukri_scrape.COLUMNS)


def _num(v) -> float | None:
    try:
        f = float(v)
        return None if f != f else f  # NaN -> None
    except (TypeError, ValueError):
        return None


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()


def row_to_job(row: dict, now: datetime) -> JobRaw | None:
    """None for rows that are not real jobs (expired, skipped, error, or missing title/company)."""
    if _s(row.get("status")) != "ok" or not _s(row.get("job_role")) or not _s(row.get("company")):
        return None
    lo, hi = _num(row.get("exp_min_years")), _num(row.get("exp_max_years"))
    exp = f"{lo:g}-{hi:g} Yrs" if lo is not None and hi is not None else f"{lo:g}+ Yrs" if lo is not None else None
    desc, skills, pkg = _s(row.get("job_description")), _s(row.get("key_skills")), _s(row.get("package"))
    jd = "\n".join(x for x in (desc, f"Key skills: {skills}" if skills else "", f"Salary: {pkg}" if pkg and pkg.lower() != "not disclosed" else "") if x)
    return JobRaw(url=_s(row["link"]), source="naukri_scraper", title=_s(row["job_role"]), company=_s(row["company"]),
                  location=_s(row.get("location")) or None, posted_at=parse_posted(_s(row.get("posted")), now),
                  snippet=(desc or jd)[:500], exp_text=exp, jd_text=jd or None)


@dataclass
class ScrapeBatch:
    jobs: list[JobRaw]
    total: int            # rows scraped
    expired: int = 0
    skipped: int = 0
    errors: int = 0
    first_error: str = ""


class NaukriScraperSource:
    def __init__(self, links: list[str], scrape: ScrapeFn):
        self.links, self.scrape = links, scrape

    def fetch(self, now: datetime) -> ScrapeBatch:
        batch = ScrapeBatch(jobs=[], total=0)
        for row in self.scrape(self.links):
            batch.total += 1
            status = _s(row.get("status"))
            job = row_to_job(row, now)
            if job:
                batch.jobs.append(job)
            elif status.startswith("job expired"):
                batch.expired += 1
            elif status.startswith("skipped"):
                batch.skipped += 1
            else:
                batch.errors += 1
                batch.first_error = batch.first_error or status
        return batch

    @classmethod
    def from_excel(cls, path: Path, headless: bool = False, delay: float = 3.0, on_progress=None) -> "NaukriScraperSource":
        from jobagent.flows.f1_discovery.naukri_scrape import read_links, scrape_links
        return cls(read_links(path), lambda urls: scrape_links(urls, headless, delay, on_progress))
