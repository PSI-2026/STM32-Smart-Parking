"""FC03-only reader for the six v1 registers verified on Mert's board.

There is no DeviceAdapter implementation, command submission, lease, boot
inference or conversion into distributed-v2.1 telemetry in this module.
"""

import asyncio
from dataclasses import dataclass
import math
import time

from pymodbus.client import AsyncModbusSerialClient

from .contracts.legacy import LegacyTelemetry


def decode_registers(words, unit_id):
    if (len(words) != 6 or any(type(w) is not int or not 0 <= w <= 65535 for w in words)
        or words[:2] != [unit_id, 0x0100] or words[2] not in (1, 2)
        or words[3] not in (0, 1) or words[4] > 15 or words[5] > 15
        or words[4] & 1 != words[3]):
        raise ValueError("Incompatible v1 register response")
    return tuple(words)


def read_only_pdu(sending, pdu):
    if sending and pdu.function_code != 3:
        raise PermissionError("The v1 diagnostic reader may only emit FC03")
    return pdu


@dataclass(frozen=True)
class Observation:
    words: tuple | None
    received: float
    observed_at: int | None
    round_trip_ms: int
    error: str | None


class LegacyReader:
    def __init__(self, client, *, unit_id=1, timeout=0.3, stale_after_ms=2000,
                 monotonic=time.monotonic, wall=time.time):
        self.client, self.unit_id, self.timeout = client, unit_id, timeout
        self.stale_after_ms, self.monotonic, self.wall = stale_after_ms, monotonic, wall
        self.lock = asyncio.Lock()
        self.latest = Observation(None, 0, None, 0, "unknown")

    @classmethod
    def from_settings(cls, settings):
        client = AsyncModbusSerialClient(settings.modbus_serial_port, baudrate=settings.modbus_baudrate,
            parity=settings.modbus_parity, stopbits=1, bytesize=8, timeout=settings.modbus_timeout_seconds,
            retries=0, reconnect_delay=0, trace_pdu=read_only_pdu)
        return cls(client, unit_id=settings.legacy_unit_id, timeout=settings.modbus_timeout_seconds,
                   stale_after_ms=settings.legacy_stale_after_ms)

    async def poll(self):
        async with self.lock:
            started = self.monotonic()
            try:
                async with asyncio.timeout(self.timeout * 2 + 0.2):
                    if not self.client.connected and not await self.client.connect():
                        raise ConnectionError("Disconnected")
                    response = await self.client.read_holding_registers(0, count=6, device_id=self.unit_id)
                    if response.isError():
                        raise ConnectionError("Modbus exception")
                words = decode_registers(response.registers, self.unit_id)
                received = self.monotonic()
                self.latest = Observation(words, received, int(self.wall() * 1000),
                                          math.ceil((received - started) * 1000), None)
            except Exception as error:
                self.client.close()
                self.latest = Observation(None, self.monotonic(), None, 0,
                                          "incompatible" if isinstance(error, ValueError) else "unavailable")

    def snapshot(self):
        # One immutable reference makes the sync HTTP read coherent with async polling.
        observation = self.latest
        if observation.words is None:
            return unavailable_telemetry(self.unit_id, self.stale_after_ms, quality=observation.error or "unknown")
        words = observation.words
        age = observation.round_trip_ms + max(0, math.ceil((self.monotonic() - observation.received) * 1000))
        quality = "stale" if age >= self.stale_after_ms else "reported" if words[5] & 1 else "unknown"
        return LegacyTelemetry.from_internal(selected=True, enabled=True, unit_id=self.unit_id,
            protocol_version=256, connected=quality != "stale", quality=quality,
            observed_at=observation.observed_at, age_ms=age, stale_after_ms=self.stale_after_ms,
            device_health=words[2], device_known=bool(words[5] & 1),
            occupied=bool(words[3]) if quality == "reported" else None, raw_registers=list(words),
            message="Observație v1.0: răspuns recent; vechimea achiziției și boot-ul MCU nu sunt disponibile.")

    async def close(self):
        async with self.lock:
            self.client.close()
            self.latest = Observation(None, self.monotonic(), None, 0, "unavailable")


def unavailable_telemetry(unit_id=1, stale_after_ms=2000, *, quality="disabled", selected=True, enabled=True):
    return LegacyTelemetry.from_internal(selected=selected, enabled=enabled, unit_id=unit_id,
        protocol_version=None, connected=False, quality=quality, observed_at=None, age_ms=None,
        stale_after_ms=stale_after_ms, device_health=None, device_known=None, occupied=None,
        raw_registers=None, message="Profil de citire v1.0; observația fizică nu este disponibilă.")


async def legacy_worker(reader, stop, interval):
    while not stop.is_set():
        await reader.poll()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
