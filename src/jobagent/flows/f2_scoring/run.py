"""F2 worker: DISCOVERED -> (JD_PARTIAL) -> EXTRACTED -> SCORED | MAYBE | REJECTED."""
import time
from dataclasses import dataclass

from jobagent.core import queue
from jobagent.core import statuses as st
from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.llm import ExtractionFailed, LLMClient
from jobagent.core.logging import get_logger
from jobagent.core.schemas import Profile
from jobagent.flows.f0_profile.versioning import hash_for_versioning
from jobagent.flows.f2_scoring.extractor import extract_jd
from jobagent.flows.f2_scoring.fetcher import HttpGet, fetch_jd
from jobagent.flows.f2_scoring.scorer import bucket, score

log = get_logger("jobagent.scoring")


@dataclass
class ScoringSummary:
    processed: int = 0
    failed: int = 0
    extraction_failed: int = 0


def process_job(db: Database, job, profile: Profile, http_get: HttpGet, llm: LLMClient | None, settings: Settings,
                sleep=time.sleep) -> str:
    text, partial = fetch_jd(job["apply_url"] or job["canonical_url"], job["snippet"], http_get, sleep=sleep)
    if partial:
        queue.advance(db, job["id"], st.JD_PARTIAL, note="JD page blocked or empty; using email snippet")
    jd = extract_jd(text, job["title"], job["company"], job["location"], llm, job["id"])
    db.write("UPDATE jobs SET jd_raw=?, jd_json=? WHERE id=?", (text, jd.model_dump_json(), job["id"]))
    if not partial:
        queue.advance(db, job["id"], st.EXTRACTED)
    sr = score(jd, job["title"], profile, db.now(), llm, job["id"])
    db.write("INSERT OR REPLACE INTO job_scores(job_id, llm_score, breakdown, reason, model, profile_hash, scored_at)"
             " VALUES (?,?,?,?,?,?,?)",
             (job["id"], sr.total, sr.model_dump_json(exclude={"reason"}), sr.reason,
              "llm" if llm else "rules", hash_for_versioning(profile), db.now_iso()))
    new_status = bucket(sr.total, settings)
    queue.advance(db, job["id"], new_status, note=f"score {sr.total}")
    return new_status


def run_scoring(db: Database, profile: Profile, http_get: HttpGet, llm: LLMClient | None, settings: Settings,
                worker: str = "f2", batch: int = 20, sleep=time.sleep) -> ScoringSummary:
    summary = ScoringSummary()
    for _ in range(batch):
        job = queue.claim(db, st.DISCOVERED, worker, settings.lease_min)
        if job is None:
            break
        try:
            process_job(db, job, profile, http_get, llm, settings, sleep)
            summary.processed += 1
        except ExtractionFailed as e:
            queue.advance(db, job["id"], st.EXTRACTION_FAILED, error=str(e))
            summary.extraction_failed += 1
        except Exception as e:  # one bad job must not stop the batch (SAF-04)
            log.error("job %s failed: %s", job["id"], e)
            queue.fail(db, job["id"], str(e), settings.max_attempts)
            summary.failed += 1
    return summary
