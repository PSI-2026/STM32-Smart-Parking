"""Real TCP framing plus decoder/freshness and persistent dispatch regressions."""

import asyncio
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerRTU, FramerType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts.api import CommandRequest
from app.contracts.firmware import DeviceCommand, NODE_IDS, NODE_ROLES
from app.hardware import hardware_worker
from app.modbus import ModbusDeviceAdapter, decode_frame
from app.parking import ParkingService
from app.settings import Settings
from app.storage import Database


def frame(node, sequence=1, *, age=0, record=None):
    payload = {"G": [31], "S1": [0, 2, 3, 0], "S2": [0, 2, 3, 0],
               "S3": [0, 0, 0, 0], "S4": [0, 0, 0, 0], "S5": []}[node]
    words = [0x0201, NODE_ROLES[node], NODE_IDS[node], 5, 0, 1,
             sequence >> 16, sequence & 65535, age >> 16, age & 65535,
             {"G": 1, "S1": 3, "S2": 3, "S3": 15, "S4": 15, "S5": 0}[node], len(payload)]
    words += payload + [0] * (8-len(payload)) + [0] * 17
    if record:
        words[20:27] = [0, 1, record[0], record[1], 3, 1, 1]
        words[28:37] = record
    return words


class DecoderTests(unittest.TestCase):
    def test_partial_validity(self):
        words = frame("S1")
        words[10], words[12:16] = 1, [1, 65535, 1, 0]
        self.assertEqual(decode_frame("S1", words)["mask"], 1)
        words[14] = 3
        with self.assertRaises(ValueError):
            decode_frame("S1", words)

    def test_documented_four_bit_led_vector(self):
        words = frame("S1")
        words[12:16] = [1, 1, 3, 6]
        self.assertEqual(decode_frame("S1", words)["payload"], [1, 1, 3, 6])
        words[15] = 16
        with self.assertRaises(ValueError):
            decode_frame("S1", words)

    def test_malformed_frames(self):
        for index, value in [(0, 0x0200), (1, 3), (2, 5), (11, 7), (19, 1), (26, 2), (27, 1), (28, 1)]:
            with self.subTest(index=index):
                words = frame("S1")
                words[index] = value
                with self.assertRaises(ValueError):
                    decode_frame("S1", words)
        with self.assertRaises(ValueError):
            decode_frame("S1", frame("S1")[:-1])

    def test_rejected_invalid_authorization_is_decodable(self):
        block = [0, 7, 1, 1000, 0, 0, 1, 0, 0]
        words = frame("S3", record=block)
        words[24:26] = [4, 3]
        self.assertEqual(decode_frame("S3", words)["record"].status, "rejected")

    def test_frozen_age_and_regression(self):
        adapter = ModbusDeviceAdapter(None)
        def observe(sequence, age, now):
            value = decode_frame("S1", frame("S1", sequence, age=age))
            value["received"] = now
            return adapter._fresh("S1", value, now)
        self.assertFalse(observe(1, 0, 0)[0])
        self.assertTrue(observe(2, 0, 0.05)[0])
        self.assertTrue(observe(3, 1510, 0.1)[0])
        self.assertEqual(observe(3, 1510, 0.7), (False, 2110))
        self.assertFalse(observe(1, 0, 0.8)[0])

    def test_serial_factory_disables_retries(self):
        # Construction inside a running loop is required by the async client.
        async def check():
            adapter = ModbusDeviceAdapter.from_settings(Settings(transport="USB", modbus_serial_port="COM99"))
            self.assertEqual(type(adapter.client).__name__, "AsyncModbusSerialClient")
            self.assertEqual(adapter.client.ctx.retries, 0)
            await adapter.close()
        asyncio.run(check())


class TcpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sequence = 0
        self.records = {}
        self.writes = []
        self.drop = False
        self.wrong_function = False
        self.bad_node = None
        self.connections = set()
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.adapter = ModbusDeviceAdapter.from_settings(Settings(modbus_port=self.port, modbus_timeout_seconds=0.3))

    async def asyncTearDown(self):
        await self.adapter.close()
        self.server.close()
        await self.server.wait_closed()
        for writer in list(self.connections):
            writer.close()
            await writer.wait_closed()

    async def handle(self, reader, writer):
        self.connections.add(writer)
        try:
            while True:
                tid, protocol, length, unit = struct.unpack(">HHHB", await reader.readexactly(7))
                request = await reader.readexactly(length-1)
                function = request[0]
                node = next(n for n, identifier in NODE_IDS.items() if identifier == unit)
                if function == 4:
                    self.sequence += 1
                    words = frame(node, self.sequence, record=self.records.get(unit))
                    if self.bad_node == node:
                        words[0] = 0x0100
                    response = bytes([4, 74]) + struct.pack(">37H", *words)
                elif function == 6:
                    self.writes.append((unit, 6, request))
                    response = request
                elif function == 16:
                    block = list(struct.unpack(">9H", request[6:]))
                    self.records[unit] = block
                    self.writes.append((unit, 16, block))
                    if self.drop:
                        self.drop = False
                        writer.close()
                        return
                    response = request[:5]
                    if self.wrong_function:
                        response = bytes([6]) + response[1:]
                else:
                    response = bytes([function | 128, 1])
                writer.write(struct.pack(">HHHB", tid, protocol, len(response)+1, unit) + response)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.connections.discard(writer)
            writer.close()

    async def warm(self):
        for _ in range(5):
            telemetry = await self.adapter.read_telemetry()
        return telemetry

    def command(self, node="S3", identifier=7):
        return DeviceCommand.from_internal(node_id=node, command_id=identifier, operation="open", ttl_ms=1000,
            authorization="capacity" if node == "S3" else "payment", expected_boot_epoch=1)

    async def test_poll_and_gateway_invalidation(self):
        telemetry = await self.warm()
        self.assertTrue(all(s.quality == "valid" for s in telemetry.slots))
        self.bad_node = "G"
        telemetry = await self.adapter.read_telemetry()
        self.assertTrue(all(s.occupied is None for s in telemetry.slots))
        self.bad_node = None
        self.assertTrue(all(s.occupied is None for s in (await self.adapter.read_telemetry()).slots))
        self.assertTrue(all(s.quality == "valid" for s in (await self.warm()).slots))

    async def test_lease_and_exact_record_each_lane(self):
        await self.warm()
        for node in ("S3", "S4"):
            command = self.command(node)
            self.assertEqual((await self.adapter.submit(command)).status, "done")
            self.assertEqual([entry[:2] for entry in self.writes[-2:]], [(NODE_IDS[node], 6), (NODE_IDS[node], 16)])
            self.assertEqual((await self.adapter.read_command(self.command(node, 8))).status, "unknown")
            self.assertEqual((await self.adapter.read_passage(node, 7, 1)).state, "unavailable")

    async def test_lost_write_response_reconciles_without_resend(self):
        await self.warm()
        self.drop = True
        command = self.command()
        with self.assertLogs("pymodbus", level="ERROR"):
            self.assertEqual((await self.adapter.submit(command)).status, "unknown")
        self.assertEqual((await self.adapter.read_command(command)).status, "unknown")
        self.assertEqual((await self.adapter.read_command(command)).status, "done")
        self.assertEqual(sum(w[1] == 16 for w in self.writes), 1)

    async def test_incompatible_station_blocks_write(self):
        await self.warm()
        self.bad_node = "S3"
        self.assertEqual((await self.adapter.submit(self.command())).status, "unknown")
        self.assertEqual(self.writes, [])

    async def test_wrong_function_response_never_repeats_fc16(self):
        await self.warm()
        self.wrong_function = True
        with self.assertLogs("pymodbus", level="ERROR"):
            result = await self.adapter.submit(self.command())
        self.assertEqual(result.status, "unknown")
        self.assertEqual(sum(w[1] == 16 for w in self.writes), 1)

    async def test_hardware_worker_persists_unknown_without_passage(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ParkingService(Database(Path(directory) / "hardware.sqlite3"), mode="hardware")
            service.recover()
            for _ in range(7):
                service.ingest_telemetry(await self.adapter.read_telemetry())
            service.admit(CommandRequest.model_validate({"commandId": "entry", "action": {"type": "enter", "plate": "B1HW"}}))
            stop = asyncio.Event()
            task = asyncio.create_task(hardware_worker(service, self.adapter, stop, 0.01))
            try:
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if service.get_command("entry").status == "unknown":
                        break
                self.assertEqual(service.get_command("entry").status, "unknown")
                self.assertEqual(sum(w[1] == 16 for w in self.writes), 1)
                with service.db.transaction(write=False) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT state FROM claims").fetchone()[0], "held")
                    self.assertEqual(connection.execute("SELECT value FROM metadata WHERE key='device_boot_floor:S3'").fetchone()[0], "1")
            finally:
                stop.set()
                await task
            restored = ParkingService(Database(Path(directory) / "hardware.sqlite3"), mode="hardware")
            restored.recover()
            stop = asyncio.Event()
            task = asyncio.create_task(hardware_worker(restored, self.adapter, stop, 0.01))
            try:
                initial = self.sequence
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if self.sequence > initial + 25:
                        break
                self.assertGreater(self.sequence, initial + 25)
                self.assertEqual(restored.get_command("entry").status, "unknown")
                self.assertEqual(sum(w[1] == 16 for w in self.writes), 1)
            finally:
                stop.set()
                await task


class RtuWireTests(TcpTests):
    """RTU ADUs/CRC over a local byte stream, not a physical serial-port test."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.adapter.close()
        trace = self.adapter.client.ctx.trace_pdu
        guard = self.adapter.write_guard
        self.adapter = ModbusDeviceAdapter(AsyncModbusTcpClient(
            "127.0.0.1", port=self.port, framer=FramerType.RTU, retries=0, timeout=0.3,
            reconnect_delay=0, trace_pdu=trace), write_guard=guard)
        self.corrupt_crc = False

    async def handle(self, reader, writer):
        self.connections.add(writer)
        try:
            while True:
                header = await reader.readexactly(6)
                unit, function = header[:2]
                if function == 16:
                    size = await reader.readexactly(1)
                    data = await reader.readexactly(size[0])
                    header += size + data
                crc = int.from_bytes(await reader.readexactly(2), "big")
                if not FramerRTU.check_CRC(header, crc):
                    raise ConnectionError("Invalid request CRC")
                node = next(n for n, identifier in NODE_IDS.items() if identifier == unit)
                if function == 4:
                    self.sequence += 1
                    words = frame(node, self.sequence, record=self.records.get(unit))
                    if self.bad_node == node:
                        words[0] = 0x0100
                    response = bytes([unit, 4, 74]) + struct.pack(">37H", *words)
                elif function == 6:
                    self.writes.append((unit, 6, header[1:]))
                    response = header
                else:
                    block = list(struct.unpack(">9H", header[7:]))
                    self.writes.append((unit, 16, block))
                    self.records[unit] = block
                    if self.drop:
                        self.drop = False
                        writer.close()
                        return
                    response = header[:6]
                    if self.wrong_function:
                        response = bytes([unit, 6]) + response[2:]
                checksum = FramerRTU.compute_CRC(response)
                if self.corrupt_crc:
                    checksum ^= 1
                writer.write(response + checksum.to_bytes(2, "big"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.connections.discard(writer)
            writer.close()

    async def test_bad_crc_invalidates_telemetry(self):
        await self.warm()
        self.corrupt_crc = True
        with self.assertLogs("pymodbus", level="ERROR"):
            data = await self.adapter.read_telemetry()
        self.assertTrue(all(slot.occupied is None for slot in data.slots))
