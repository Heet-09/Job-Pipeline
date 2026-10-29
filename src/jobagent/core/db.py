import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jobagent.core.logging import get_logger

log = get_logger("jobagent.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  dedupe_key TEXT UNIQUE NOT NULL,
  canonical_url TEXT UNIQUE,
  source TEXT NOT NULL,
  title TEXT, company TEXT, location TEXT,
  posted_at TEXT, discovered_at TEXT,
  jd_raw TEXT, jd_json TEXT, snippet TEXT, apply_url TEXT,
  apply_type TEXT,
  status TEXT NOT NULL DEFAULT 'DISCOVERED',
  status_updated_at TEXT,
  locked_by TEXT, locked_at TEXT,
  attempts INTEGER DEFAULT 0, last_error TEXT,
  flags TEXT DEFAULT '', manual INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS job_history (
  id INTEGER PRIMARY KEY, job_id INTEGER, from_status TEXT, to_status TEXT, note TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS job_scores (
  job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
  embed_sim REAL, llm_score INTEGER, breakdown TEXT, reason TEXT, model TEXT,
  profile_hash TEXT, scored_at TEXT, digested_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  job_id INTEGER UNIQUE REFERENCES jobs(id),
  resume_path TEXT, resume_diff TEXT, resume_flag TEXT, profile_hash TEXT,
  filled_at TEXT, approved_at TEXT, submitted_at TEXT, confirmation_shot TEXT,
  current_status TEXT, last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS form_answers (
  id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES jobs(id),
  page_no INTEGER, field_ref TEXT, field_label TEXT, field_type TEXT,
  answer TEXT, source TEXT, confidence REAL,
  needs_review INTEGER DEFAULT 0, approved INTEGER DEFAULT 0, screenshot TEXT
);
CREATE TABLE IF NOT EXISTS answer_bank (
  id INTEGER PRIMARY KEY, canonical_question TEXT, answer TEXT,
  human_approved INTEGER DEFAULT 0, use_count INTEGER DEFAULT 0,
  needs_cleanup INTEGER DEFAULT 0, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS status_events (
  id INTEGER PRIMARY KEY, application_id INTEGER REFERENCES applications(id),
  status TEXT, email_id TEXT, snippet TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY, flow TEXT, job_id INTEGER, model TEXT,
  prompt_tokens INT, completion_tokens INT, cost_usd REAL, latency_ms INT,
  ok INTEGER, error TEXT, prompt TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS processed_emails (
  email_id TEXT PRIMARY KEY, kind TEXT, processed_at TEXT
);
CREATE TABLE IF NOT EXISTS manual_review (
  id INTEGER PRIMARY KEY, email_id TEXT, sender TEXT, subject TEXT, reason TEXT,
  created_at TEXT, resolved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS profile_versions (
  hash TEXT PRIMARY KEY, version INTEGER, saved_at TEXT, profile_json TEXT
);
"""


class _NoCursor:
    lastrowid = None
    rowcount = 0


class Database:
    """Thin sqlite wrapper. In dry-run mode every write is logged and skipped (PLT-02)."""

    def __init__(self, path: str | Path = ":memory:", dry_run: bool = False, clock=None):
        self.path = str(path)
        self.dry_run = dry_run
        self.clock = clock or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))
        self.skipped_writes: list[str] = []
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def now(self) -> datetime:
        return self.clock()

    def now_iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def write(self, sql: str, params=()):
        if self.dry_run:
            self.skipped_writes.append(sql.strip().split("(")[0][:80])
            log.info("[dry-run] would execute: %s", sql.strip()[:120])
            return _NoCursor()
        return self.conn.execute(sql, params)

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params=()):
        row = self.one(sql, params)
        return row[0] if row else None

    def close(self):
        self.conn.close()
