# Test Report: all 50 features

Date: 2026-10-29 | Branch: `feature/prf-01-resume-to-profile` | Python 3.13, pytest 9, Playwright/Chromium (headless)

## Result

| | |
|---|---|
| Features covered | **50 of 50** |
| Test cases in the workbook | 115 |
| **Pass** | **115** |
| Fail | 0 |
| Not Run | 0 |
| Automated tests executed | 268 (0 failed), 70 s |

Per-test-case Status, Actual Result and Remarks are written into `Job_Pipeline_Agent_TestCases.xlsx` (regenerate with `python scripts/apply_results.py junit.xml`).
A test case is marked Pass only when at least one automated test carries its id (`test_tcNNN_...`) and every such test passed.

## READ THIS FIRST: what "Pass" does and does not mean

All 115 test cases pass, but the tests run against **stand-ins**, not live systems:

1. **No real LLM was called.** There is no `GROQ_API_KEY` here. Every LLM step is a scripted fake, so the tests prove our code (validation, guards, retries, recomputing totals, saving) works. They do **not** prove that a real model extracts, scores, tailors or answers well. Where a test case is about model quality (TC-001 dates, TC-030/031/033 scoring, TC-033 consistency) the test uses either a scripted LLM or the deterministic **rule-based** scorer/extractor that ships with the code.
2. **The 115 test cases never touched a real job site or mailbox.** Alert-email tests use synthetic `.eml` files (not captured real emails) and a fake `MailSource`. The Naukri-scraper source was checked separately (see "Naukri scraper as the job source" below) on the extracted fields, on your 160 real scraped rows, and live on 3 real Naukri links.
3. **Form filling and submit ran for real, but only on local dummy forms** (real headless Chromium, no real ATS). Greenhouse/Lever/Workday behave differently; expect to adjust.
4. **Time and delays use a fake clock** (e.g. the 45-120 s delay between submits is asserted without actually waiting).
5. **Golden set (TC-100) is hand-written** (20 forms, 189 fields, wording modelled on common ATS forms). First measured accuracy was **96.8% (183/189)**; I then fixed the 6 misses in the mapper rules, giving **100%** on this same set. That 100% is therefore fitted to this set, not a held-out result.
6. **Not built** (the logic exists and is tested, but the real connector does not): the Gmail API client (OAuth), the scheduler/cron runner, Telegram/email delivery, and the Streamlit UI (the review screen is a generated HTML page). Jobs now come from the **Naukri scraper**, so discovery works without Gmail; **status tracking (STA) still needs the Gmail client** to read real replies.

## Results by module

| # | Module | Features | Test cases | Pass | Automated tests |
|---|---|---|---|---|---|
| 1 | Profile | 4 | 9 | 9 | 34 |
| 2 | Job Discovery | 5 | 16 | 16 | 18 |
| 3 | Job Understanding & Scoring | 5 | 15 | 15 | 22 |
| 4 | Resume Tailoring | 5 | 11 | 11 | 15 |
| 5 | Form Filling | 7 | 15 | 15 | 39 |
| 6 | Review & Submit | 6 | 14 | 14 | 18 |
| 7 | Status Tracking | 5 | 13 | 13 | 24 |
| 8 | Feedback & Improvement | 4 | 8 | 8 | 12 |
| 9 | Safety & Control | 5 | 10 | 10 | 19 |
| 10 | Platform | 4 | 4 | 4 | 9 |

## Results by feature

### 1. Profile

| Feature | Name | Test cases | Result |
|---|---|---|---|
| PRF-01 | Resume se profile banta hai | TC-001, TC-002, TC-003 | **Pass** |
| PRF-02 | Sensitive details sirf user bharta hai | TC-004, TC-005 | **Pass** |
| PRF-03 | Search preferences | TC-006, TC-007 | **Pass** |
| PRF-04 | Profile versioning | TC-008, TC-009 | **Pass** |

### 2. Job Discovery

| Feature | Name | Test cases | Result |
|---|---|---|---|
| DIS-01 | Job alerts roz uthte hain | TC-010, TC-011, TC-012, TC-013 | **Pass** |
| DIS-02 | Sirf pichhle 3 din ki jobs | TC-014, TC-015, TC-016, TC-017 | **Pass** |
| DIS-03 | Duplicate removal | TC-018, TC-019, TC-020 | **Pass** |
| DIS-04 | Irrelevant titles filter | TC-021, TC-022, TC-023 | **Pass** |
| DIS-05 | Zero jobs / source fail alert | TC-024, TC-025 | **Pass** |

