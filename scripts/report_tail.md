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
