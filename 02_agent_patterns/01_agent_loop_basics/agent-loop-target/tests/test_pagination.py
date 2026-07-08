"""Bug 1 — off-by-one. The final partial page must not be dropped."""

import pytest

from agent_loop_target.pagination import paginate


def test_exact_multiple():
    assert paginate([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_partial_final_page_is_kept():
    # 10 items in pages of 3 -> four pages, the last holding the remainder.
    assert paginate(list(range(10)), 3) == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]


def test_single_partial_page():
    assert paginate([1, 2], 5) == [[1, 2]]


def test_empty():
    assert paginate([], 3) == []


def test_invalid_page_size():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 0)
