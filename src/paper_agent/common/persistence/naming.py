from __future__ import annotations

import re
from typing import Optional

from ..models.base import TaskPhase

PHASE_SHORT_NAMES: dict[str, str] = {
    TaskPhase.TASK_INITIALIZATION.value: "task_init",
    TaskPhase.PAPER_RETRIEVAL.value: "paper_retrieval",
    TaskPhase.PAPER_PARSING.value: "paper_parsing",
    TaskPhase.CODE_LOCATION.value: "code_loc",
    TaskPhase.REPRODUCTION_PLANNING.value: "repro_plan",
    TaskPhase.EXPERIMENT_EXECUTION.value: "exp_exec",
    TaskPhase.RESULT_REPORTING.value: "result_report",
}

SHORT_TO_PHASE: dict[str, str] = {v: k for k, v in PHASE_SHORT_NAMES.items()}

VALID_TYPES = {"plan", "result", "error", "eval", "summary", "output", "completion"}

_FILENAME_PATTERN = re.compile(
    r"^(?P<phase>[a-z_]+)"
    r"(?:_(?P<step_id>s\d+))?"
    r"(?:_(?P<tool>[a-z_]+))?"
    r"_(?P<type>plan|result|error|eval|summary|output|completion)"
    r"(?:_r(?P<revision>\d+))?"
    r"\.json$"
)


def phase_short(phase: TaskPhase | str) -> str:
    phase_str = phase.value if isinstance(phase, TaskPhase) else str(phase)
    return PHASE_SHORT_NAMES.get(phase_str, phase_str)


def phase_from_short(short: str) -> Optional[str]:
    return SHORT_TO_PHASE.get(short)


def artifact_filename(
    phase: TaskPhase | str,
    artifact_type: str,
    step_id: Optional[str] = None,
    tool: Optional[str] = None,
    revision: Optional[int] = None,
) -> str:
    if artifact_type not in VALID_TYPES:
        raise ValueError(f"Invalid artifact_type: {artifact_type}. Must be one of {VALID_TYPES}")

    short = phase_short(phase)
    parts = [short]

    if step_id:
        parts.append(step_id)
    if tool and step_id:
        parts.append(tool)

    parts.append(artifact_type)

    if revision is not None and revision > 0:
        parts.append(f"r{revision}")

    return "_".join(parts) + ".json"


def parse_artifact_filename(name: str) -> Optional[dict]:
    if not name.endswith(".json"):
        return None

    if name in ("research_spec.json", "task_state.json"):
        return {"name": name, "type": "spec" if name == "research_spec.json" else "state", "is_fixed": True}

    if name.startswith("checkpoint_") and name.endswith(".json"):
        ts = name[len("checkpoint_"):-len(".json")]
        return {"name": name, "type": "checkpoint", "timestamp": ts, "is_fixed": True}

    m = _FILENAME_PATTERN.match(name)
    if not m:
        return None

    gd = m.groupdict()
    result = {
        "name": name,
        "phase_short": gd["phase"],
        "phase": SHORT_TO_PHASE.get(gd["phase"], gd["phase"]),
        "step_id": gd.get("step_id"),
        "tool": gd.get("tool"),
        "type": gd["type"],
        "revision": int(gd["revision"]) if gd.get("revision") else 0,
        "is_fixed": False,
    }
    return result
