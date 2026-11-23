"""Virtual device/business integration, including durable state and atomic failure."""

import asyncio
import sqlite3
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.contracts.api import CommandRequest
from app.contracts.firmware import DeviceCommand
from app.main import create_app
from app.parking import ParkingService
from app.settings import Settings
from app.simulator import SimulatedDeviceAdapter, SimulatorRuntime
from app.storage import Database, MIGRATION_2, SCHEMA


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "simulation.sqlite3"
        self.wall, self.mono = 1_800_000_000_000, 1000
        self.service = ParkingService(Database(self.path), clock_ms=lambda: self.wall, monotonic_ms=lambda: self.mono)
        self.service.recover()
        self.runtime = SimulatorRuntime(self.service, step_delay_ms=50)
        self.runtime.connect()
        self.retries = {}

    def step(self, delta=50):
        self.wall += delta
        self.mono += delta
        self.runtime.cycle(self.retries)

    def action(self, identifier, action):
        self.service.admit(CommandRequest.model_validate({"commandId": identifier, "action": action}))
        self.runtime.cycle(self.retries)
        return self.service.get_command(identifier)

    def finish(self, identifier):
        for _ in range(20):
            result = self.service.get_command(identifier)
            if result.status in ("done", "rejected", "unknown"):
                return result
            self.step()
        self.fail(f"Command {identifier} never settled")

    def enter(self, identifier="entry", plate="B 1 DEM"):
        self.action(identifier, {"type": "enter", "plate": plate})
        result = self.finish(identifier)
        self.assertEqual(result.status, "done")
        self.step()  # finish local barrier closing before the next access
        return result.session_id

    def world(self):
        with self.service.db.transaction(write=False) as connection:
            return self.runtime.adapter.world(connection)

    def test_timed_entry_payment_exit_and_persistent_physical_state(self):
        self.assertEqual(self.service.get_capacity().available, 4)
        result = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.assertEqual(self.world().barriers["entry"].state, "OPENING")
        self.step(49)
        self.assertEqual(self.world().barriers["entry"].state, "OPENING")
        self.step(1)
        self.assertEqual(self.world().barriers["entry"].state, "OPEN")
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.step(50)
        self.assertEqual(self.service.get_command("entry").status, "done")
        session = self.service.get_session(result.session_id)
        self.assertEqual((session.status, session.slot_id), ("active", 1))
        self.assertEqual(self.world().occupied, [True, False, False, False])
        self.assertEqual(self.service.get_capacity().outstanding_claims, 0)
        self.step()
        self.assertEqual(self.action("pay", {"type": "pay", "sessionId": session.id}).status, "done")
        self.assertTrue(self.world().occupied[0])
        self.action("exit", {"type": "exit", "sessionId": session.id})
        self.assertEqual(self.finish("exit").status, "done")
        self.assertEqual(self.service.get_session(session.id).status, "completed")
        self.assertEqual(self.service.get_capacity().available, 4)
        self.assertFalse(any(self.world().occupied))

    def test_demo_sensor_presence_transport_and_full_capacity(self):
        self.action("presence", {"type": "set-barrier-presence", "barrierId": "entry", "present": True})
        self.step(500)
        self.assertEqual(self.world().barriers["entry"].state, "CLOSED")
        self.assertEqual(self.service.open_sessions(), [])
        self.action("full", {"type": "set-all-slot-sensors", "occupied": True})
        self.assertEqual(self.service.get_capacity().available, 0)
        rejected = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.assertEqual(rejected.error.code, "PARKING_FULL")
        self.action("free", {"type": "set-slot-sensor", "slotId": 1, "occupied": False})
        self.assertEqual(self.service.get_capacity().available, 1)
        self.action("usb", {"type": "set-transport", "transport": "USB"})
        self.assertEqual(self.service.snapshot().transport, "USB")

    def test_node_loss_and_gateway_loss_publish_unknown_until_reconnected(self):
        self.action("s1-off", {"type": "set-node-online", "nodeId": "S1", "online": False})
        snapshot = self.service.snapshot()
        self.assertIsNone(snapshot.slots[0].occupied)
        self.assertIsNone(snapshot.slots[1].occupied)
        self.assertIsNone(snapshot.capacity.available)
        self.action("s1-on", {"type": "set-node-online", "nodeId": "S1", "online": True})
        self.assertEqual(self.service.get_capacity().available, 4)
        self.action("g-off", {"type": "set-node-online", "nodeId": "G", "online": False})
        self.assertTrue(all(slot.occupied is None for slot in self.service.snapshot().slots))
        self.action("g-on", {"type": "set-node-online", "nodeId": "G", "online": True})
        self.assertEqual(self.service.get_capacity().available, 4)

    def test_obstacle_holds_motion_and_presence_does_not_create_passage(self):
        self.runtime.auto_passage = False
        result = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.action("obstacle", {"type": "set-obstacle", "barrierId": "entry", "active": True})
        self.step(500)
        self.assertEqual(self.world().barriers["entry"].state, "OPENING")
        self.action("clear", {"type": "set-obstacle", "barrierId": "entry", "active": False})
        self.assertEqual(self.world().barriers["entry"].state, "OPEN")
        self.action("no-presence", {"type": "set-barrier-presence", "barrierId": "entry", "present": False})
        self.step(500)
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.runtime.auto_passage = True
        self.step()
        self.assertEqual(self.service.get_command("entry").status, "done")

    def test_disconnect_mid_access_never_creates_late_passage(self):
        result = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        device = self.service.get_device_command("entry")
        self.step()
        self.action("off", {"type": "set-node-online", "nodeId": "S3", "online": False})
        self.assertEqual(self.service.get_command("entry").status, "unknown")
        self.action("on", {"type": "set-node-online", "nodeId": "S3", "online": True})
        self.step(500)
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        passage = asyncio.run(self.runtime.adapter.read_passage(device.node_id, device.command_id, device.expected_boot_epoch))
        self.assertEqual(passage.state, "lost")
        self.assertEqual(asyncio.run(self.runtime.adapter.read_command(device)).status, "unknown")
        self.assertEqual(asyncio.run(self.runtime.adapter.submit(device)).status, "unknown")

    def assert_same_batch_outage_stays_lost(self, node):
        result = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        device = self.service.get_device_command("entry")
        self.step()  # OPEN
        self.wall += 50
        self.mono += 50  # passage would now be due
        for identifier, online in (("outage-0", False), ("outage-1", True)):
            self.service.admit(CommandRequest.model_validate({"commandId": identifier,
                "action": {"type": "set-node-online", "nodeId": node, "online": online}}))
        self.runtime.cycle(self.retries)
        self.assertEqual(self.service.get_command("outage-0").status, "done")
        self.assertEqual(self.service.get_command("outage-1").status, "done")
        self.assertEqual(self.service.get_command("entry").status, "unknown")
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertFalse(any(self.world().occupied))
        self.assertEqual(asyncio.run(self.runtime.adapter.read_command(device)).status, "unknown")
        self.assertEqual(asyncio.run(self.runtime.adapter.submit(device)).status, "unknown")
        self.assertEqual(asyncio.run(self.runtime.adapter.read_passage(device.node_id, device.command_id, device.expected_boot_epoch)).state, "lost")

    def test_same_batch_station_offline_online_cannot_confirm_passage(self):
        self.assert_same_batch_outage_stays_lost("S3")

    def test_same_batch_gateway_offline_online_cannot_confirm_passage(self):
        self.assert_same_batch_outage_stays_lost("G")

    def test_device_dedup_does_not_restart_deadline_and_conflict_cannot_steal_result(self):
        self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        command = self.service.get_device_command("entry")
        self.mono += 49
        self.wall += 49
        self.assertEqual(asyncio.run(self.runtime.adapter.submit(command)).status, "accepted")
        self.step(1)
        self.assertEqual(self.world().barriers["entry"].state, "OPEN")
        reset = DeviceCommand.from_internal(node_id=command.node_id, command_id=command.command_id,
                    operation="reset-fault", ttl_ms=0, authorization="none", expected_boot_epoch=command.expected_boot_epoch)
        self.assertEqual(asyncio.run(self.runtime.adapter.submit(reset)).result_code, 4)
        self.assertEqual(asyncio.run(self.runtime.adapter.read_command(command)).status, "unknown")
        self.step()
        self.assertEqual(self.service.get_command("entry").status, "unknown")
        self.assertFalse(any(self.world().occupied))
        self.action("off", {"type": "set-node-online", "nodeId": "S3", "online": False})
        self.action("on", {"type": "set-node-online", "nodeId": "S3", "online": True})
        self.assertEqual(asyncio.run(self.runtime.adapter.read_command(command)).status, "unknown")
        # Abandoning the original must not erase the newer conflicting request's record.
        self.assertEqual(asyncio.run(self.runtime.adapter.read_command(reset)).result_code, 4)

    def test_failed_access_rolls_back_its_passage_and_keeps_independent_demo_command(self):
        self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.step()  # barrier open, passage not yet generated
        self.wall += 50
        self.mono += 50
        self.service.admit(CommandRequest.model_validate({"commandId": "usb", "action": {"type": "set-transport", "transport": "USB"}}))
        with patch.object(self.service, "account_occupancy", side_effect=RuntimeError("injected after passage")):
            with self.assertLogs("app.simulator", level="ERROR"):
                self.runtime.cycle(self.retries)
        self.assertEqual(self.service.get_command("usb").status, "done")
        self.assertEqual(self.service.snapshot().transport, "USB")
        self.assertEqual(self.service.get_command("entry").status, "unknown")
        self.assertEqual(self.service.open_sessions()[0].status, "pending_entry")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertFalse(any(self.world().occupied))
        with self.service.db.transaction(write=False) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT phase FROM simulator_commands").fetchone()[0], "lost")
        self.runtime.cycle(self.retries)
        self.assertEqual(self.service.get_command("entry").status, "unknown")

    def test_regressed_utc_marks_one_access_uncertain_without_poisoning_cycles(self):
        result = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.step()
        self.wall -= 3_600_000
        self.mono += 50
        self.service.admit(CommandRequest.model_validate({"commandId": "usb", "action": {"type": "set-transport", "transport": "USB"}}))
        with self.assertLogs("app.simulator", level="ERROR"):
            self.runtime.cycle(self.retries)
        self.assertEqual(self.service.get_command("usb").status, "done")
        self.assertEqual(self.service.snapshot().transport, "USB")
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_command("entry").status, "unknown")
        self.assertFalse(any(self.world().occupied))
        self.action("tcp", {"type": "set-transport", "transport": "TCP"})
        self.assertEqual(self.service.get_command("tcp").status, "done")

    def test_failed_entry_does_not_rollback_the_other_lane_passage(self):
        first = self.enter("entry-1", "B 1 DEM")
        self.action("pay", {"type": "pay", "sessionId": first})
        second = self.action("entry-2", {"type": "enter", "plate": "B 2 DEM"})
        self.action("exit-1", {"type": "exit", "sessionId": first})
        self.step()
        self.wall += 50
        self.mono += 50
        with patch.object(self.service, "account_occupancy", side_effect=RuntimeError("entry-only failure")):
            with self.assertLogs("app.simulator", level="ERROR"):
                self.runtime.cycle(self.retries)
        self.assertEqual(self.service.get_command("entry-2").status, "unknown")
        self.assertEqual(self.service.get_session(second.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_command("exit-1").status, "done")
        self.assertEqual(self.service.get_session(first).status, "completed")
        self.assertFalse(any(self.world().occupied))
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)

    def test_restart_keeps_occupied_slots_and_payments_without_replaying_entry(self):
        session_id = self.enter()
        self.action("pay", {"type": "pay", "sessionId": session_id})
        old_boot = self.world().boot_epoch
        self.service = ParkingService(Database(self.path), clock_ms=lambda: self.wall, monotonic_ms=lambda: self.mono)
        self.service.recover()
        self.runtime = SimulatorRuntime(self.service, step_delay_ms=50)
        self.runtime.connect()
        self.assertEqual(self.world().boot_epoch, old_boot + 1)
        self.assertTrue(self.world().occupied[0])
        self.assertEqual(self.service.get_capacity().available, 3)
        self.assertEqual(self.service.get_session(session_id).paid_bani, 500)
        replay = self.service.admit(CommandRequest.model_validate({"commandId": "entry", "action": {"type": "enter", "plate": "B 1 DEM"}}))
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result.status, "done")

    def test_restart_in_flight_keeps_claim_and_never_sends_again(self):
        self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.service = ParkingService(Database(self.path), clock_ms=lambda: self.wall, monotonic_ms=lambda: self.mono)
        self.service.recover()
        self.runtime = SimulatorRuntime(self.service, step_delay_ms=50)
        self.runtime.connect()
        self.step(500)
        self.assertEqual(self.service.get_command("entry").status, "unknown")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertFalse(any(self.world().occupied))
        with self.service.db.transaction(write=False) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM simulator_commands").fetchone()[0], 1)

    def test_two_lanes_can_progress_without_unrelated_claim_becoming_ambiguous(self):
        first = self.enter("entry-1", "B 1 DEM")
        self.action("pay", {"type": "pay", "sessionId": first})
        self.action("entry-2", {"type": "enter", "plate": "B 2 DEM"})
        self.action("exit-1", {"type": "exit", "sessionId": first})
        self.assertEqual(self.finish("entry-2").status, "done")
        self.assertEqual(self.finish("exit-1").status, "done")
        snapshot = self.service.snapshot()
        self.assertFalse(snapshot.capacity.reconciliation_required)
        self.assertEqual(snapshot.capacity.available, 3)
        self.assertEqual(snapshot.capacity.outstanding_claims, 0)

    def test_partial_node_data_cannot_complete_a_virtual_entry(self):
        result = self.action("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.action("s1-off", {"type": "set-node-online", "nodeId": "S1", "online": False})
        self.step(500)
        self.step(500)
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertFalse(any(self.world().occupied))

    def test_nested_transactions_keep_inner_failure_and_outer_rollback_separate(self):
        with self.service.db.transaction() as connection:
            connection.execute("INSERT INTO metadata VALUES ('outer-test','kept')")
            with self.assertRaises(RuntimeError):
                with self.service.db.transaction() as nested:
                    self.assertIs(connection, nested)
                    nested.execute("INSERT INTO metadata VALUES ('inner-test','rolled-back')")
                    raise RuntimeError("inner failure")
            self.assertIsNone(connection.execute("SELECT value FROM metadata WHERE key='inner-test'").fetchone())
        with self.service.db.transaction(write=False) as connection:
            self.assertEqual(connection.execute("SELECT value FROM metadata WHERE key='outer-test'").fetchone()[0], "kept")
            with self.assertRaises(RuntimeError):
                with self.service.db.transaction():
                    self.fail("read-only unit must not permit a nested writer")

    def test_full_parking_rejects_fifth_vehicle_and_replay_never_adds_a_car(self):
        for index in range(4):
            self.enter(f"entry-{index}", f"B {index} DEM")
        self.assertEqual(self.service.get_capacity().available, 0)
        result = self.action("fifth", {"type": "enter", "plate": "B 5 DEM"})
        self.assertEqual(result.error.code, "PARKING_FULL")
        replay = self.service.admit(CommandRequest.model_validate({"commandId": "entry-0", "action": {"type": "enter", "plate": "B 0 DEM"}}))
        self.assertTrue(replay.replayed)
        self.runtime.cycle(self.retries)
        self.assertEqual(len(self.service.open_sessions()), 4)
        self.assertTrue(all(self.world().occupied))

    def test_adapter_lifecycle_and_hardware_mode_are_separate(self):
        boot = self.world().boot_epoch
        asyncio.run(self.runtime.adapter.connect())
        self.assertEqual(self.world().boot_epoch, boot)
        asyncio.run(self.runtime.adapter.close())
        with self.assertRaises(RuntimeError):
            asyncio.run(self.runtime.adapter.read_telemetry())
        hardware = ParkingService(Database(Path(self.directory.name) / "hardware.sqlite3"), mode="hardware")
        with self.assertRaises(ValueError):
            SimulatedDeviceAdapter(hardware)

    def test_v2_migration_adds_simulator_tables_without_losing_old_commands(self):
        path = Path(self.directory.name) / "version2.sqlite3"
        connection = sqlite3.connect(path)
        try:
            for statement in [*SCHEMA, *MIGRATION_2]:
                connection.execute(statement)
            connection.execute("""INSERT INTO commands (id,action_json,mode,status,created_at,updated_at,message)
                VALUES ('old','{"type":"pay","sessionId":"missing"}','simulation','accepted',1,1,'accepted')""")
            connection.execute("PRAGMA user_version=2")
            connection.commit()
        finally:
            connection.close()
        database = Database(path)
        with database.transaction(write=False) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT status FROM commands WHERE id='old'").fetchone()[0], "accepted")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM simulator_commands").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


