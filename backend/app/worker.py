"""Business queue and simulator loop; physical dispatch lives in hardware.py."""

import asyncio
import logging
import time

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def process_batch(service, retry_after=None, should_stop=lambda: False, *, clock=None):
    retry_after = {} if retry_after is None else retry_after
    clock = clock or time.monotonic
    # A retry remains a retry even when its backoff expired during a slow batch.
    # First attempts must be selected before any previously failed command.
    batch = service.processable_commands(limit=50, excluded=frozenset(retry_after))
    if len(batch) < 50:
        now = clock()
        retries = [identifier for identifier, deadline in sorted(retry_after.items(), key=lambda item: (item[1], item[0]))
                   if deadline <= now]
        batch += service.processable_commands(limit=50 - len(batch), excluded=set(batch), ordered_ids=retries)
    for command_id in batch:
        if should_stop():
            break
        try:
            service.process(command_id)
        except Exception:
            # Transaction already rolled back; retain accepted for a later retry.
            # One bad command must not starve the rest of the queue.
            logger.exception("Business command processing failed: %s", command_id)
            retry_after[command_id] = clock() + 5
        else:
            retry_after.pop(command_id, None)


async def business_worker(service, stop: asyncio.Event, interval: float, simulator=None):
    retry_after = {}
    while not stop.is_set():
        try:
            if simulator is None:
                await run_in_threadpool(process_batch, service, retry_after, stop.is_set)
            else:
                await run_in_threadpool(simulator.cycle, retry_after, stop.is_set)
        except Exception:
            logger.exception("Business queue unavailable")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
