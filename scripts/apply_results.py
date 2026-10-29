"""Reads pytest's junit XML and writes the results into Job_Pipeline_Agent_TestCases.xlsx (Status / Actual Result / Remarks),
then prints a per-feature summary used by the report.

Usage: pytest --junitxml=junit.xml ; python scripts/apply_results.py junit.xml
A TC is 'Pass' only if at least one test carries its id (test_tcNNN_...) and every such test passed.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "Job_Pipeline_Agent_TestCases.xlsx"

# What a reader must know about HOW each feature was tested (shown in the Remarks column and the report).
CAVEAT = {
    "PRF-01": "LLM stubbed: checks our PDF/validation/date/safety code, not a real model's accuracy.",
    "DIS": "Synthetic .eml fixtures (tests/fixtures/emails), not real captured alerts; Gmail is a fake MailSource.",
    "SCR-01": "LLM stubbed. Rule-based extractor also tested. No real model measured.",
    "SCR-02": "TC-030/031/033 use the deterministic rule scorer; TC-032/034 use a stubbed LLM. A live model's score consistency was not measured.",
    "SCR-03": "LLM stubbed to emit exact component totals.",
    "SCR-04": "Digest channel is an in-memory fake (no real email/Telegram).",
    "RES": "LLM stubbed. Ordering is done in code. PDF made with reportlab (LLD said Playwright).",
    "FRM": "Real headless Chromium on local dummy forms; LLM stubbed; no real ATS/site was touched.",
    "REV": "Real headless Chromium on local dummy forms; no real employer site. Time/delay uses a fake clock.",
    "STA": "Gmail is a fake MailSource; classifier is rule-based (LLM fallback not exercised).",
    "FBK-04": "20 hand-written golden forms (189 fields), not captured from real sites. First run 96.8%; rules were then fixed to 100% on this same set.",
    "SAF": "",
    "PLT": "",
}
EXTRA = {
    "TC-057": "Similarity is char-trigram cosine (offline), not a semantic embedding model.",
    "TC-058": "Similarity is char-trigram cosine (offline), not a semantic embedding model.",
    "TC-025": "Auth failure simulated by a MailSource that raises MailAuthError.",
    "TC-108": "Crash simulated by claiming a job and never finishing it.",
    "TC-033": "Deterministic scorer returns identical scores (diff 0).",
    "TC-004": "Verified in the PRF-01 test file; sensitive section is structurally unreachable for the LLM.",
}


def caveat_for(feature_id: str) -> str:
    return CAVEAT.get(feature_id) or CAVEAT.get(feature_id.split("-")[0], "")


def main(junit: str):
    results: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for case in ET.parse(junit).getroot().iter("testcase"):
        ok = not any(c.tag in ("failure", "error") for c in case)
        for tc in set(re.findall(r"tc(\d{3})", case.get("name", ""))):
            results[f"TC-{tc}"].append((case.get("name"), ok))

    wb = openpyxl.load_workbook(XLSX)
    ws = wb["Test Cases"]
    hdr = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(hdr)}
    per_feature: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in ws.iter_rows(min_row=2):
        tc, feat = row[col["TC ID"]].value, row[col["Feature ID"]].value
        if not tc:
            continue
        tests = results.get(tc, [])
        if not tests:
            status, actual = "Not Run", "No automated test carries this TC id."
        elif all(ok for _, ok in tests):
            status = "Pass"
            actual = f"{len(tests)} automated test(s) passed: " + "; ".join(n.split('[')[0].removeprefix(f'test_{tc.lower().replace("-", "")}_') for n, _ in tests[:3]) + ("; ..." if len(tests) > 3 else "")
        else:
            status = "Fail"
            actual = "Failed: " + "; ".join(n for n, ok in tests if not ok)
        row[col["Status"]].value = status
        row[col["Actual Result"]].value = actual
        row[col["Remarks"]].value = " ".join(x for x in (caveat_for(feat), EXTRA.get(tc, "")) if x) or None
        per_feature[feat].append((tc, status))
    wb.save(XLSX)

    summary = {f: v for f, v in per_feature.items()}
    (Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "scripts" / "last_results.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    total = sum(len(v) for v in summary.values())
    passed = sum(s == "Pass" for v in summary.values() for _, s in v)
    print(f"{passed}/{total} test cases Pass; features: {len(summary)}")
    for f, v in summary.items():
        bad = [(t, s) for t, s in v if s != "Pass"]
        if bad:
            print("  NOT PASSING:", f, bad)


if __name__ == "__main__":
    main(sys.argv[1])
