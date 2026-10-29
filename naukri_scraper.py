"""Scrape Naukri job links listed in an Excel file.

Usage:
    python naukri_scraper.py input.xlsx [output.xlsx] [--headless]

The input Excel needs a column called "link" (or "url"); if no such header
exists, the first column is used. Output is written to output.xlsx
(default: naukri_output.xlsx).

The scraping logic now lives in src/jobagent/flows/f1_discovery/naukri_scrape.py (shared with the job agent).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402

from jobagent.flows.f1_discovery.naukri_scrape import COLUMNS, read_links, scrape_links  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headless = "--headless" in sys.argv
    if not args:
        sys.exit(__doc__)
    src = args[0]
    out = args[1] if len(args) > 1 else "naukri_output.xlsx"

    urls = read_links(src)
    rows = []
    for row in scrape_links(urls, headless=headless,
                            on_progress=lambda i, n, url: print(f"[{i}/{n}] {url[:90]}", flush=True)):
        if str(row.get("status", "")).startswith("error"):
            print("   failed:", row["status"])
        rows.append(row)
        pd.DataFrame(rows, columns=COLUMNS).to_excel(out, index=False)  # save as we go
    print("Saved", out)


if __name__ == "__main__":
    main()
