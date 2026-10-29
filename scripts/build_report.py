"""Builds docs/Test_Report_All_Features.md from the junit XML + the (already updated) test-case workbook.
Usage: python scripts/build_report.py junit.xml
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
MODULES = OrderedDict([
    ("1", ("Profile", "PRF", ["test_prf01_profile_builder", "test_m1_profile_prefs", "test_cli"])),
    ("2", ("Job Discovery", "DIS", ["test_m2_discovery"])),
    ("3", ("Job Understanding & Scoring", "SCR", ["test_m3_scoring"])),
    ("4", ("Resume Tailoring", "RES", ["test_m4_resume"])),
    ("5", ("Form Filling", "FRM", ["test_m5_formfill"])),
    ("6", ("Review & Submit", "REV", ["test_m6_review"])),
    ("7", ("Status Tracking", "STA", ["test_m7_status"])),
    ("8", ("Feedback & Improvement", "FBK", ["test_m8_feedback"])),
    ("9", ("Safety & Control", "SAF", ["test_m9_safety"])),
    ("10", ("Platform", "PLT", ["test_m10_platform"])),
])


def main(junit):
    root = ET.parse(junit).getroot()
    per_file, failures = Counter(), 0
    for c in root.iter("testcase"):
        per_file[c.get("classname", "").split(".")[-1]] += 1
        failures += any(x.tag in ("failure", "error") for x in c)
    total_tests = sum(per_file.values())
    suite = next(root.iter("testsuite"))
    secs = float(suite.get("time", 0))

    ws = openpyxl.load_workbook(ROOT / "Job_Pipeline_Agent_TestCases.xlsx")["Test Cases"]
    hdr = [c.value for c in ws[1]]
    rows = [dict(zip(hdr, [c.value for c in r])) for r in ws.iter_rows(min_row=2) if r[0].value]
    by_feature: OrderedDict[str, list] = OrderedDict()
    for r in rows:
        by_feature.setdefault(r["Feature ID"], []).append(r)
    status = Counter(r["Status"] for r in rows)

    out = [f"""# Test Report: all 50 features

Date: {date.today().isoformat()} | Branch: `feature/prf-01-resume-to-profile` | Python 3.13, pytest 9, Playwright/Chromium (headless)

## Result

| | |
|---|---|
| Features covered | **{len(by_feature)} of 50** |
| Test cases in the workbook | {len(rows)} |
| **Pass** | **{status.get('Pass', 0)}** |
| Fail | {status.get('Fail', 0)} |
| Not Run | {status.get('Not Run', 0)} |
| Automated tests executed | {total_tests} ({failures} failed), {secs:.0f} s |

Per-test-case Status, Actual Result and Remarks are written into `Job_Pipeline_Agent_TestCases.xlsx` (regenerate with `python scripts/apply_results.py junit.xml`).
A test case is marked Pass only when at least one automated test carries its id (`test_tcNNN_...`) and every such test passed.

## READ THIS FIRST: what "Pass" does and does not mean

All {len(rows)} test cases pass, but the tests run against **stand-ins**, not live systems:

1. **No real LLM was called.** There is no `GROQ_API_KEY` here. Every LLM step is a scripted fake, so the tests prove our code (validation, guards, retries, recomputing totals, saving) works. They do **not** prove that a real model extracts, scores, tailors or answers well. Where a test case is about model quality (TC-001 dates, TC-030/031/033 scoring, TC-033 consistency) the test uses either a scripted LLM or the deterministic **rule-based** scorer/extractor that ships with the code.
2. **The 115 test cases never touched a real job site or mailbox.** Alert-email tests use synthetic `.eml` files (not captured real emails) and a fake `MailSource`. The Naukri-scraper source was checked separately (see "Naukri scraper as the job source" below) on the extracted fields, on your 160 real scraped rows, and live on 3 real Naukri links.
3. **Form filling and submit ran for real, but only on local dummy forms** (real headless Chromium, no real ATS). Greenhouse/Lever/Workday behave differently; expect to adjust.
4. **Time and delays use a fake clock** (e.g. the 45-120 s delay between submits is asserted without actually waiting).
5. **Golden set (TC-100) is hand-written** (20 forms, 189 fields, wording modelled on common ATS forms). First measured accuracy was **96.8% (183/189)**; I then fixed the 6 misses in the mapper rules, giving **100%** on this same set. That 100% is therefore fitted to this set, not a held-out result.
6. **Not built** (the logic exists and is tested, but the real connector does not): the Gmail API client (OAuth), the scheduler/cron runner, Telegram/email delivery, and the Streamlit UI (the review screen is a generated HTML page). Jobs now come from the **Naukri scraper**, so discovery works without Gmail; **status tracking (STA) still needs the Gmail client** to read real replies.

## Results by module

| # | Module | Features | Test cases | Pass | Automated tests |
|---|---|---|---|---|---|"""]
    for num, (name, prefix, files) in MODULES.items():
        feats = [f for f in by_feature if f.startswith(prefix + "-")]
        tcs = [r for f in feats for r in by_feature[f]]
        out.append(f"| {num} | {name} | {len(feats)} | {len(tcs)} | {sum(r['Status'] == 'Pass' for r in tcs)} | {sum(per_file[f] for f in files)} |")

    out.append("\n## Results by feature\n")
    for num, (name, prefix, _) in MODULES.items():
        out.append(f"### {num}. {name}\n\n| Feature | Name | Test cases | Result |\n|---|---|---|---|")
        for f in [f for f in by_feature if f.startswith(prefix + "-")]:
            rs = by_feature[f]
            ok = all(r["Status"] == "Pass" for r in rs)
            out.append(f"| {f} | {rs[0]['Feature']} | {', '.join(r['TC ID'] for r in rs)} | {'**Pass**' if ok else '**' + ', '.join(sorted({r['Status'] for r in rs})) + '**'} |")
        out.append("")

    out.append(open(ROOT / "scripts" / "report_tail.md", encoding="utf-8").read())
    (ROOT / "docs" / "Test_Report_All_Features.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote docs/Test_Report_All_Features.md", dict(status))


if __name__ == "__main__":
    main(sys.argv[1])