class SimulatorHttpTests(unittest.TestCase):
    def test_real_worker_completes_api_flow_without_injected_telemetry_or_proofs(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(allow_anonymous_simulation=True, database_path=Path(directory) / "http.sqlite3", simulator_step_delay_ms=50,
                                worker_interval_seconds=0.05)
            with TestClient(create_app(settings)) as client:
                def execute(identifier, action):
                    response = client.post("/api/v1/commands", json={"commandId": identifier, "action": action})
                    self.assertEqual(response.status_code, 202)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        result = client.get(f"/api/v1/commands/{identifier}").json()
                        if result["status"] in ("done", "rejected", "unknown"):
                            self.assertEqual(result["status"], "done", result)
                            return result
                        time.sleep(0.02)
                    self.fail("Simulator command timeout")
                snapshot = client.get("/api/v1/snapshot").json()
                self.assertEqual(snapshot["capacity"]["available"], 4)
                entry = execute("entry", {"type": "enter", "plate": "B 101 DEM"})
                self.assertEqual(client.get("/api/v1/snapshot").json()["capacity"]["available"], 3)
                execute("pay", {"type": "pay", "sessionId": entry["sessionId"]})
                execute("exit", {"type": "exit", "sessionId": entry["sessionId"]})
                self.assertEqual(client.get(f"/api/v1/sessions/{entry['sessionId']}").json()["status"], "completed")
                self.assertEqual(client.get("/api/v1/snapshot").json()["capacity"]["available"], 4)
            with TestClient(create_app(settings)) as client:
                replay = client.post("/api/v1/commands", json={"commandId": "entry", "action": {"type": "enter", "plate": "B 101 DEM"}})
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(replay.json()["status"], "done")
                self.assertEqual(client.get("/api/v1/snapshot").json()["capacity"]["available"], 4)


if __name__ == "__main__":
    unittest.main()
