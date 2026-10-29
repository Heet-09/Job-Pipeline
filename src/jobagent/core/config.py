from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[3] / "config" / "settings.yaml"


@dataclass
class Settings:
    auto_submit: bool = False            # SAF-01: must be switched on explicitly
    daily_submit_cap: int = 15
    max_pages: int = 8
    jd_max_age_days: int = 3
    ghost_after_days: int = 14
    score_go: int = 70
    score_maybe: int = 50
    auto_tailor: int = 80
    between_submits_sec: tuple[int, int] = (45, 120)
    max_attempts: int = 3
    lease_min: int = 15
    bank_min_sim: float = 0.90
    match_min_score: float = 80
    match_min_margin: float = 10
    mapper_accuracy_target: float = 0.90
    models: dict = field(default_factory=lambda: {"small": "llama-3.1-8b-instant", "large": "llama-3.3-70b-versatile"})


def load_settings(path: Path | None = None) -> Settings:
    path = Path(path) if path else DEFAULT_SETTINGS_PATH
    s = Settings()
    if not path.exists():
        return s
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flat = {}
    for section in raw.values():
        if isinstance(section, dict):
            flat.update(section)
    flat.update({k: v for k, v in raw.items() if not isinstance(v, dict)})
    if "models" in raw:
        flat["models"] = raw["models"]
    known = {f.name for f in fields(Settings)}
    for k, v in flat.items():
        if k in known:
            setattr(s, k, tuple(v) if k == "between_submits_sec" else v)
    return s
