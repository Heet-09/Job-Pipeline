Extract structured details from the job description. Reply with ONLY a JSON object.

Rules (hard):
- Use only what the JD text says. If something is not stated, use null / empty list / "unknown". Never guess.
- `salary_range`: copy the text exactly as written (e.g. "10-15 LPA"). If the JD has no salary, return null.
- `must_have_skills` / `nice_to_have`: only skills/tools that are literally named in the JD.
- `exp_min` / `exp_max`: years, as numbers, only if stated.
- `role_category`: genai_agent | ml | backend | data | other.
- `apply_type`: easy_apply | external_ats | email | unknown.
