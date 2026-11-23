"""Composition root: application configuration, lifecycle and worker ownership."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from .controllers.errors import register_http_handlers
from .controllers.parking import router
from .services.parking import ParkingService
from .settings import Settings
from .storage import Database
from .simulator import SimulatorRuntime
from .worker import business_worker
from .modbus import ModbusDeviceAdapter
from .hardware import hardware_worker


def create_app(settings: Settings | None = None, *, service: ParkingService | None = None):
    settings = settings or Settings()
    if service and (service.mode != settings.mode or service.hourly_rate_bani != settings.hourly_rate_bani):
        raise ValueError("Injected service must match mode and tariff configuration")

    @asynccontextmanager
    async def lifespan(application):
        active = service or await run_in_threadpool(lambda: ParkingService(
            Database(settings.database_path), mode=settings.mode, hourly_rate_bani=settings.hourly_rate_bani))
        await run_in_threadpool(active.recover)
        application.state.parking = active
        simulator = None
        if settings.mode == "simulation" and settings.simulator_enabled:
            simulator = SimulatorRuntime(active, step_delay_ms=settings.simulator_step_delay_ms,
                                         auto_passage=settings.simulator_auto_passage, transport=settings.transport)
            await run_in_threadpool(simulator.connect)
        application.state.simulator = simulator
        adapter = ModbusDeviceAdapter.from_settings(settings) if settings.mode == "hardware" and settings.hardware_enabled else None
        application.state.hardware_adapter = adapter
        stop = asyncio.Event()
        if settings.worker_enabled:
            task = asyncio.create_task(hardware_worker(active, adapter, stop, settings.worker_interval_seconds)
                                       if adapter else business_worker(active, stop, settings.worker_interval_seconds, simulator))
        else:
            task = None
        application.state.worker_task = task
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            if simulator:
                active.simulation_handler = None
                await simulator.adapter.close()
            if adapter:
                await adapter.close()

    application = FastAPI(title="STM32 Smart Parking API", description="Persistent parking API; simulated payments.",
                          version="0.1.0", lifespan=lifespan)

    application.state.settings = settings
    register_http_handlers(application)
    application.include_router(router)
    return application


app = create_app()
