Classify a job-application form field. Reply with ONLY JSON: {"ref": "<ref>", "category": "...", "profile_key": "..." or null}.

category is one of: personal, experience, sensitive, custom_question, file_resume, consent, skip.
- personal / experience / sensitive: profile_key MUST be one of the valid profile_keys listed, never invented.
- sensitive = money, notice period, relocation, work authorization. These are filled only from the user's profile.
- custom_question = a free-text or choice question about the candidate's motivation, fit or opinions (profile_key null).
- skip = demographic / EEO questions and fields that should stay blank.
