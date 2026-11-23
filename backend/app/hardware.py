"""Single hardware controller: commit send intent, then perform bounded I/O."""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from .contracts.firmware import DeviceCommand
from .worker import process_batch
from .observations import boot_floors as stored_boot_floors

logger = logging.getLogger(__name__)


def bindings(service):
    with service.db.transaction(write=False) as connection:
        return [dict(row) for row in connection.execute(
            """SELECT d.* FROM device_commands d JOIN commands c ON c.id=d.command_id
               WHERE c.status IN ('executing','unknown') ORDER BY c.created_at,c.id""")]


def boot_floors(service):
    with service.db.transaction(write=False) as connection:
        return stored_boot_floors(connection)


async def hardware_worker(service, adapter, stop, interval):
    async def persist_boot(node, boot):
        await run_in_threadpool(service.record_boot_observation, node, boot)
    adapter.set_boot_observer(persist_boot)
    retries = {}
    while not stop.is_set():
        try:
            adapter.seed_boot_floors(await run_in_threadpool(boot_floors, service))
            telemetry = await adapter.read_telemetry()
            await run_in_threadpool(service.ingest_telemetry, telemetry)
            await run_in_threadpool(process_batch, service, retries, stop.is_set)
            for row in await run_in_threadpool(bindings, service):
                if stop.is_set():
                    break
                try:
                    command = DeviceCommand.model_validate_json(row["block_json"])
                    if row["send_state"] == "prepared":
                        command = await run_in_threadpool(service.claim_dispatch, row["command_id"])
                        if command is None:
                            continue
                        result = await adapter.submit(command)
                    else:
                        # Read-only reconciliation of the ORIGINAL ID/block, including after restart.
                        result = await adapter.read_command(command)
                    await run_in_threadpool(service.record_device_result, row["command_id"], result)
                except Exception:
                    logger.exception("Hardware command reconciliation failed: %s", row["command_id"])
        except Exception:
            logger.exception("Hardware polling failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
