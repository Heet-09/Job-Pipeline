# PRF-01: Changes Made

Feature: **PRF-01, Resume se profile banta hai.** A resume PDF becomes a structured `data/profile.json` (experience, projects, skills, education).

Design source: Features doc (PRF-01) and LLD section 6, F0: Profile (`profile.json` shape, bullet ids, hash).

## Usage

```bash
pip install -e ".[dev]"            # needs Python 3.11+
export GROQ_API_KEY=...            # see .env.example
python -m jobagent.cli build-profile resume.pdf            # writes data/profile.json
python -m jobagent.cli build-profile resume.pdf --dry-run  # prints summary, writes nothing
pytest
```

After building, the user fills `sensitive.*` (CTC, notice period, relocation, work auth) by hand.

## Files added

| File | Purpose |
|---|---|
| `src/jobagent/core/schemas.py` | Pydantic models for `Profile` (same shape as the LLD). It also holds `ResumeExtract`, the **only** shape the LLM may return. `ResumeExtract` has no `sensitive` section and no bullet ids. |
| `src/jobagent/flows/f0_profile/builder.py` | Main logic. It reads the PDF, calls the extractor, validates and assembles the profile, then saves it. |
| `src/jobagent/flows/f0_profile/extractor.py` | `ResumeExtractor` interface and `LangChainExtractor` (Groq via LangChain `with_structured_output`). The client is created on first use. |
| `src/jobagent/flows/f0_profile/loader.py` | `load_profile`, atomic `save_profile` and `profile_hash` (sha256 of canonical JSON, as in the LLD). The hash is not wired into PRF-04 yet. |
| `src/jobagent/cli.py` | `build-profile` command with `--out` and `--dry-run`. |
| `prompts/profile_extract.md` | Extraction prompt. It lives in a file, as the LLD asks. |
| `tests/unit/test_prf01_profile_builder.py` | 24 tests (TC-001 to TC-003 plus guards). |
| `pyproject.toml`, `.env.example`, `__init__.py` files | Packaging, pytest config, and the API key placeholder. |
| `docs/PRF-01_Test_Report.md`, `docs/PRF-01_Changes.md` | This report and this doc. |

## Files modified

| File | Change |
|---|---|
| `Job_Pipeline_Agent_TestCases.xlsx` | Status, Actual Result and Remarks filled for TC-001 to TC-003 (all Pass). Nothing else was changed. |
| `.gitignore` | Added `.env`, `data/profile.json` and `.pytest_cache/`, because the profile and API key must never be committed. |

## Behaviour and design decisions

- **Unreadable PDF (TC-002):** Corrupt, encrypted, missing and scanned (less than 100 characters of extractable text) PDFs raise `ProfileBuildError` with a clear message. The LLM is not called and nothing is written.
- **Empty result (TC-002):** If the LLM returns nothing usable, the build errors and no empty profile is saved.
- **No projects (TC-003):** The profile is still built and a warning is returned (and printed by the CLI).
- **Sensitive data (PRF-02 safety):** `sensitive` is always created empty. The LLM schema cannot carry those fields. When rebuilding over an existing `profile.json`, the existing `sensitive` values and `version` are kept so manual entries are not lost.
- **Hallucination guards:**
  - A company that does not appear in the resume text is dropped, with a warning.
  - An email that does not appear in the resume text is dropped, with a warning.
  - A date that cannot be parsed is set to null, with a warning. Dates are normalised to `YYYY-MM`, `YYYY` or `present`.
- **Bullet ids:** Ids are `e<job>b<n>` for experience and `p<project>b<n>` for projects, assigned in code and not by the LLM. The tailoring step (F3) will use them.
- **Safe writes:** `profile.json` is written to a temp file and then renamed, so a crash cannot leave a half-written file.

## Not done (out of scope for PRF-01)

- PRF-02 (user entry flow and startup fail-fast for null `sensitive` values), PRF-03 (search preferences) and PRF-04 (version bump on change) are not implemented. Only the data shapes and hash helper they will need exist.
- No OCR for scanned resumes.
- The live LLM path has not been run, because no API key was available (see the test report).