### 3. Job Understanding & Scoring

| Feature | Name | Test cases | Result |
|---|---|---|---|
| SCR-01 | JD se details extract | TC-026, TC-027, TC-028, TC-029 | **Pass** |
| SCR-02 | Score 0-100 + reason | TC-030, TC-031, TC-032, TC-033, TC-034 | **Pass** |
| SCR-03 | Apply / Maybe / Reject buckets | TC-035, TC-036 | **Pass** |
| SCR-04 | Daily digest | TC-037, TC-038 | **Pass** |
| SCR-05 | Manual apply / skip | TC-039, TC-040 | **Pass** |

### 4. Resume Tailoring

| Feature | Name | Test cases | Result |
|---|---|---|---|
| RES-01 | JD ke hisaab se rephrase | TC-041, TC-042 | **Pass** |
| RES-02 | Sirf actual skills (no fabrication) | TC-043, TC-044, TC-045 | **Pass** |
| RES-03 | Claim verification | TC-046, TC-047 | **Pass** |
| RES-04 | Diff view | TC-048 | **Pass** |
| RES-05 | ATS-friendly PDF | TC-049, TC-050, TC-051 | **Pass** |

### 5. Form Filling

| Feature | Name | Test cases | Result |
|---|---|---|---|
| FRM-01 | Auto-fill | TC-052, TC-053 | **Pass** |
| FRM-02 | Personal details profile se | TC-054, TC-055 | **Pass** |
| FRM-03 | Answer Bank reuse | TC-056, TC-057, TC-058 | **Pass** |
| FRM-04 | Subjective answer draft | TC-059, TC-060 | **Pass** |
| FRM-05 | Answer log | TC-061 | **Pass** |
| FRM-06 | CAPTCHA / unknown field handling | TC-062, TC-063, TC-064 | **Pass** |
| FRM-07 | Approval ke bina submit nahi | TC-065, TC-066 | **Pass** |

### 6. Review & Submit

| Feature | Name | Test cases | Result |
|---|---|---|---|
| REV-01 | Review screen | TC-067, TC-068 | **Pass** |
| REV-02 | Approve / Edit / Skip | TC-069, TC-070, TC-071 | **Pass** |
| REV-03 | Edits yaad rehte hain | TC-072, TC-073 | **Pass** |
| REV-04 | Daily application limit | TC-074, TC-075 | **Pass** |
| REV-05 | Confirmation screenshot | TC-076, TC-077 | **Pass** |
| REV-06 | Duplicate application nahi | TC-078, TC-079, TC-080 | **Pass** |

### 7. Status Tracking

| Feature | Name | Test cases | Result |
|---|---|---|---|
| STA-01 | Gmail replies check | TC-081, TC-082 | **Pass** |
| STA-02 | Email se status | TC-083, TC-084, TC-085, TC-086 | **Pass** |
| STA-03 | Interview alert | TC-087, TC-088 | **Pass** |
| STA-04 | Ghosted detection | TC-089, TC-090, TC-091 | **Pass** |
| STA-05 | Unclear emails manual list | TC-092, TC-093 | **Pass** |

### 8. Feedback & Improvement

| Feature | Name | Test cases | Result |
|---|---|---|---|
| FBK-01 | Weekly funnel report | TC-094, TC-095 | **Pass** |
| FBK-02 | Score bucket response rate | TC-096, TC-097 | **Pass** |
| FBK-03 | Answer Bank cleanup | TC-098, TC-099 | **Pass** |
| FBK-04 | Accuracy test set | TC-100, TC-101 | **Pass** |

### 9. Safety & Control

| Feature | Name | Test cases | Result |
|---|---|---|---|
| SAF-01 | Auto-submit default off | TC-102, TC-103 | **Pass** |
| SAF-02 | Sensitive fields kabhi guess nahi | TC-104, TC-105 | **Pass** |
| SAF-03 | Fake claims block | TC-106 | **Pass** |
| SAF-04 | Failed jobs skip | TC-107, TC-108 | **Pass** |
| SAF-05 | Full logging | TC-109, TC-110, TC-111 | **Pass** |

### 10. Platform

| Feature | Name | Test cases | Result |
|---|---|---|---|
| PLT-01 | Idempotent runs | TC-112 | **Pass** |
| PLT-02 | Dry-run mode | TC-113 | **Pass** |
| PLT-03 | Rate limit handling | TC-114 | **Pass** |
| PLT-04 | Valid status transitions | TC-115 | **Pass** |

