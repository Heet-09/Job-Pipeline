import argparse
import json
import sys
from pathlib import Path

from jobagent.flows.f0_profile.builder import ProfileBuildError, build_profile
from jobagent.flows.f0_profile.extractor import LangChainExtractor
from jobagent.flows.f0_profile.loader import DEFAULT_PROFILE_PATH

DEFAULT_DB = Path("data/jobagent.db")
DEFAULT_PREFS = Path("config/search_prefs.yaml")


class PrintChannel:
    def send(self, subject: str, body: str) -> None:
        print(f"=== {subject} ===\n{body}")


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jobagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("build-profile", help="Build data/profile.json from a resume PDF")
    bp.add_argument("resume_pdf", type=Path)
    bp.add_argument("--out", type=Path, default=DEFAULT_PROFILE_PATH)
    bp.add_argument("--dry-run", action="store_true", help="Print result, write nothing")
    cp = sub.add_parser("check-profile", help="Warn (or fail with --strict) when sensitive fields are empty")
    cp.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    cp.add_argument("--strict", action="store_true")
    ss = sub.add_parser("set-sensitive", help="Type in a sensitive detail yourself, e.g. set-sensitive notice_period_days 30")
    ss.add_argument("field")
    ss.add_argument("value")
    ss.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)

    cn = sub.add_parser("collect-naukri", help="Scrape Naukri job links from an Excel file and add them to the job database")
    cn.add_argument("links_xlsx", type=Path, help="Excel with a 'link' column (like Jobs.xlsx)")
    cn.add_argument("--db", type=Path, default=DEFAULT_DB)
    cn.add_argument("--prefs", type=Path, default=DEFAULT_PREFS)
    cn.add_argument("--max-age-days", type=int, help="override the prefs value (jobs older than this are dropped)")
    cn.add_argument("--headless", action="store_true", help="does not work against Naukri (it blocks headless browsers)")
    cn.add_argument("--dry-run", action="store_true", help="scrape and filter, but write nothing to the database")
    sc = sub.add_parser("score", help="Extract + score every DISCOVERED job")
    sc.add_argument("--db", type=Path, default=DEFAULT_DB)
    sc.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    sc.add_argument("--llm", action="store_true", help="use the LLM (needs GROQ_API_KEY); default is the rule-based scorer")
    ui = sub.add_parser("ui", help="Open the dashboard in your browser")
    ui.add_argument("--db", type=Path, default=DEFAULT_DB)
    ui.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    ui.add_argument("--port", type=int, default=8501)
    ui.add_argument("--demo", action="store_true", help="use a separate database filled with FAKE demo data")
    dg = sub.add_parser("digest", help="Print the daily digest of new Apply/Maybe jobs")
    dg.add_argument("--db", type=Path, default=DEFAULT_DB)
    return ap


def _cmd_profile(args) -> int:
    if args.cmd == "check-profile":
        from jobagent.flows.f0_profile.loader import load_profile
        from jobagent.flows.f0_profile.sensitive import MissingSensitiveError, startup_check
        try:
            msgs = startup_check(load_profile(args.profile), strict=args.strict)
        except MissingSensitiveError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print("\n".join(f"WARNING: {m}" for m in msgs) or "profile ok: all sensitive fields are set")
        return 0
    if args.cmd == "set-sensitive":
        from jobagent.flows.f0_profile.sensitive import set_sensitive
        try:
            raw = json.loads(args.value)
        except ValueError:
            raw = args.value
        try:
            set_sensitive(args.profile, **{args.field: raw})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"saved sensitive.{args.field}")
        return 0
    try:
        result = build_profile(args.resume_pdf, LangChainExtractor(), args.out, dry_run=args.dry_run)
    except ProfileBuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # LLM/network/auth failures: report, never save a partial profile
        print(f"ERROR: profile extraction failed ({type(e).__name__}): {e}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    p = result.profile
    print(f"{'Would write' if args.dry_run else 'Wrote'} {args.out}: {len(p.experience)} experience, "
          f"{len(p.projects)} projects, {len(p.skills.core)} core skills, {len(p.education)} education")
    print("Fill the 'sensitive' section (CTC, notice period, ...) by hand - it is never auto-filled.")
    return 0


def _cmd_jobs(args) -> int:
    from jobagent.core.config import load_settings
    from jobagent.core.db import Database
    from jobagent.core.notify import LogNotifier
    from jobagent.core.logging import setup_logging

    setup_logging()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.cmd == "collect-naukri":
        from jobagent.flows.f0_profile.prefs import SearchPrefs, load_prefs
        from jobagent.flows.f1_discovery.run import run_scraper_discovery
        from jobagent.flows.f1_discovery.scraper_source import NaukriScraperSource
        prefs = load_prefs(args.prefs) if args.prefs.exists() else SearchPrefs()
        if args.max_age_days is not None:
            prefs.max_age_days = args.max_age_days
        db = Database(args.db, dry_run=args.dry_run)
        source = NaukriScraperSource.from_excel(args.links_xlsx, headless=args.headless,
                                                on_progress=lambda i, n, url: print(f"[{i}/{n}] {url[:90]}", flush=True))
        res = run_scraper_discovery(db, source, prefs, LogNotifier())
        print(f"\nscraped {res.scraped}: {res.parsed} real jobs, {res.expired} expired, {res.scrape_errors} errors\n"
              f"{'would add' if args.dry_run else 'added'} {res.inserted} new jobs; "
              f"{res.rejected} filtered by your preferences, {res.duplicates} duplicates")
        for r in res.reject_reasons[:10]:
            print("  filtered:", r)
        return 0 if res.scrape_errors < max(res.scraped, 1) else 1
    db = Database(args.db)
    if args.cmd == "score":
        from jobagent.flows.f0_profile.loader import load_profile
        from jobagent.flows.f2_scoring.fetcher import default_http_get
        from jobagent.flows.f2_scoring.run import run_scoring
        llm = None
        if args.llm:
            from jobagent.core.llm import LLMClient, langchain_backend
            llm = LLMClient(langchain_backend(), db=db)
        s = run_scoring(db, load_profile(args.profile), default_http_get, llm, load_settings())
        print(f"scored {s.processed}, failed {s.failed}, extraction failed {s.extraction_failed}")
        for r in db.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status"):
            print(f"  {r['status']}: {r['n']}")
        return 0
    from jobagent.flows.f2_scoring.digest import send_digest
    send_digest(db, PrintChannel())
    return 0


def _cmd_ui(args) -> int:
    import os
    import subprocess
    src = str(Path(__file__).resolve().parents[1])
    db = args.db
    if args.demo:
        from jobagent.core.db import Database
        from jobagent.ui.demo import seed_demo
        db = Path("data/demo/demo.db")
        db.parent.mkdir(parents=True, exist_ok=True)
        if db.exists():
            db.unlink()
        d = Database(db)
        seed_demo(d, db.parent / "screenshots")
        d.close()
        print(f"Demo mode: FAKE data in {db} (your real database is untouched)")
    env = {**os.environ, "JOBAGENT_DB": str(db), "JOBAGENT_PROFILE": str(args.profile),
           "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    app = Path(__file__).resolve().parent / "ui" / "app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(args.port),
                            "--browser.gatherUsageStats", "false", "--client.toolbarMode", "minimal"], env=env)


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "ui":
        return _cmd_ui(args)
    if args.cmd in ("collect-naukri", "score", "digest"):
        return _cmd_jobs(args)
    return _cmd_profile(args)


if __name__ == "__main__":
    sys.exit(main())
