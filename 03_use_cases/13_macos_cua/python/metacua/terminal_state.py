"""Pure terminal-state helpers for function-call terminal tools."""

from enum import Enum
from typing import Tuple


class StopClassification(Enum):
    SUCCESS = "success"
    INFEASIBLE = "infeasible"


def classify_stop_answer(answer: str) -> Tuple[StopClassification, str]:
    """Classify a computer.stop answer into log kind and message text."""
    text = answer or ""
    low = text.lower()
    if "infeasible" in low or "unfeasible" in low:
        return StopClassification.INFEASIBLE, "task infeasible: " + text
    return StopClassification.SUCCESS, "done: " + text


def is_stop_tool_name(name: str) -> bool:
    return name in ("computer.stop", "computer_stop", "stop")
