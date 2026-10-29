import hashlib
import json
import os
from pathlib import Path

from jobagent.core.schemas import Profile

DEFAULT_PROFILE_PATH = Path("data/profile.json")


def profile_hash(profile: Profile) -> str:
    canonical = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> Profile:
    return Profile.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_profile(profile: Profile, path: Path = DEFAULT_PROFILE_PATH) -> None:
    """Write atomically so a crash never leaves a half-written profile.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
