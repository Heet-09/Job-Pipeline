import argparse
import sys
from pathlib import Path

from jobagent.flows.f0_profile.builder import ProfileBuildError, build_profile
from jobagent.flows.f0_profile.extractor import LangChainExtractor
from jobagent.flows.f0_profile.loader import DEFAULT_PROFILE_PATH


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jobagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("build-profile", help="Build data/profile.json from a resume PDF")
    bp.add_argument("resume_pdf", type=Path)
    bp.add_argument("--out", type=Path, default=DEFAULT_PROFILE_PATH)
    bp.add_argument("--dry-run", action="store_true", help="Print result, write nothing")
    args = ap.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
