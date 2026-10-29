Score how well this job fits the candidate. Reply with ONLY a JSON object:
{"skills": 0-40, "seniority": 0-20, "salary": 0-15, "role_type": 0-15, "company": 0-10, "total": <sum>, "reason": "<max 2 short lines>"}

Fixed rubric weights: skills 40, seniority 20, salary 15, role_type 15, company 10.
- role_type: is this real GenAI/agent work, or a support/QA/data-entry job that merely carries an "AI" label? Give the latter a very low score.
- salary: score only if the JD states a salary. If it is missing, give 8 (neutral). Do not penalise.
- reason: at most 2 lines.
