"""Bug 2 — wrong comparison operator at the A boundary."""

import pytest

from agent_loop_target.grades import letter_grade


def test_lower_bounds_are_inclusive():
    assert letter_grade(90) == "A"
    assert letter_grade(80) == "B"
    assert letter_grade(70) == "C"
    assert letter_grade(60) == "D"


def test_interior_values():
    assert letter_grade(95) == "A"
    assert letter_grade(85) == "B"
    assert letter_grade(59) == "F"


def test_extremes():
    assert letter_grade(100) == "A"
    assert letter_grade(0) == "F"


def test_out_of_range():
    with pytest.raises(ValueError):
        letter_grade(101)
    with pytest.raises(ValueError):
        letter_grade(-1)
