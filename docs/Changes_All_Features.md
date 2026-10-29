# Changes made: implementation of all 50 features

Follows `Job_Pipeline_Agent_LLD.docx` (module layout, DB schema, status machine, flows F0-F7). PRF-01 was delivered first (see `PRF-01_Changes.md`); this document covers everything added after it. Test evidence: `Test_Report_All_Features.md`.

## What exists now

```
src/jobagent/
  core/        statuses.py  db.py  queue.py  config.py  llm.py  logging.py  notify.py  mail.py  similarity.py  lexicon.py  schemas.py
  flows/
    f0_profile/    builder.py loader.py sensitive.py prefs.py versioning.py view.py extractor.py     PRF-01..04
    f1_discovery/  gmail_source.py normalizer.py prefilter.py run.py                                DIS-01..05
    f2_scoring/    fetcher.py extractor.py scorer.py run.py digest.py                               SCR-01..05
    f3_resume/     tailor.py validator.py graph.py renderer.py run.py models.py                     RES-01..05, SAF-03
    f4_formfill/   snapshot.py mapper.py resolver.py answer_bank.py filler.py guards.py run.py      FRM-01..07
    f5_review/     review.py decide.py submit.py                                                    REV-01..06
    f6_status/     matcher.py classifier.py run.py                                                  STA-01..05
    f7_feedback/   metrics.py cleanup.py evals.py golden/*.json baseline.json                       FBK-01..04
  cli.py                                                                                           build-profile, check-profile, set-sensitive
config/        settings.yaml (auto_submit: false)   search_prefs.yaml
prompts/       profile_extract, jd_extract, score, tailor, form_answer, field_map  (.md, not inline strings)
tests/         210 automated tests, fixtures/emails/*.eml, forms.py (local dummy application forms)
scripts/       make_golden.py  apply_results.py  build_report.py
```

## Where jobs come from (updated)

Jobs are collected by **scraping Naukri job links** with `naukri_scraper.py`'s logic (moved to `f1_discovery/naukri_scrape.py`; the original `naukri_scraper.py` is now a thin wrapper with the same command line). The Gmail alert-email path (`run_discovery`) is still in the code but needs a Gmail client that does not exist yet.

```bash
# 1. put Naukri job links in an Excel file with a 'link' column (like Jobs.xlsx)
# 2. edit config/search_prefs.yaml (keywords, experience, locations, max age)
python -m jobagent.cli collect-naukri Jobs.xlsx --max-age-days 7   # opens Chrome, scrapes, filters, de-dupes, saves to data/jobagent.db
python -m jobagent.cli score --profile data/profile.json            # extract + score (rule-based; add --llm for the model)
python -m jobagent.cli digest                                       # Apply / Maybe list
```
- Each scraped job is stored with its **full description**, so scoring does not fetch the page again.
- The same filters, de-duplication and alerts apply as for email jobs (a job seen in both places is one row).
- New files: `naukri_scrape.py`, `scraper_source.py`; changed: `f1_discovery/run.py` (shared `Ingest` + `run_scraper_discovery`), `prefilter.py` (wider default keywords, 4+ letter keywords match longer words), `f2_scoring/run.py` (uses stored JD), `cli.py` (`collect-naukri`, `score`, `digest`), `config/search_prefs.yaml` (broad starter prefs).

## Dashboard (UI to track everything)

```bash
python -m jobagent.cli ui                 # opens http://localhost:8501 on YOUR data/jobagent.db
python -m jobagent.cli ui --demo          # same UI on a separate database full of FAKE demo data
```
Local only (Streamlit, reads the same SQLite file the pipeline writes). Code: `src/jobagent/ui/` (`data.py` = queries and actions, `app.py` = pages, `demo.py` = fake data).