## Naukri scraper as the job source (added after the 115 test cases)

Jobs are collected by scraping the Naukri links in an Excel file (like `Jobs.xlsx`) with the existing scraper logic, instead of reading Gmail alerts.

| Check | Result |
|---|---|
| Field extraction on a Naukri-shaped page (real Chromium) | title, company, experience, salary, location, posted, skills, apply-site all extracted |
| Your 160 real scraped rows (`Jobs_output.xlsx`): 139 `ok` | all 139 convert to jobs; with a 365-day age limit 96 inserted, 14 duplicates, 29 filtered by title keywords; all 96 scored without any re-fetch (4 Apply, 57 Maybe, 35 Reject against the **sample** profile, so those buckets say nothing about you) |
| Live run of the real CLI on 3 real Naukri links | 3 scraped, 2 added, 1 filtered (before adding "Artificial Intelligence" to the keywords), 2 scored, digest printed |
| Same job from an alert email and the scraper | one row |
| All links fail / browser crash / zero new jobs | `source_failed` / `zero_jobs` alert, no crash |

Found while doing this: the default title keywords rejected "Artificial Intelligence Engineer" and "Data Scientist", and whole-word matching rejected "Agentic" for the keyword "Agent". Fixed (4+ letter keywords now match longer words; the blacklist stays whole-word so "Salesforce" is not caught by "sales"). Limits: Naukri blocks headless browsers, so a visible Chrome window opens; most links in `Jobs.xlsx` are older than 3 days and are dropped by the age rule unless you pass `--max-age-days`; scraping may be against Naukri's terms of service.

## Problems the tests found (and that were fixed)

| Where | Problem | Found by | Fix |
|---|---|---|---|
| `normalizer.canonical_url` | Naukri's `sid` tracking param was kept, so the same job from two alerts looked different | TC-019 | Naukri URLs are identified by path only; the query is dropped |
| `f3_resume/validator.py` | `v += ...` inside a nested function raised `UnboundLocalError` whenever a rewrite was checked | TC-042/043/044/046 | `v.extend(...)` |
| `f4_formfill/snapshot.py` | Field tokens from page 1 stayed on hidden elements, so page 2 matched two elements ("strict mode violation") and multi-page forms failed | TC-053 | Clear old tokens at the start of every snapshot |
| `f4_formfill/run.py` | The Answer Bank was only used if the caller passed one, so reuse silently never happened | TC-056/057 | Default to a bank on the same DB with the configured threshold |
| `f6_status/matcher.py` | An ambiguous two-role email was reported as "low score" instead of "ambiguous" (outcome was right, the reason was misleading) | TC-092 | Check ambiguity before the score floor |
| `core/queue.fail` | A failing job was re-claimed immediately, burning all 3 attempts inside one run | TC-107 | A failed job stays leased for one lease period and is retried on the next scheduled run |
| `core/queue` (dry run) | `claim` relied on a write, so a dry run could not process anything | TC-113 | Read-only claim plus an in-memory status overlay in dry-run mode |
| `f4_formfill/mapper.py` | 6 of 189 golden fields mapped wrongly (e.g. "When can you start?", "Location (City)", "Phone Device Type" was filled with the phone number) | TC-100 | Added general patterns, and an exclusion for "phone type / country code" |
| `cli.py` | My own patch wrote a literal newline into a string (syntax error) and was committed | manual CLI check | Fixed, and `tests/unit/test_cli.py` added so it cannot recur silently |

Test-side mistakes I also corrected: a false positive on `/ImageB` (a standard PDF header, not an image), two weak assertions (`or True`) that could never fail, and an extra LLM call from a dropdown that made three Answer Bank tests wrong.

## Are the tests able to fail? (mutation check)

I broke five safety mechanisms one at a time and confirmed the matching test failed each time (then restored the code):

| Broken on purpose | Test that caught it |
|---|---|
| Log redaction removed | TC-111 |
| Sensitive section sent to the LLM | TC-104 |
| Submit-button guard removed | TC-065 |
| Duplicate-application guard removed | TC-078 |
| LLM-supplied score total trusted | TC-032 |

5 of 5 were caught.

## How to re-run

```bash
pip install -e ".[dev]"
python -m playwright install chromium
python -m pytest --junitxml=junit.xml
python scripts/apply_results.py junit.xml      # updates the Excel workbook
python scripts/build_report.py junit.xml       # rebuilds this report
```
