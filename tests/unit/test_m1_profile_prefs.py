"""PRF-02 (TC-005), PRF-03 (TC-007), PRF-04 (TC-008, TC-009). TC-004 is in test_prf01_profile_builder.py,
TC-006 is in test_m2_discovery.py (it needs the discovery run)."""
import pytest
from pydantic import ValidationError

from conftest import make_profile
from jobagent.flows.f0_profile.prefs import SearchPrefs
from jobagent.flows.f0_profile.sensitive import MissingSensitiveError, set_sensitive, startup_check
from jobagent.flows.f0_profile.loader import save_profile, load_profile
from jobagent.flows.f0_profile.versioning import record_version


def test_tc005_null_notice_period_warns_at_startup(caplog):
    p = make_profile(current_ctc=1.0, expected_ctc=2.0, relocation=True, work_auth="x")  # notice_period_days stays null
    with caplog.at_level("WARNING"):
        msgs = startup_check(p)
    assert any("notice_period_days" in m for m in msgs)
    assert "notice_period_days" in caplog.text


def test_tc005_null_notice_period_fails_fast_in_strict_mode():
    p = make_profile(current_ctc=1.0, expected_ctc=2.0, relocation=True, work_auth="x")
    with pytest.raises(MissingSensitiveError, match="notice_period_days"):
        startup_check(p, strict=True)


def test_prf02_user_can_set_sensitive_values_and_types_are_validated(tmp_path):
    path = tmp_path / "profile.json"
    save_profile(make_profile(), path)
    set_sensitive(path, notice_period_days=45, relocation=False)
    assert load_profile(path).sensitive.notice_period_days == 45
    with pytest.raises(ValidationError):
        set_sensitive(path, notice_period_days="soon")
    with pytest.raises(ValueError, match="unknown"):
        set_sensitive(path, favourite_colour="blue")


def test_tc007_min_experience_above_max_is_a_validation_error():
    with pytest.raises(ValidationError, match="cannot be greater"):
        SearchPrefs(keywords=["GenAI"], exp_min=4, exp_max=1)


def test_prf03_valid_prefs_accepted():
    p = SearchPrefs(keywords=["GenAI", "LLM", "Agent"], exp_min=1, exp_max=4, locations=["Mumbai"])
    assert (p.exp_min, p.exp_max, p.max_age_days) == (1, 4, 3)


def test_tc008_edited_profile_gets_new_hash_and_old_applications_keep_old_hash(db):
    p = make_profile()
    h1, v1 = record_version(db, p)
    db.write("INSERT INTO jobs(dedupe_key, source, status) VALUES ('a','x','FILLED')")
    db.write("INSERT INTO applications(job_id, profile_hash) VALUES (1, ?)", (h1,))
    p.skills.core.append("Docker")
    h2, v2 = record_version(db, p)
    assert h2 != h1 and v2 == v1 + 1
    assert db.scalar("SELECT profile_hash FROM applications WHERE job_id=1") == h1
    assert db.scalar("SELECT COUNT(*) FROM profile_versions") == 2


def test_tc009_saving_unchanged_profile_keeps_same_hash(db):
    p = make_profile()
    first = record_version(db, p)
    second = record_version(db, make_profile())
    assert first == second
    assert db.scalar("SELECT COUNT(*) FROM profile_versions") == 1