| Page | What you see / do |
|---|---|
| **Overview** | Key numbers (jobs found, Apply, Maybe, ready to review, submitted, interviews), today's submits vs the daily cap, a **"Needs your attention"** list (NEEDS_HUMAN, submit without confirmation, filled-awaiting-approval, unmatched emails, interviews, failed jobs, missing profile / sensitive fields) with an Open button for each, pipeline chart by status, 7-day funnel, response rate by score bucket, LLM spend |
| **Jobs** | Every job with filters (status, source, min score, search). Tick a row: score breakdown with the reason, extracted skills/experience/salary, full JD, status history; buttons **Apply anyway** (Maybe/Reject) and **Skip** |
| **Review** | Filled / needs-you applications: why the agent stopped, every answer with its source and confidence (yellow = check), edit and Save (remembered in the Answer Bank), form screenshots, resume diff and PDF download, **Approve and submit** (locked behind a confirmation tick; opens a visible browser; respects the daily cap and the duplicate guard) and Skip |
| **Applications** | Submitted applications with days since submit and **days until GHOSTED**, email/status history, confirmation screenshot, manual status change |
| **Inbox** | Emails the agent could not match or understand: attach to an application with a status, or dismiss |
| **Answer Bank** | Saved answers: edit (marks human-approved), delete, run cleanup |
| **Health** | auto-submit / cap settings, profile status and versions, LLM calls and cost per flow, recent status changes |

## How each feature is implemented

### 1. Profile
- **PRF-02** `sensitive.py`: `startup_check()` warns (or raises with `strict=True`) for empty `sensitive.*`; `set_sensitive()` is the only writer and validates types. The LLM output schema has **no** sensitive section, and every LLM prompt is built from `profile_for_llm()`, which strips `sensitive` and contact details.
- **PRF-03** `prefs.py`: `SearchPrefs` (keywords, experience range, locations, max age); `exp_min > exp_max` is a validation error. Discovery filters use these values.
- **PRF-04** `versioning.py`: content hash (version number excluded) stored in `profile_versions`; unchanged content keeps its hash, an edit gets a new one; `applications.profile_hash` keeps the hash that was used.

### 2. Discovery
- Parsers per source (`LinkedInAlertParser`, `NaukriAlertParser`); a mail that looks like an alert but yields no jobs raises `ParserError` (logged + alert, other mails still processed).
- `prefilter.passes()`: age (exactly 3 days kept; unknown date kept and flagged `posted_date_missing`), title blacklist, whitelist, location, experience. **Documented rule: blacklist beats whitelist** ("Senior AI Sales Engineer" is rejected).
- Dedupe by `sha1(company|title|city)` and canonical URL (tracking params stripped); `processed_emails` makes a re-run harmless.
- Alerts: `zero_jobs`, `auth_failed`, `parser_failed`.

### 3. Scoring
- `fetcher`: login wall / 4xx / empty page -> email snippet and `JD_PARTIAL`; HTTP 429 backed off 1/2/4 s.
- `extractor`: LLM or rule-based; **guards drop any skill or salary the JD text does not contain**.
- `scorer`: components -> **total always recomputed in code**; missing salary forced to neutral 8; "AI"-labelled support/QA jobs capped at role_type 3; buckets 70/50.
- `digest`: Apply bucket first, with score and reason; a short "No new matches" message instead of an empty digest. `manual_apply` / `skip_job` implement SCR-05 (a skipped job is not re-added because its dedupe key remains).

### 4. Resume tailoring
- Bullet/project/skill **ordering is done in code** by relevance to the JD; an LLM may only rephrase.
- `validator.validate()` rejects: new numbers, new tools/skills, new proper nouns, changed company/role/dates, unknown or wrong-owner bullet ids, skills outside the profile, inflated summary; optional LLM second pass (`LLMClaimChecker`).
- `run_tailor_loop`: 2 attempts, then the **base resume with `fallback=True`** (stored in `applications.resume_flag`).
- `renderer`: single-column text PDF (reportlab), no tables/images, shrinks font then trims bullets to stay within 2 pages; `diff_lines/diff_html/unified_diff` for the diff view.

### 5. Form filling
- `snapshot.take_snapshot()` reads visible fields, stamps `data-jaref`, and detects CAPTCHA, login wall and unknown widgets.
- `mapper`: regex shortcuts (no LLM) for personal/sensitive/experience/consent/resume; everything else is a custom question (optional LLM mapper).
- `resolver`: profile -> Answer Bank (similarity >= 0.90) -> LLM draft (<= 80 words, `needs_review`, choices constrained to the real options). **Sensitive fields are never sent to the LLM; a missing value leaves the field empty and the job goes to `NEEDS_HUMAN`.**
- `guards`: `safe_click()` blocks submit-like buttons (`allow_submit=False` hard default) and a page-level script cancels any `submit` event during the fill phase.
- `run.fill_application`: up to 8 pages, 3 retries, per-page screenshot, rows in `form_answers`, stops before submit; idempotent (a finished job is a no-op).

