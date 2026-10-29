"""Generates the golden form-mapping set (src/jobagent/flows/f7_feedback/golden/*.json).

20 forms written by hand in the wording seen on Greenhouse / Lever / Ashby / Workable / SmartRecruiters / Workday / Indian
job-portal forms. They are NOT captured from real sites (no network), and the labels were written BEFORE the mapper was
measured against them. Run once; the JSON files are committed.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "jobagent" / "flows" / "f7_feedback" / "golden"
OUT.mkdir(parents=True, exist_ok=True)

EXPECT = {
    "email": ("personal", "personal.email"), "first": ("personal", "personal.first_name"), "last": ("personal", "personal.last_name"),
    "name": ("personal", "personal.name"), "phone": ("personal", "personal.phone"), "li": ("personal", "personal.links.linkedin"),
    "gh": ("personal", "personal.links.github"), "web": ("personal", "personal.links.portfolio"), "loc": ("personal", "personal.location"),
    "notice": ("sensitive", "sensitive.notice_period_days"), "ectc": ("sensitive", "sensitive.expected_ctc"),
    "cctc": ("sensitive", "sensitive.current_ctc"), "reloc": ("sensitive", "sensitive.relocation"), "auth": ("sensitive", "sensitive.work_auth"),
    "yoe": ("experience", "experience.total_years"), "resume": ("file_resume", None), "consent": ("consent", None),
    "skip": ("skip", None), "custom": ("custom_question", None),
}
YN = ["Yes", "No"]

FORMS = {
    "greenhouse_1": [
        ("First Name", "text", "first"), ("Last Name", "text", "last"), ("Email", "text", "email"), ("Phone", "text", "phone"),
        ("Resume/CV", "file", "resume"), ("Cover Letter", "file", "skip"), ("LinkedIn Profile", "text", "li"), ("Website", "text", "web"),
        ("GitHub", "text", "gh"), ("How did you hear about this job?", "text", "custom"),
        ("Are you legally authorized to work in the country in which this job is located?", "radio", "auth", YN),
        ("Will you now or in the future require sponsorship for employment visa status?", "radio", "auth", YN),
        ("Gender", "select", "skip", ["Male", "Female", "Decline"]), ("Race", "select", "skip", ["Asian", "White", "Decline"]),
        ("Veteran Status", "select", "skip", ["Yes", "No"]), ("Disability Status", "select", "skip", ["Yes", "No"])],
    "greenhouse_2": [
        ("First Name", "text", "first"), ("Last Name", "text", "last"), ("Email", "text", "email"), ("Phone", "text", "phone"),
        ("Location (City)", "text", "loc"), ("Resume", "file", "resume"), ("LinkedIn URL", "text", "li"),
        ("Why do you want to work at this company?", "textarea", "custom"), ("What is your expected salary?", "text", "ectc"),
        ("Are you open to relocation?", "select", "reloc", YN)],
    "lever_1": [
        ("Full name", "text", "name"), ("Email", "text", "email"), ("Phone", "text", "phone"), ("Current location", "text", "loc"),
        ("Current company", "text", "custom"), ("LinkedIn URL", "text", "li"), ("Twitter URL", "text", "custom"), ("GitHub URL", "text", "gh"),
        ("Portfolio URL", "text", "web"), ("Resume/CV", "file", "resume"), ("Additional information", "textarea", "custom"),
        ("Pronouns", "text", "skip")],
    "lever_2": [
        ("Full name", "text", "name"), ("Email", "text", "email"), ("Phone", "text", "phone"), ("Resume/CV", "file", "resume"),
        ("What interests you about this role?", "textarea", "custom"), ("What is your notice period?", "text", "notice"),
        ("Do you require visa sponsorship?", "radio", "auth", YN), ("Gender identity", "select", "skip", ["Woman", "Man", "Non-binary"])],
    "ashby_1": [
        ("Name", "text", "name"), ("Email", "text", "email"), ("Phone Number", "text", "phone"), ("Resume", "file", "resume"),
        ("LinkedIn", "text", "li"), ("What is your expected salary?", "text", "ectc"), ("When can you start?", "text", "notice"),
        ("Are you open to relocation?", "radio", "reloc", YN), ("Why are you interested in this role?", "textarea", "custom")],
    "ashby_2": [
        ("Legal name", "text", "name"), ("Email address", "text", "email"), ("Mobile number", "text", "phone"), ("Resume", "file", "resume"),
        ("Link to your GitHub", "text", "gh"), ("Tell us about a project you are proud of", "textarea", "custom"),
        ("Total years of professional experience", "text", "yoe"), ("Do you have the right to work in India?", "radio", "auth", YN)],
    "workable_1": [
        ("First name", "text", "first"), ("Last name", "text", "last"), ("Email", "text", "email"), ("Phone", "text", "phone"),
        ("Cover letter", "textarea", "custom"), ("Years of experience", "text", "yoe"), ("Expected salary", "text", "ectc"),
        ("Notice period", "text", "notice"), ("Resume", "file", "resume")],
    "workable_2": [
        ("First name", "text", "first"), ("Last name", "text", "last"), ("Email", "text", "email"), ("Phone", "text", "phone"),
        ("What are your strengths?", "textarea", "custom"), ("Describe your experience with Python.", "textarea", "custom"),
        ("Are you comfortable working in a hybrid setup?", "radio", "custom", YN), ("Resume", "file", "resume"),
        ("I agree to the processing of my personal data", "checkbox", "consent")],
    "smartrecruiters_1": [
        ("Given name", "text", "first"), ("Family name", "text", "last"), ("Email address", "text", "email"),
        ("Confirm your email", "text", "email"), ("Mobile phone number", "text", "phone"), ("City", "text", "loc"),
        ("Resume", "file", "resume"), ("I acknowledge the Privacy Policy", "checkbox", "consent"),
        ("How many years of relevant experience do you have?", "text", "yoe")],
    "workday_1": [
        ("Legal First Name", "text", "first"), ("Legal Last Name", "text", "last"), ("Email Address", "text", "email"),
        ("Phone Number", "text", "phone"), ("Phone Device Type", "select", "custom", ["Mobile", "Home", "Work"]),
        ("Country Phone Code", "select", "custom", ["India (+91)", "United States (+1)"]), ("City", "text", "loc"),
        ("Resume", "file", "resume"), ("LinkedIn", "text", "li"),
        ("Are you legally authorized to work in this country?", "radio", "auth", YN)],
    "naukri_1": [
        ("Current CTC (in LPA)", "text", "cctc"), ("Expected CTC (in LPA)", "text", "ectc"), ("Notice Period (in days)", "text", "notice"),
        ("Total Experience (in years)", "text", "yoe"), ("Current Location", "text", "loc"), ("Preferred Location", "text", "custom"),
        ("Are you willing to relocate?", "radio", "reloc", YN), ("Resume", "file", "resume")],
    "naukri_2": [
        ("Current Salary", "text", "cctc"), ("Expected Salary", "text", "ectc"), ("How soon can you join?", "select", "notice", ["Immediate", "15 days", "30 days"]),
        ("Years of Experience", "text", "yoe"), ("Mobile Number", "text", "phone"), ("Email ID", "text", "email"),
        ("Upload CV", "file", "resume"), ("Do you have a laptop?", "radio", "custom", YN)],
    "startup_1": [
        ("Your name", "text", "name"), ("Email", "text", "email"), ("Contact number", "text", "phone"), ("Where are you based?", "text", "loc"),
        ("Resume", "file", "resume"), ("What excites you about agentic AI?", "textarea", "custom"),
        ("Link to GitHub or portfolio", "text", "gh"), ("Anything else we should know?", "textarea", "custom")],
    "startup_2": [
        ("First Name", "text", "first"), ("Last Name", "text", "last"), ("Email", "text", "email"), ("Phone", "text", "phone"),
        ("Personal website or blog", "text", "web"), ("LinkedIn Profile URL", "text", "li"), ("CV", "file", "resume"),
        ("Describe a time you debugged a hard production issue.", "textarea", "custom"),
        ("Earliest joining date", "text", "notice")],
    "enterprise_1": [
        ("First Name", "text", "first"), ("Last Name", "text", "last"), ("Email Address", "text", "email"), ("Telephone", "text", "phone"),
        ("Current CTC", "text", "cctc"), ("Expected CTC", "text", "ectc"), ("Notice Period", "text", "notice"),
        ("Do you hold a valid work permit?", "radio", "auth", YN), ("Date of birth", "text", "custom"),
        ("Marital status", "select", "skip", ["Single", "Married"]), ("Resume", "file", "resume")],
    "enterprise_2": [
        ("Full Name", "text", "name"), ("Email", "text", "email"), ("WhatsApp number", "text", "phone"), ("Current city", "text", "loc"),
        ("Total experience", "text", "yoe"), ("Resume", "file", "resume"), ("Caste / category", "select", "skip", ["General", "OBC", "SC", "ST"]),
        ("I confirm that the information provided is true", "checkbox", "consent")],
    "consent_1": [
        ("Email", "text", "email"), ("Phone", "text", "phone"), ("I agree to the Terms and Conditions", "checkbox", "consent"),
        ("I consent to the processing of my data for recruitment", "checkbox", "consent"), ("Resume", "file", "resume")],
    "custom_heavy_1": [
        ("First Name", "text", "first"), ("Last Name", "text", "last"), ("Email", "text", "email"),
        ("Why do you want to join us?", "textarea", "custom"), ("What is your greatest professional achievement?", "textarea", "custom"),
        ("Which LLM frameworks have you used?", "textarea", "custom"), ("Describe your ideal team.", "textarea", "custom"),
        ("Would you like to receive job alerts?", "radio", "custom", YN), ("Resume", "file", "resume")],
    "mixed_1": [
        ("Name", "text", "name"), ("E-mail", "text", "email"), ("Cell", "text", "phone"), ("Notice period", "text", "notice"),
        ("Expected compensation", "text", "ectc"), ("Are you eligible to work in the United States?", "radio", "auth", YN),
        ("Are you willing to relocate for this role?", "select", "reloc", YN), ("Resume", "file", "resume"),
        ("What is your favourite programming language?", "text", "custom")],
    "greenhouse_3": [
        ("First Name", "text", "first"), ("Last Name", "text", "last"), ("Email", "text", "email"), ("Phone", "text", "phone"),
        ("Resume/CV", "file", "resume"), ("Current Employer", "text", "custom"), ("Current Job Title", "text", "custom"),
        ("What is your current salary?", "text", "cctc"), ("What are your salary expectations?", "text", "ectc"),
        ("What is your notice period?", "text", "notice"), ("Are you willing to relocate to Bangalore?", "radio", "reloc", YN),
        ("Do you need work authorization or sponsorship?", "radio", "auth", YN),
        ("Tell us about your experience with LangChain.", "textarea", "custom"), ("Hispanic/Latino", "select", "skip", YN)],
}


for name, fields in FORMS.items():
    snapshot, expected = [], {}
    for f in fields:
        label, typ, exp = f[0], f[1], f[2]
        options = f[3] if len(f) > 3 else []
        ref = f"{typ}:{label}:0"
        snapshot.append({"ref": ref, "label": label, "type": typ, "required": True, "options": options})
        cat, key = EXPECT[exp]
        expected[ref] = {"category": cat, "profile_key": key}
    (OUT / f"{name}.json").write_text(json.dumps({"form": name, "snapshot_fields": snapshot, "expected": expected}, indent=1), encoding="utf-8")
print(f"{len(FORMS)} forms, {sum(len(v) for v in FORMS.values())} fields")
