Tailor the candidate's resume for the job. Reply with ONLY a JSON object matching the TailoredResume schema.

Rules (hard):
- Use ONLY skills, tools, numbers, companies and dates that exist in the profile. Do not create any new claim.
- You may rephrase a bullet and reorder bullets so the most relevant come first. You may NOT change facts.
- Never change company, role or dates. Refer to bullets only by their `id`.
- `skills_order` must be a subset of the profile's skills.
- Do not add a skill just because the job asks for it. If the profile lacks it, leave it out.
