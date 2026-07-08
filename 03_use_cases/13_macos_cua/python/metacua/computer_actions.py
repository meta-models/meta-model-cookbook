"""Pure helpers for the Anthropic-style computer.computer tool."""

from typing import Any, Dict, List

from .errors import CLIError


def normalize_computer_actions(input_value: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize a computer.computer input object to a non-empty action list."""
    if not isinstance(input_value, dict):
        raise CLIError("tool input must be an object")
    if "actions" in input_value:
        raw_actions = input_value.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise CLIError("`actions` must be a non-empty list")
        actions = []
        for action in raw_actions:
            if not isinstance(action, dict):
                raise CLIError("`actions` must be a list of objects")
            actions.append(action)
        return actions
    if "action" in input_value:
        return [input_value]
    return []
