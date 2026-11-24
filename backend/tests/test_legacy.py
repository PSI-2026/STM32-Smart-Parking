"""Read-only compatibility with the exact six-register physical-board result."""

import asyncio
import struct
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerRTU, FramerType

from app.legacy import LegacyReader, decode_registers, read_only_pdu
from app.main import create_app
from app.parking import ParkingService
from app.settings import Settings
from app.storage import Database

TOKEN = "test-legacy-readonly-token-000000000000000000"


class LegacyWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_rtu_frames_read_only_sensor_changes_and_crc_failure(self):
        requests = []
        words = [1, 256, 1, 0, 0, 1]
        corrupt = False
        connections = set()

        async def handle(reader, writer):
            connections.add(writer)
            try:
                while True:
                    request = await reader.readexactly(8)
                    self.assertTrue(FramerRTU.check_CRC(request[:6], int.from_bytes(request[6:], "big")))
                    requests.append(request[:6])
                    response = bytes([1, 3, 12]) + struct.pack(">6H", *words)
                    crc = FramerRTU.compute_CRC(response) ^ int(corrupt)
                    writer.write(response + crc.to_bytes(2, "big"))
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                connections.discard(writer)
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        client = AsyncModbusTcpClient("127.0.0.1", port=server.sockets[0].getsockname()[1],
            framer=FramerType.RTU, retries=0, timeout=0.1, reconnect_delay=0, trace_pdu=read_only_pdu)
        sensor = LegacyReader(client, timeout=0.1)
        try:
            await sensor.poll()
            self.assertIs(sensor.snapshot().occupied, False)
            words[3] = words[4] = 1
            await sensor.poll()
            self.assertIs(sensor.snapshot().occupied, True)
            corrupt = True
            await sensor.poll()
            self.assertEqual(sensor.snapshot().quality, "unavailable")
            self.assertIsNone(sensor.snapshot().occupied)
            self.assertEqual(requests, [bytes([1, 3, 0, 0, 0, 6])] * 3)
        finally:
            await sensor.close()
            server.close()
            await server.wait_closed()
            for writer in list(connections):
                writer.close()
                await writer.wait_closed()


class Client:
    connected = True

    def __init__(self):
        self.words = [1, 256, 1, 0, 0, 1]
        self.calls = []
        self.failure = None

    async def connect(self):
        self.connected = True
        return True

    def close(self):
        self.connected = False

    async def read_holding_registers(self, address, *, count, device_id):
        self.calls.append((3, address, count, device_id))
        if self.failure:
            raise self.failure
        return SimpleNamespace(registers=self.words, isError=lambda: False)


