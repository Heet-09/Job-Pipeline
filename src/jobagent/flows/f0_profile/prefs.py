"""PRF-03: search preferences set by the user."""
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class SearchPrefs(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    exp_min: float = 0
    exp_max: float = 50
    locations: list[str] = Field(default_factory=list)
    max_age_days: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def _check_range(self):
        if self.exp_min < 0:
            raise ValueError("exp_min cannot be negative")
        if self.exp_min > self.exp_max:
            raise ValueError(f"exp_min ({self.exp_min}) cannot be greater than exp_max ({self.exp_max})")
        return self


def load_prefs(path: Path) -> SearchPrefs:
    return SearchPrefs(**(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}))
