"""Bug 3 — missing edge cases: empty input and an all-zero maximum."""

from agent_loop_target.normalize import normalize


def test_basic_scaling():
    assert normalize([2, 4]) == [0.5, 1.0]
    assert normalize([1, 2, 4]) == [0.25, 0.5, 1.0]


def test_empty_returns_empty():
    assert normalize([]) == []


def test_all_zero_does_not_raise():
    assert normalize([0, 0, 0]) == [0.0, 0.0, 0.0]


def test_single_value():
    assert normalize([7]) == [1.0]
