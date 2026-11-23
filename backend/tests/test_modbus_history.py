"""Controlled observation histories, including real SQLite claim preservation."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts.api import CommandRequest
from app.contracts.firmware import NODE_IDS, DeviceCommand, DeviceTelemetry
from app.hardware import boot_floors
from app.modbus import ModbusDeviceAdapter, decode_frame
from app.parking import ParkingService
from app.storage import Database
from test_modbus import frame


class Nodes:
    connected = True

    def __init__(self):
        self.now = 0
        self.boot = dict.fromkeys(NODE_IDS, 1)
        self.sequence = dict.fromkeys(NODE_IDS, 0)
        self.frozen = set()
        self.offline = set()
        self.ages = {}
        self.records = {}
        self.mask = 31
        self.reads, self.writes = [], []

    async def connect(self):
        self.connected = True
        return True

    def close(self):
        self.connected = False

    async def read_input_registers(self, address, *, count, device_id):
        node = next(n for n, identifier in NODE_IDS.items() if identifier == device_id)
        self.reads.append(node)
        self.now += 0.01
        if node in self.offline:
            self.now += 0.3
            raise TimeoutError(node)
        if node not in self.frozen:
            self.sequence[node] += 1
        words = frame(node, self.sequence[node], age=self.ages.get(node, 0))
        words[4:6] = [0, self.boot[node]]
        if node == "G":
            words[12] = self.mask
        if node in self.records:
            command, status, code = self.records[node]
            words[20:27] = [0, command.expected_boot_epoch, 0, command.command_id, status, code, 1]
            words[28:] = command.registers()
        return SimpleNamespace(registers=words, isError=lambda: False)

    async def write_register(self, address, value, *, device_id):
        self.writes.append((device_id, 6))
        return SimpleNamespace(address=address, registers=[value], isError=lambda: False)

    async def write_registers(self, address, values, *, device_id):
        self.writes.append((device_id, 16))
        return SimpleNamespace(address=address, count=len(values), isError=lambda: False)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.nodes = Nodes()
        self.adapter = ModbusDeviceAdapter(self.nodes, monotonic=lambda: self.nodes.now,
                                           wall=lambda: 1_800_000_000 + self.nodes.now)

    async def warm(self, service=None):
        for _ in range(7):
            telemetry = await self.adapter.read_telemetry()
            if service:
                service.ingest_telemetry(telemetry)
        return telemetry

    def command(self, boot=1):
        return DeviceCommand.from_internal(node_id="S3", command_id=1, operation="open", ttl_ms=1000,
                                           authorization="capacity", expected_boot_epoch=boot)

    async def test_repeated_first_sample_after_reboot_never_proves_progress(self):
        await self.warm()
        self.adapter._interrupt("S3")
        self.nodes.boot["S3"] = 2
        self.nodes.sequence["S3"] = 1
        self.nodes.frozen.add("S3")
        for _ in range(3):
            telemetry = await self.adapter.read_telemetry()
            self.assertEqual(telemetry.barriers[0].state, "UNKNOWN")
            self.assertEqual((await self.adapter.submit(self.command(2))).status, "unknown")
        self.assertEqual(self.nodes.writes, [])
        self.nodes.frozen.remove("S3")
        self.assertEqual((await self.adapter.read_telemetry()).barriers[0].quality, "valid")

    async def test_wrap_requires_temporal_continuity(self):
        self.nodes.sequence["S3"] = 2**32 - 4
        await self.adapter.read_telemetry()
        await self.adapter.read_telemetry()
        self.nodes.now += 3
        self.nodes.sequence["S3"] = 0
        self.assertEqual((await self.adapter.read_telemetry()).barriers[0].state, "UNKNOWN")
        self.assertGreater(self.adapter.history["S3"]["key"][1], 2**32 - 4)
        self.nodes.frozen.add("S3")
        for _ in range(3):
            self.assertEqual((await self.adapter.read_telemetry()).barriers[0].state, "UNKNOWN")
        self.nodes.frozen.remove("S3")
        for _ in range(4):
            telemetry = await self.adapter.read_telemetry()
        self.assertEqual(telemetry.barriers[0].quality, "valid")
        self.assertLess(self.adapter.history["S3"]["key"][1], 10)

    async def test_offline_target_is_not_read_during_result_or_submit(self):
        await self.warm()
        self.nodes.mask &= ~(1 << 2)
        self.nodes.offline.add("S3")
        self.nodes.reads.clear()
        for _ in range(3):
            self.assertEqual((await self.adapter.read_command(self.command())).status, "unknown")
            self.assertEqual((await self.adapter.submit(self.command())).status, "unknown")
        self.assertNotIn("S3", self.nodes.reads)
        self.assertEqual(self.nodes.writes, [])

    async def test_restart_boot_floor_blocks_old_refusal_at_adapter_and_service(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parking.sqlite3"
            def service():
                return ParkingService(Database(path), mode="hardware",
                    clock_ms=lambda: int((1_800_000_000+self.nodes.now)*1000), monotonic_ms=lambda: int(self.nodes.now*1000))
            active = service()
            await self.warm(active)
            active.admit(CommandRequest.model_validate({"commandId": "enter", "action": {"type": "enter", "plate": "B1RST"}}))
            active.process("enter")
            command = active.claim_dispatch("enter")
            self.nodes.boot["S3"] = 2
            await self.warm(active)
            self.assertEqual(boot_floors(active)["S3"], 2)
            restored = service()
            restored.recover()
            self.nodes.boot["S3"] = 1
            self.nodes.records["S3"] = (command, 4, 2)
            self.adapter = ModbusDeviceAdapter(self.nodes, monotonic=lambda: self.nodes.now)
            await self.warm(restored)
            # Even an unseeded external adapter cannot bypass the transactional floor.
            result = await self.adapter.read_command(command)
            self.assertEqual(result.status, "rejected")
            self.assertEqual(restored.record_device_result("enter", result).status, "unknown")
            with restored.db.transaction(write=False) as connection:
                self.assertEqual(connection.execute("SELECT state FROM claims").fetchone()[0], "held")
                self.assertEqual(connection.execute("SELECT status FROM sessions").fetchone()[0], "pending_entry")
            self.adapter.seed_boot_floors(boot_floors(restored))
            self.assertEqual((await self.adapter.read_command(command)).status, "unknown")

    async def test_first_new_boot_frame_is_durable_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parking.sqlite3"
            def create():
                return ParkingService(Database(path), mode="hardware", monotonic_ms=lambda: int(self.nodes.now*1000))
            service = create()
            await self.warm(service)
            service.admit(CommandRequest.model_validate({"commandId": "enter", "action": {"type": "enter", "plate": "B1FIRST"}}))
            service.process("enter")
            command = service.claim_dispatch("enter")
            async def observe(node, boot):
                service.record_boot_observation(node, boot)
                raise RuntimeError("stop before telemetry publication")
            self.adapter.boot_observer = observe
            self.nodes.boot["S3"] = 2
            with self.assertRaisesRegex(RuntimeError, "stop before"):
                await self.adapter._frame("S3")
            with service.db.transaction(write=False) as connection:
                self.assertEqual(connection.execute("SELECT boot_epoch FROM telemetry_history WHERE node_id='S3'").fetchone()[0], 1)
            restored = create()
            restored.recover()
            self.assertEqual(boot_floors(restored)["S3"], 2)
            self.nodes.boot["S3"] = 1
            self.nodes.records["S3"] = (command, 4, 2)
            self.adapter = ModbusDeviceAdapter(self.nodes, monotonic=lambda: self.nodes.now)
            await self.warm(restored)
            result = await self.adapter.read_command(command)
            self.assertEqual(result.status, "rejected")
            self.assertEqual(restored.record_device_result("enter", result).status, "unknown")
            self.adapter.seed_boot_floors(boot_floors(restored))
            self.assertEqual((await self.adapter.read_command(command)).status, "unknown")
            with restored.db.transaction(write=False) as connection:
                self.assertEqual(connection.execute("SELECT state FROM claims").fetchone()[0], "held")
                self.assertEqual(connection.execute("SELECT status FROM sessions").fetchone()[0], "pending_entry")

    async def test_new_identity_invalidates_cached_snapshot_before_next_poll(self):
        for node in ("S3", "S1", "G"):
            with self.subTest(node=node), tempfile.TemporaryDirectory() as directory:
                self.nodes = Nodes()
                self.adapter = ModbusDeviceAdapter(self.nodes, monotonic=lambda: self.nodes.now)
                service = ParkingService(Database(Path(directory) / "parking.sqlite3"), mode="hardware",
                    monotonic_ms=lambda: int(self.nodes.now*1000))
                await self.warm()
                for _ in range(3):
                    data = (await self.adapter.read_telemetry()).model_dump(by_alias=True)
                    data["slots"][0]["occupied"] = True
                    service.ingest_telemetry(DeviceTelemetry.model_validate(data))
                self.assertEqual(service.get_capacity().available, 3)
                self.assertEqual(service.get_telemetry().barriers[0].state, "CLOSED")
                with service.db.transaction(write=False) as connection:
                    cached = connection.execute("SELECT payload_json FROM telemetry").fetchone()[0]
                async def observe(identifier, boot):
                    service.record_boot_observation(identifier, boot)
                self.adapter.set_boot_observer(observe)
                self.nodes.boot[node] = 2
                await self.adapter._frame(node)
                # No fresh DTO has been ingested: both public and business reads
                # must apply the durable identity floor to the old cached JSON.
                telemetry = service.get_telemetry()
                snapshot = service.snapshot()
                station = next(item for item in snapshot.stations if item.id == node)
                self.assertNotEqual(station.quality, "valid")
                self.assertFalse(station.online)
                if node in ("S3", "G"):
                    self.assertEqual(telemetry.barriers[0].state, "UNKNOWN")
                    self.assertEqual(snapshot.barriers[0].state, "UNKNOWN")
                if node in ("S1", "G"):
                    self.assertIsNone(service.get_capacity().available)
                    self.assertIsNone(snapshot.capacity.available)
                    self.assertTrue(all(item.occupied is None for item in snapshot.slots if node == "G" or item.node_id == "S1"))
                else:
                    self.assertEqual(snapshot.capacity.available, 3)
                    self.assertTrue(all(item.quality == "valid" for item in snapshot.slots))
                if node == "G":
                    self.assertTrue(all(item.quality != "valid" for item in snapshot.stations))
                    self.assertTrue(all(item.state == "UNKNOWN" for item in snapshot.barriers))
                service.admit(CommandRequest.model_validate({"commandId": "entry", "action": {"type": "enter", "plate": "B1CACHE"}}))
                self.assertEqual(service.process("entry").status, "rejected")
                with service.db.transaction(write=False) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM device_commands").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT payload_json FROM telemetry").fetchone()[0], cached)

    async def test_cached_boot_floor_blocks_prepared_dispatch(self):
        for node in ("S3", "S1", "G"):
            with self.subTest(node=node), tempfile.TemporaryDirectory() as directory:
                self.nodes = Nodes()
                self.adapter = ModbusDeviceAdapter(self.nodes, monotonic=lambda: self.nodes.now)
                service = ParkingService(Database(Path(directory) / "parking.sqlite3"), mode="hardware",
                    monotonic_ms=lambda: int(self.nodes.now*1000))
                await self.warm(service)
                service.admit(CommandRequest.model_validate({"commandId": "entry", "action": {"type": "enter", "plate": "B1PREP"}}))
                self.assertEqual(service.process("entry").status, "executing")
                service.record_boot_observation(node, 2)
                self.assertIsNone(service.claim_dispatch("entry"))
                self.assertEqual(service.get_command("entry").status, "unknown")
                with service.db.transaction(write=False) as connection:
                    row = connection.execute("SELECT send_state,sent_at FROM device_commands").fetchone()
                    self.assertEqual(row["send_state"], "prepared")
                    self.assertIsNone(row["sent_at"])
                    self.assertEqual(connection.execute("SELECT state FROM claims").fetchone()[0], "held")

    async def test_expired_wrap_candidate_anchor_is_not_refreshed(self):
        def sample(sequence, age, now):
            value = decode_frame("S3", frame("S3", sequence, age=age))
            value["received"] = now
            return self.adapter._fresh("S3", value, now)[0]
        sample(2**32-2, 0, 0)
        self.assertTrue(sample(2**32-1, 0, 0.01))
        self.assertFalse(sample(1, 1500, 3))
        anchor = self.adapter.candidates["S3"].copy()
        self.assertFalse(sample(1, 0, 3.6))
        self.assertEqual(self.adapter.candidates["S3"], anchor)
        self.assertFalse(sample(2, 0, 3.61))
        self.assertTrue(sample(3, 0, 3.62))

    async def test_expired_wrap_candidate_anchor_is_not_refreshed_in_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ParkingService(Database(Path(directory) / "parking.sqlite3"), monotonic_ms=lambda: int(self.nodes.now*1000))
            source = (await self.warm()).model_dump(by_alias=True)
            def publish(sequence, age=0):
                data = DeviceTelemetry.model_validate(source).model_dump(by_alias=True)
                for item in [*data["stations"], *data["slots"], *data["barriers"]]:
                    item["ageMs"] = 0
                for station in data["stations"]:
                    self.nodes.sequence[station["id"]] += 1
                    station["sampleSequence"] = self.nodes.sequence[station["id"]]
                data["stations"][3].update(sampleSequence=sequence, ageMs=age)
                data["barriers"][0]["ageMs"] = age
                service.ingest_telemetry(DeviceTelemetry.model_validate(data))
                with service.db.transaction(write=False) as connection:
                    row = dict(connection.execute("SELECT * FROM telemetry_history WHERE node_id='S3'").fetchone())
                    candidate = connection.execute("SELECT value FROM metadata WHERE key='telemetry_candidate:S3'").fetchone()
                    return row, candidate[0] if candidate else None
            for sequence in (2**32-3, 2**32-2, 2**32-1):
                publish(sequence)
            self.nodes.now += 3
            publish(2**32-1)
            publish(2**32-1)
            row, candidate = publish(1, 1500)
            self.nodes.now += 0.6
            self.assertEqual(publish(1)[1], candidate)
            self.assertEqual(publish(2)[0]["sequence"], 2**32-1)
            self.assertEqual(publish(3)[0]["continuity"], 2)

    async def test_persistent_wrap_candidate_needs_progress_and_survives_restart_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parking.sqlite3"
            def create():
                return ParkingService(Database(path), monotonic_ms=lambda: int(self.nodes.now*1000))
            active = create()
            source = (await self.warm()).model_dump(by_alias=True)
            async def publish(sequence):
                self.nodes.now += 0.01
                data = DeviceTelemetry.model_validate(source).model_dump(by_alias=True)
                for station in data["stations"]:
                    self.nodes.sequence[station["id"]] += 1
                    station["sampleSequence"] = self.nodes.sequence[station["id"]]
                data["stations"][3]["sampleSequence"] = sequence
                active.ingest_telemetry(DeviceTelemetry.model_validate(data))
                with active.db.transaction(write=False) as connection:
                    return dict(connection.execute("SELECT * FROM telemetry_history WHERE node_id='S3'").fetchone())
            await publish(2**32-2)
            await publish(2**32-1)
            self.nodes.now += 3
            self.assertEqual((await publish(1))["sequence"], 2**32-1)
            self.assertEqual((await publish(1))["sequence"], 2**32-1)
            self.assertEqual((await publish(1))["sequence"], 2**32-1)
            with active.db.transaction(write=False) as connection:
                self.assertIsNotNone(connection.execute("SELECT value FROM metadata WHERE key='telemetry_candidate:S3'").fetchone())
            active = create()
            active.recover()
            # Stored monotonic candidates do not constitute proof in a new runtime.
            self.assertEqual((await publish(2))["sequence"], 2**32-1)
            for value in range(3, 10):
                row = await publish(value)
            self.assertEqual(row["sequence"], 9)
            self.assertEqual(row["continuity"], 2)
            self.assertEqual((await publish(2**32-2))["sequence"], 9)

    async def test_one_timed_out_unit_does_not_invalidate_other_nodes(self):
        self.nodes.offline.add("S5")
        for _ in range(6):
            telemetry = await self.adapter.read_telemetry()
        self.assertEqual(telemetry.stations[0].quality, "valid")
        self.assertTrue(all(slot.quality == "valid" for slot in telemetry.slots))
        self.assertTrue(all(b.quality == "valid" for b in telemetry.barriers))
        self.assertEqual(telemetry.stations[-1].quality, "unknown")

    async def test_offline_gateway_mask_skips_unit_reads(self):
        self.nodes.mask = 15
        await self.warm()
        self.assertNotIn("S5", self.nodes.reads)
        self.assertIn("S4", self.nodes.reads)

    async def test_old_boot_refusal_cannot_release_persistent_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ParkingService(Database(Path(directory) / "parking.sqlite3"), mode="hardware",
                clock_ms=lambda: int((1_800_000_000+self.nodes.now)*1000), monotonic_ms=lambda: int(self.nodes.now*1000))
            await self.warm(service)
            service.admit(CommandRequest.model_validate({"commandId": "enter", "action": {"type": "enter", "plate": "B1REG"}}))
            service.process("enter")
            command = service.claim_dispatch("enter")
            self.assertIsNotNone(command)
            self.nodes.boot["S3"] = 2
            await self.adapter.read_telemetry()
            await self.adapter.read_telemetry()
            self.nodes.boot["S3"] = 1
            self.nodes.ages["S3"] = 5000
            self.nodes.records["S3"] = (command, 4, 2)
            result = await self.adapter.read_command(command)
            self.assertEqual(result.status, "unknown")
            service.record_device_result("enter", result)
            with service.db.transaction(write=False) as connection:
                self.assertEqual(connection.execute("SELECT state FROM claims").fetchone()[0], "held")
                self.assertEqual(connection.execute("SELECT status FROM sessions").fetchone()[0], "pending_entry")
            self.assertEqual(self.adapter.history["S3"]["key"][0], 2)

    async def test_stale_gateway_or_target_cannot_confirm_refusal(self):
        for node in ("G", "S3"):
            with self.subTest(node=node):
                await self.warm()
                self.nodes.records["S3"] = (self.command(), 4, 2)
                self.nodes.ages[node] = 5000
                self.assertEqual((await self.adapter.read_command(self.command())).status, "unknown")
                self.nodes.ages.clear()

    async def test_retained_command_record_in_current_observations_remains_usable(self):
        await self.warm()
        self.nodes.records["S3"] = (self.command(), 4, 2)
        for _ in range(8):
            self.assertEqual((await self.adapter.read_command(self.command())).status, "rejected")
            self.nodes.now += 0.5