### 6. Review and submit
- `review.py` renders a standalone HTML review page (screenshots, answer table with `needs_review` rows highlighted and editable, resume diff).
- `decide.py`: `approve` / `skip` / `edit_answer` (edits saved to the Answer Bank with `human_approved=1`), daily cap (default 15), random 45-120 s gap between submits, `maybe_auto_submit` (raises unless `auto_submit: true`).
- `submit.py`: replays the reviewed answers, **aborts to `NEEDS_HUMAN` without clicking submit if the form changed**, saves a pre-submit and a confirmation screenshot with timestamp, and records `SUBMIT_UNCERTAIN` (never auto-retried) when no confirmation appears. Duplicate applications are refused.

### 7. Status tracking
- `matcher`: `0.5*token_set(company) + 0.3*partial(subject, title) + 0.2*domain`; needs score > 80 **and** margin > 10, else the email goes to `manual_review`.
- `classifier`: rule-based labels (received / under_review / shortlisted / interview_scheduled / rejected / other) and interview date+time extraction (a time is required; no time means an alert but no calendar event).
- `run_status_check`: 48 h window, newsletters ignored, status never moves backwards, interview alert with a calendar-event suggestion; `check_ghosted` marks GHOSTED after 14 days without activity.

### 8. Feedback
- `weekly_funnel` (discovered / applied / responses / interviews; an automatic "received" does not count as a response), `bucket_response_rates` (empty bucket = `n/a`, never a division error), `cleanup_answer_bank` (merge identical, flag conflicts, never touch human-approved), `evals` (golden-set accuracy + regression check against `baseline.json`).

### 9. Safety and 10. Platform
- `auto_submit` defaults to false in code and in `config/settings.yaml`.
- `queue.fail` retries up to 3 times (one per scheduled run), then `FAILED`; a stale lease lets another worker re-claim a crashed job.
- `llm.py` logs every call (tokens, cost, latency, redacted prompt) to `llm_calls`; `logging.py` redacts passwords, tokens, API keys and CTC values from every log line; `job_history` records every status change.
- `Database(dry_run=True)` executes the flow, logs each skipped write and changes nothing.
- 429 handling: exponential backoff (1, 2, 4 s) for the LLM and for JD fetching.
- `statuses.TRANSITIONS` is the single source of truth; an illegal move raises before anything is written.

## Differences from the LLD (deliberate)

| LLD | What I did | Why |
|---|---|---|
| SQLAlchemy + Alembic | plain `sqlite3`, schema in `core/db.py` | fewer dependencies for a single-user tool; swap later if needed |
| LangGraph loops | plain Python loops | each loop has one cycle; LangGraph is not installed |
| Playwright HTML->PDF | reportlab | no browser needed, simple ATS-safe output |
| Streamlit review UI | generated HTML review page | Streamlit not installed |
| sentence-transformers embeddings | char-trigram cosine (`core/similarity.py`) | offline; the embedder is a swappable function |
| LLM for every extract/score | rule-based extractor/scorer used when no LLM is given | lets the pipeline and tests run offline |
| "total_years" etc. from LLM | computed in code from profile dates | cannot be hallucinated |

## Not built (be aware)

- **Real Gmail client (OAuth)**, **scheduler** (daily/15-min/48-h jobs), **Telegram/email delivery**, **Streamlit UI**. The interfaces (`MailSource`, `Notifier`, `DigestChannel`) exist and all logic is tested against fakes.
- The real LLM backend (`core/llm.langchain_backend`, Groq) is written but has never been called.
- Resume-from-PDF OCR for scanned files.

## Other changes

- `Job_Pipeline_Agent_TestCases.xlsx`: Status / Actual Result / Remarks filled for all 115 test cases.
- `.gitignore`, `pyproject.toml`, `config/`, `prompts/`, `tests/`, `scripts/` added as listed above.
