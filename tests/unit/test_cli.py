"""CLI smoke tests (user-facing commands for PRF-01 / PRF-02)."""
import json

from conftest import make_profile
from jobagent import cli
from jobagent.flows.f0_profile.loader import load_profile, save_profile


def test_check_profile_warns_then_fails_in_strict_mode(tmp_path, capsys):
    p = tmp_path / "profile.json"
    save_profile(make_profile(), p)
    assert cli.main(["check-profile", "--profile", str(p)]) == 0
    assert "notice_period_days" in capsys.readouterr().out
    assert cli.main(["check-profile", "--profile", str(p), "--strict"]) == 1


def test_set_sensitive_saves_valid_values_and_rejects_bad_ones(tmp_path, capsys):
    p = tmp_path / "profile.json"
    save_profile(make_profile(), p)
    assert cli.main(["set-sensitive", "notice_period_days", "30", "--profile", str(p)]) == 0
    assert load_profile(p).sensitive.notice_period_days == 30
    assert cli.main(["set-sensitive", "relocation", "true", "--profile", str(p)]) == 0
    assert load_profile(p).sensitive.relocation is True
    assert cli.main(["set-sensitive", "notice_period_days", "soon", "--profile", str(p)]) == 1
    assert load_profile(p).sensitive.notice_period_days == 30  # unchanged after the bad value


def test_build_profile_reports_a_corrupt_pdf_without_needing_an_api_key(tmp_path, capsys):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"junk")
    out = tmp_path / "profile.json"
    assert cli.main(["build-profile", str(bad), "--out", str(out)]) == 1
    assert "could not read PDF" in capsys.readouterr().err and not out.exists()
