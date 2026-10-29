# Test Report: PRF-01 "Resume se profile banta hai"

Date: 2026-10-29 | Branch: `feature/prf-01-resume-to-profile` | Python 3.13.12, pytest 9.2.0

## Result

| TC ID | Type | Scenario | Result |
|---|---|---|---|
| TC-001 | Positive | Valid resume PDF -> profile with experience, projects, skills, correct dates | **Pass** |
| TC-002 | Negative | Scanned or corrupt PDF -> clear error, no empty profile saved | **Pass** |
| TC-003 | Edge | Resume with no projects section -> profile built with a warning | **Pass** |

3 of 3 test cases for PRF-01 pass. The full automated run is **24 passed, 0 failed** (0.7 s). The same run was repeated in a clean virtualenv with the declared dependencies and also gave 24 passed.

Per-case results are also written into the Status, Actual Result and Remarks columns of `Job_Pipeline_Agent_TestCases.xlsx`.

## How each case was tested

| TC | Tests (`tests/unit/test_prf01_profile_builder.py`) | What they check |
|---|---|---|
| TC-001 | `test_tc001_valid_resume_builds_profile_with_dates` | A real PDF is generated and read with pypdf. The saved JSON has both jobs, the project and the skills. Dates are normalised (`Jan 2022` -> `2022-01`, `Present` -> `present`, `Jun 2020` -> `2020-06`). Bullet ids are `e1b1` / `p1b1`. The file loads back through the schema. There are no warnings. |
| TC-002 | `test_tc002_corrupt_pdf_...`, `test_tc002_scanned_image_only_pdf_...`, `test_tc002_missing_file`, `test_tc002_extractor_returns_nothing_usable_...` | Random bytes give "could not read PDF". An image-only PDF gives "looks like a scanned/image-only PDF". A missing file gives "not found". An extractor that returns nothing gives "nothing usable". In every case `profile.json` does not exist afterwards. For bad PDFs the LLM is never called. |
| TC-003 | `test_tc003_no_projects_section_builds_profile_with_warning` | The profile is saved with `projects == []` and the warning "No projects section found". |

### Extra tests beyond the three test cases

| Test | Why |
|---|---|
| `test_tc004_ctc_in_resume_never_reaches_sensitive_fields`, `test_llm_output_schema_has_no_sensitive_field` | The resume text contains CTC and notice period, and every `sensitive.*` field stays null. This is **not** a formal TC-004 run (that belongs to PRF-02). It only confirms PRF-01 does not break the rule. |
| `test_rebuild_keeps_user_entered_sensitive_values` | Rebuilding from a resume does not wipe values the user typed in. |
| `test_hallucinated_company_is_dropped_with_warning`, `test_hallucinated_email_is_dropped` | Anything the LLM returns that is not in the resume text is dropped. |
| `test_unparseable_date_warns_and_is_left_empty` | A bad date is never guessed. |
| `test_dry_run_writes_nothing`, `test_normalize_date[...]` | Dry run writes nothing; 11 date formats are checked. |

## Limitations (please read)

1. **The LLM was stubbed in every test.** The tests show our code handles PDF reading, validation, date normalisation, safety rules and saving correctly. They do **not** show that a real model extracts a real resume accurately. TC-001's wording ("sahi dates ke saath") can only be fully confirmed with a real resume and a real model.
   - `GROQ_API_KEY` is not set in this environment, so no live call was made.
   - To run it live: set `GROQ_API_KEY`, then run `python -m jobagent.cli build-profile your_resume.pdf --dry-run`.
2. **The global Python environment cannot import `langchain_groq`.** The installed `langchain-core 0.3.28` is too old for `langchain-groq 1.1.2` (`ImportError: ModelProfile`). In a clean venv the real extractor builds correctly (checked with a dummy key), so the fix is to upgrade `langchain-core` or use a venv for this project.
3. **"Scanned PDF" detection means "no text layer".** A scanned PDF that already has an OCR text layer is treated as a normal PDF. There is no OCR.
4. `pytest`, `reportlab` and (for the venv check only) the LangChain packages were installed as test dependencies.
