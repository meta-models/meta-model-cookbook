"""Bug 5 (race condition in async code): count events processed concurrently."""

import asyncio


async def count_events(num_events):
    """Process ``num_events`` events concurrently and return how many were counted.

    Each event handler runs as a coroutine and bumps a shared counter. After all
    handlers finish, the counter must equal ``num_events`` — no updates may be
    lost to interleaving.

    Args:
        num_events: the number of events to process.

    Returns:
        The final counter value, which should equal ``num_events``.
    """
    counter = 0

    async def handle_one():
        nonlocal counter
        current = counter
        await asyncio.sleep(0)
        counter = current + 1

    await asyncio.gather(*(handle_one() for _ in range(num_events)))
    return counter
