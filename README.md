# Naukri Job Scraper

Reads Naukri job links from an Excel file, opens each one in a browser, and writes the job details to a new Excel file.

## What it extracts

| Column | Description |
|---|---|
| `link` | The job URL from your input file |
| `job_role` | Job title |
| `company` | Hiring company |
| `exp_min_years` | Lower limit of experience |
| `exp_max_years` | Upper limit of experience |
| `package` | Salary as shown ("Not Disclosed" when hidden) |
| `work_mode` | Remote, Hybrid or Office (inferred, see limitations) |
| `location` | Job location(s) |
| `apply_on_company_site` | Yes/No (see limitations) |
| `posted` | When the job was posted, e.g. "3 days ago" |
| `job_description` | Full description text |
| `key_skills` | Comma-separated skills |
| `status` | `ok`, `skipped ...`, `job expired/removed ...` or `error: ...` |

## Setup

Requires Python 3.9+.

```bash
pip install playwright pandas openpyxl
python -m playwright install chromium
```

## Usage

1. Put your links in an Excel file. Use a column headed `link` (or `url`); if there is no such header, the first column is used. A file with no header row also works.
2. Run:

```bash
python naukri_scraper.py Jobs.xlsx Jobs_output.xlsx
```

The output file name is optional and defaults to `naukri_output.xlsx`.

A Chrome window opens and visits each link with a 3 second pause between them. Leave it open until the script prints `Saved ...`. The output file is rewritten after every link, so a crash will not lose earlier rows.

## How it works

- Naukri builds job pages with JavaScript, so a plain HTTP request returns an empty page. The script uses Playwright to run a real browser and read the rendered page.
- Fields are read from Naukri's page elements, with text and JSON-LD fallbacks.
- Duplicate links are scraped once.
- Links that are not individual job listings (company pages, search pages, other sites) are skipped and marked in `status`.
- Naukri redirects expired jobs to a search page. The script detects the redirect and marks the row `job expired/removed`.

## Limitations

- **Headless mode is blocked.** Naukri returns "Access Denied" to headless browsers, so the script runs with a visible window. The `--headless` flag exists but does not work against Naukri.
- **Blocking is still possible.** Scraping many links quickly may get you blocked. Increase the `time.sleep(3)` delay in `main()` or use a proxy service if that happens.
- **`apply_on_company_site` is unreliable.** When logged out, Naukri showed a plain "Apply" button on every job tested, so this column was "No" for all of them. It probably does not reflect the real answer. A logged-in session may be needed.
- **`work_mode` is inferred** from the location text and the top of the page, so unusual listings may be wrong.
- **Selectors are tied to Naukri's current markup.** Naukri may change class names, which would break extraction. Check `status` and empty columns after a run.
- **LinkedIn and AmbitionBox links are not supported.** They are skipped.

## Terms of use

Automated scraping may be against Naukri's terms of service. Use this for small-scale personal use and respect the site's rules.
