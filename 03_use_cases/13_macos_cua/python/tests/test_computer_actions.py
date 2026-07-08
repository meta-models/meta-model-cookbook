import pytest

from metacua.computer_actions import normalize_computer_actions
from metacua.errors import CLIError


def test_normalize_single_action_object():
    action = {"action": "wait"}
    assert normalize_computer_actions(action) == [action]


def test_normalize_batched_actions_requires_non_empty_list():
    with pytest.raises(CLIError) as exc:
        normalize_computer_actions({"actions": []})
    assert "`actions` must be a non-empty list" in exc.value.message


def test_normalize_batched_actions_requires_objects():
    with pytest.raises(CLIError) as exc:
        normalize_computer_actions({"actions": [{"action": "wait"}, "bad"]})
    assert "`actions` must be a list of objects" in exc.value.message