class LegacyTests(unittest.TestCase):
    def test_physical_board_vector_and_invalid_registers(self):
        self.assertEqual(decode_registers([1, 256, 1, 0, 0, 1], 1), (1, 256, 1, 0, 0, 1))
        self.assertEqual(decode_registers([1, 256, 1, 1, 1, 1], 1)[3], 1)
        for words in ([1, 513, 1, 0, 0, 1], [2, 256, 1, 0, 0, 1], [1, 256, 1, 1, 0, 1],
                      [1, 256, 1, 0, 0, 16], [1, 256, 1, 0, 0], [True, 256, 1, 0, 0, 1]):
            with self.subTest(words=words), self.assertRaises(ValueError):
                decode_registers(words, 1)

    def test_outgoing_pdu_guard_refuses_every_function_except_fc03(self):
        pdu = SimpleNamespace(function_code=3)
        self.assertIs(read_only_pdu(True, pdu), pdu)
        for function in (4, 6, 16):
            with self.assertRaises(PermissionError):
                read_only_pdu(True, SimpleNamespace(function_code=function))

    def test_reported_bit_then_unknown_stale_and_timeout(self):
        client = Client()
        clock = [100.0]
        reader = LegacyReader(client, monotonic=lambda: clock[0], wall=lambda: 1_800_000_000)
        asyncio.run(reader.poll())
        observation = reader.snapshot()
        self.assertEqual(observation.quality, "reported")
        self.assertIs(observation.occupied, False)
        self.assertEqual(observation.freshness_guarantee, "communication-only")
        self.assertEqual(client.calls, [(3, 0, 6, 1)])
        clock[0] += 2.1
        self.assertEqual(reader.snapshot().quality, "stale")
        self.assertIsNone(reader.snapshot().occupied)
        client.words = [1, 256, 1, 0, 0, 0]
        asyncio.run(reader.poll())
        self.assertTrue(reader.snapshot().connected)
        self.assertIsNone(reader.snapshot().occupied)
        self.assertFalse(reader.snapshot().device_known)
        client.failure = TimeoutError()
        asyncio.run(reader.poll())
        self.assertEqual(reader.snapshot().quality, "unavailable")
        self.assertIsNone(reader.snapshot().raw_registers)

    def test_incompatible_identity_cannot_be_reported(self):
        client = Client()
        client.words[1] = 513
        reader = LegacyReader(client)
        asyncio.run(reader.poll())
        self.assertEqual(reader.snapshot().quality, "incompatible")
        self.assertIsNone(reader.snapshot().occupied)

    def test_explicit_profile_and_serial_factory(self):
        for kwargs in ({"mode": "simulation", "transport": "USB"}, {"mode": "hardware", "transport": "TCP"}):
            with self.assertRaises(ValidationError):
                Settings(hardware_profile="hybrid-v1-readonly", **kwargs)
        settings = Settings(mode="hardware", transport="USB", hardware_profile="hybrid-v1-readonly", modbus_baudrate=115200)
        with patch("app.legacy.AsyncModbusSerialClient", return_value=Client()) as factory:
            LegacyReader.from_settings(settings)
            self.assertEqual(factory.call_args.kwargs["baudrate"], 115200)
            self.assertEqual(factory.call_args.kwargs["retries"], 0)
            self.assertIs(factory.call_args.kwargs["trace_pdu"], read_only_pdu)

    def test_profile_cannot_reuse_a_parking_database_or_switch_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ParkingService(Database(Path(directory) / "parking.sqlite3"), mode="hardware")
            service.configure_hardware_profile("hybrid-v1-readonly")
            with self.assertRaises(ValueError):
                service.configure_hardware_profile("distributed-v2.1")

    def test_profile_refuses_existing_commands_before_binding(self):
        from app.contracts.api import CommandRequest
        with tempfile.TemporaryDirectory() as directory:
            service = ParkingService(Database(Path(directory) / "parking.sqlite3"), mode="hardware")
            service.admit(CommandRequest.model_validate({"commandId": "old", "action": {"type": "pay", "sessionId": "s"}}))
            with self.assertRaises(ValueError):
                service.configure_hardware_profile("hybrid-v1-readonly")

    def test_profile_refuses_unbound_database_with_distributed_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ParkingService(Database(Path(directory) / "parking.sqlite3"), mode="hardware")
            with service.db.transaction() as connection:
                connection.execute("INSERT INTO telemetry VALUES (1,'{}','previous-runtime',0)")
            with self.assertRaises(ValueError):
                service.configure_hardware_profile("hybrid-v1-readonly")

    def test_authenticated_diagnostics_never_feed_capacity_or_accept_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_path=Path(directory) / "legacy.sqlite3", mode="hardware", transport="USB",
                hardware_profile="hybrid-v1-readonly", hardware_enabled=True, modbus_baudrate=115200,
                admin_token=TOKEN, legacy_poll_interval_seconds=0.1)
            source = Client()
            reader = LegacyReader(source)
            app = create_app(settings)
            with patch("app.main.LegacyReader.from_settings", return_value=reader), \
                 patch("app.main.ModbusDeviceAdapter.from_settings", side_effect=AssertionError("v2 must not start")), \
                 TestClient(app) as client:
                headers = {"Authorization": "Bearer " + TOKEN}
                self.assertEqual(client.get("/api/v1/diagnostics/legacy").status_code, 401)
                deadline = time.monotonic() + 3
                while True:
                    data = client.get("/api/v1/diagnostics/legacy", headers=headers).json()
                    if data["quality"] == "reported" or time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
                self.assertEqual(data["rawRegisters"], [1, 256, 1, 0, 0, 1])
                self.assertIs(data["occupied"], False)
                snapshot = client.get("/api/v1/snapshot", headers=headers).json()
                self.assertIsNone(snapshot["capacity"]["available"])
                self.assertTrue(all(slot["occupied"] is None for slot in snapshot["slots"]))
                for action in ({"type": "enter", "plate": "B1REAL"}, {"type": "pay", "sessionId": "s"},
                               {"type": "exit", "sessionId": "s"}, {"type": "set-all-slot-sensors", "occupied": False}):
                    result = client.post("/api/v1/commands", headers=headers, json={"commandId": "blocked", "action": action})
                    self.assertEqual(result.status_code, 403)
                self.assertEqual(app.state.parking.pending_commands(), [])
                self.assertIsNone(app.state.hardware_adapter)
                self.assertTrue(all(call == (3, 0, 6, 1) for call in source.calls))
            self.assertFalse(source.connected)
            self.assertTrue(app.state.worker_task.done())

    def test_get_only_reads_cache_and_disabled_profile_does_not_connect(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_path=Path(directory) / "legacy.sqlite3", mode="hardware", transport="USB",
                hardware_profile="hybrid-v1-readonly", worker_enabled=False, hardware_enabled=True, admin_token=TOKEN)
            with patch("app.main.LegacyReader.from_settings", side_effect=AssertionError("worker disabled")), TestClient(create_app(settings)) as client:
                headers = {"Authorization": "Bearer " + TOKEN}
                self.assertFalse(client.get("/api/v1/diagnostics/legacy", headers=headers).json()["enabled"])
                source = Client()
                reader = LegacyReader(source)
                asyncio.run(reader.poll())
                client.app.state.legacy_reader = reader
                for _ in range(5):
                    self.assertEqual(client.get("/api/v1/diagnostics/legacy", headers=headers).status_code, 200)
                self.assertEqual(len(source.calls), 1)
