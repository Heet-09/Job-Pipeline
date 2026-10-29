"""F7 metrics (pure SQL): weekly funnel (FBK-01), response rate by score bucket (FBK-02)."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from jobagent.core.db import Database

POSITIVE = ("SHORTLISTED", "INTERVIEW")
RESPONDED = ("SHORTLISTED", "INTERVIEW", "REJECTED")   # a human replied; an automatic 'received' does not count
BUCKETS = [("80+", 80, 1000), ("70-79", 70, 80), ("50-69", 50, 70)]


@dataclass
class Funnel:
    week_start: str
    week_end: str
    discovered: int
    applied: int
    responses: int
    interviews: int

    def render(self) -> str:
        rate = f"{100 * self.responses / self.applied:.0f}%" if self.applied else "n/a"
        return (f"Weekly funnel {self.week_start} -> {self.week_end}\n"
                f"  Discovered: {self.discovered}\n  Applied:    {self.applied}\n"
                f"  Responses:  {self.responses} ({rate} of applied)\n  Interviews: {self.interviews}")


def weekly_funnel(db: Database, week_start: datetime) -> Funnel:
    start, end = week_start.isoformat(timespec="seconds"), (week_start + timedelta(days=7)).isoformat(timespec="seconds")
    discovered = db.scalar("SELECT COUNT(*) FROM jobs WHERE discovered_at >= ? AND discovered_at < ?", (start, end)) or 0
    applied = db.scalar("SELECT COUNT(*) FROM applications WHERE submitted_at >= ? AND submitted_at < ?", (start, end)) or 0
    q = ",".join("?" * len(RESPONDED))
    responses = db.scalar(f"SELECT COUNT(*) FROM applications WHERE submitted_at >= ? AND submitted_at < ? AND current_status IN ({q})",
                          (start, end, *RESPONDED)) or 0
    interviews = db.scalar("SELECT COUNT(*) FROM applications WHERE submitted_at >= ? AND submitted_at < ? AND current_status = 'INTERVIEW'", (start, end)) or 0
    return Funnel(start[:10], end[:10], discovered, applied, responses, interviews)


@dataclass
class BucketRate:
    bucket: str
    applied: int
    positive: int

    @property
    def rate(self) -> float | None:
        return None if self.applied == 0 else round(100 * self.positive / self.applied, 1)  # None = no applications yet, not 0%

    def render(self) -> str:
        return f"{self.bucket}: {self.positive}/{self.applied} positive = {'n/a' if self.rate is None else f'{self.rate:.0f}%'}"


def bucket_response_rates(db: Database) -> list[BucketRate]:
    """Every bucket is always returned, even with zero applications."""
    out = []
    q = ",".join("?" * len(POSITIVE))
    for name, lo, hi in BUCKETS:
        base = "FROM applications a JOIN job_scores s ON s.job_id = a.job_id WHERE a.submitted_at IS NOT NULL AND s.llm_score >= ? AND s.llm_score < ?"
        applied = db.scalar(f"SELECT COUNT(*) {base}", (lo, hi)) or 0
        positive = db.scalar(f"SELECT COUNT(*) {base} AND a.current_status IN ({q})", (lo, hi, *POSITIVE)) or 0
        out.append(BucketRate(name, applied, positive))
    return out
