"""Run the job agent without installing anything:   python agent.py collect-naukri Jobs.xlsx

Same commands as `python -m jobagent.cli ...` (build-profile, check-profile, set-sensitive, collect-naukri, score, digest, ui).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobagent.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
