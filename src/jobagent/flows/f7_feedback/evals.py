"""FBK-04: measure field-mapping accuracy on the golden forms and catch regressions after a prompt/rule change."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from jobagent.core.schemas import FieldMap, FieldSpec
from jobagent.flows.f4_formfill.mapper import map_field

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"


def default_mapper(spec: FieldSpec) -> FieldMap:
    return map_field(spec) or FieldMap(ref=spec.ref, category="custom_question")


@dataclass
class EvalResult:
    total: int = 0
    correct: int = 0
    forms: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def load_golden(directory: Path = GOLDEN_DIR) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(directory).glob("*.json"))]


def evaluate_mapper(mapper=default_mapper, directory: Path = GOLDEN_DIR) -> EvalResult:
    res = EvalResult()
    for form in load_golden(directory):
        res.forms += 1
        for raw in form["snapshot_fields"]:
            spec = FieldSpec(**raw)
            want = form["expected"][spec.ref]
            got = mapper(spec)
            ok = got.category == want["category"] and (got.profile_key or None) == (want["profile_key"] or None)
            res.total += 1
            res.correct += ok
            if not ok:
                res.errors.append(f"{form['form']}: '{spec.label}' -> {got.category}/{got.profile_key}, expected {want['category']}/{want['profile_key']}")
    return res


@dataclass
class Regression:
    flagged: bool
    accuracy: float
    baseline: float | None
    message: str


def save_baseline(accuracy: float, path: Path = BASELINE_PATH) -> None:
    Path(path).write_text(json.dumps({"mapper_accuracy": round(accuracy, 4)}, indent=1), encoding="utf-8")


def check_regression(accuracy: float, path: Path = BASELINE_PATH, tolerance: float = 0.02) -> Regression:
    p = Path(path)
    if not p.exists():
        return Regression(False, accuracy, None, "no baseline yet")
    base = json.loads(p.read_text(encoding="utf-8"))["mapper_accuracy"]
    if accuracy < base - tolerance:
        return Regression(True, accuracy, base, f"REGRESSION: accuracy {accuracy:.1%} is below baseline {base:.1%} (tolerance {tolerance:.0%})")
    return Regression(False, accuracy, base, f"ok: {accuracy:.1%} vs baseline {base:.1%}")
