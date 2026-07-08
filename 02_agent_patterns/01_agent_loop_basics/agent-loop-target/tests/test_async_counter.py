"""Bug 5 — race condition: concurrent increments must not lose updates."""

import asyncio

from agent_loop_target.async_counter import count_events


def test_counts_every_event():
    assert asyncio.run(count_events(100)) == 100


def test_small_count():
    assert asyncio.run(count_events(5)) == 5


def test_zero():
    assert asyncio.run(count_events(0)) == 0
