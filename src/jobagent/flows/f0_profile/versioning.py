"""PRF-04: every profile change gets a hash/version, so each application records which version it used."""
from jobagent.core.db import Database
from jobagent.core.schemas import Profile
from jobagent.flows.f0_profile.loader import profile_hash


def hash_for_versioning(profile: Profile) -> str:
    """Hash of the content that goes into applications. Version number itself is excluded."""
    return profile_hash(profile.model_copy(update={"version": 0}))


def record_version(db: Database, profile: Profile) -> tuple[str, int]:
    """Store the profile if its content is new. Returns (hash, version). Unchanged content keeps its hash."""
    h = hash_for_versioning(profile)
    row = db.one("SELECT version FROM profile_versions WHERE hash=?", (h,))
    if row:
        return h, row["version"]
    version = (db.scalar("SELECT COALESCE(MAX(version),0) FROM profile_versions") or 0) + 1
    db.write("INSERT INTO profile_versions(hash, version, saved_at, profile_json) VALUES (?,?,?,?)",
             (h, version, db.now_iso(), profile.model_dump_json()))
    return h, version
