"""Business regressions use real SQLite transactions and explicit device evidence."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts.api import CommandRequest, DEVICE_SCHEMA_VERSION
from app.contracts.firmware import DeviceCommandResult, DeviceTelemetry, PassageEvidence
from app.parking import BusinessFault, ParkingService, tariff_bani
from app.storage import Database, SCHEMA


class Clock:
    def __init__(self):
        self.wall = 1_800_000_000_000
        self.mono = 1000

    def advance(self, delta):
        self.wall += delta
        self.mono += delta


class ParkingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "parking.sqlite3"
        self.db = Database(self.path)
        self.clock = Clock()
        self.service = ParkingService(self.db, clock_ms=lambda: self.clock.wall, monotonic_ms=lambda: self.clock.mono)
        self.sequence = 0
        self.occupied = [False] * 4
        self.refresh()

    def telemetry(self, occupied=None, *, obstacle=False, boot=7):
        self.sequence += 1
        occupied = self.occupied if occupied is None else occupied
        return DeviceTelemetry.model_validate({
            "stations": [dict(id=node, role=role, online=True, quality="valid", updatedAt=self.clock.wall,
                              ageMs=0, schemaVersion=DEVICE_SCHEMA_VERSION, bootEpoch=boot, sampleSequence=self.sequence)
                         for node, role in zip(["G", "S1", "S2", "S3", "S4", "S5"],
                                              ["gateway", "slots", "slots", "entry", "exit", "environment"])],
            "slots": [dict(id=i + 1, nodeId="S1" if i < 2 else "S2", occupied=value,
                           quality="valid", updatedAt=self.clock.wall, ageMs=0) for i, value in enumerate(occupied)],
            "barriers": [dict(id=lane, nodeId=node, state="CLOSED", obstacle=obstacle, vehiclePresent=True,
                              feedback="estimated", quality="valid", updatedAt=self.clock.wall, ageMs=0)
                         for lane, node in [("entry", "S3"), ("exit", "S4")]],
        })

    def refresh(self, **kwargs):
        # Observe actual forward progress for gateway, then station handshakes.
        for _ in range(3):
            self.service.ingest_telemetry(self.telemetry(**kwargs))

    def unavailable(self):
        data = self.telemetry().model_dump(by_alias=True)
        for station in data["stations"]:
            station.update(quality="unavailable", online=False, bootEpoch=None,
                           sampleSequence=None, schemaVersion=None, updatedAt=None, ageMs=None)
        for slot in data["slots"]:
            slot.update(quality="unavailable", occupied=None, updatedAt=None, ageMs=None)
        for barrier in data["barriers"]:
            barrier.update(quality="unavailable", state="UNKNOWN", obstacle=None,
                           vehiclePresent=None, feedback="unknown", updatedAt=None, ageMs=None)
        return DeviceTelemetry.model_validate(data)

    def request(self, identifier, action):
        return CommandRequest.model_validate({"commandId": identifier, "action": action})

    def run_action(self, identifier, action):
        self.service.admit(self.request(identifier, action))
        return self.service.process(identifier)

    def sent(self, identifier, action):
        result = self.run_action(identifier, action)
        self.assertEqual(result.status, "executing")
        device = self.service.claim_dispatch(identifier)
        self.assertIsNotNone(device)
        self.assertIsNone(self.service.claim_dispatch(identifier))
        return result, device

    def device_result(self, device, status="accepted", code=0):
        return DeviceCommandResult.from_internal(node_id=device.node_id, command_id=device.command_id,
            boot_epoch=device.expected_boot_epoch, status=status, result_code=code,
            command_block=None if status == "unknown" else device.registers(),
            evidence="unproven" if status == "unknown" else "simulation",
            reason="write-timeout" if status == "unknown" else "matched")

    def proof(self, device, identifier):
        return PassageEvidence.from_internal(node_id=device.node_id, command_id=device.command_id,
            boot_epoch=device.expected_boot_epoch, state="confirmed", source="simulation",
            evidence_id=identifier, occurred_at=self.clock.wall, command_block=device.registers())

    def enter(self, identifier="entry-1", plate="B 101 DEM", *, park=True):
        result, device = self.sent(identifier, {"type": "enter", "plate": plate})
        self.service.record_device_result(identifier, self.device_result(device))
        evidence = self.proof(device, f"passage-{identifier}")
        self.assertTrue(self.service.consume_passage(identifier, evidence))
        self.assertFalse(self.service.consume_passage(identifier, evidence))
        if park:
            slot = self.occupied.index(False)
            self.occupied[slot] = True
            self.assertTrue(self.service.account_occupancy(result.session_id, slot + 1, self.telemetry(), evidence_id=f"occupancy-{identifier}"))
        return result.session_id, device

    def count(self, table):
        with self.db.transaction(write=False) as connection:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_full_flow_and_payment_freeze_without_faking_free_sensor(self):
        session_id, _ = self.enter()
        self.clock.advance(3_600_001)
        self.refresh()
        self.assertEqual(self.service.get_session(session_id).amount_due_bani, 1000)
        paid = self.run_action("pay-1", {"type": "pay", "sessionId": session_id})
        self.assertEqual(paid.status, "done")
        self.clock.advance(10 * 3_600_000)
        self.refresh()
        self.assertEqual(self.service.get_session(session_id).amount_due_bani, 0)
        self.assertEqual(self.service.get_session(session_id).paid_bani, 1000)
        self.run_action("pay-again", {"type": "pay", "sessionId": session_id})
        self.assertEqual(self.count("payments"), 1)
        _, device = self.sent("exit-1", {"type": "exit", "sessionId": session_id})
        self.service.record_device_result("exit-1", self.device_result(device, "done", 1))
        self.assertEqual(self.service.get_command("exit-1").status, "unknown")
        self.assertEqual(self.service.get_session(session_id).status, "pending_exit")
        self.service.consume_passage("exit-1", self.proof(device, "exit-proof"))
        self.assertEqual(self.service.get_session(session_id).status, "completed")
        self.assertEqual(self.service.get_capacity().physical_occupied, 1)
        self.assertEqual(self.service.get_capacity().available, 3)
        self.occupied[0] = False
        self.refresh()
        self.assertEqual(self.service.get_capacity().available, 4)

    def test_normalized_replay_conflict_and_missing_session_are_persistent(self):
        request = self.request("entry-1", {"type": "enter", "plate": " b   101 dem "})
        self.assertFalse(self.service.admit(request).replayed)
        same = self.request("entry-1", {"type": "enter", "plate": "B 101 DEM"})
        self.assertTrue(self.service.admit(same).replayed)
        with self.assertRaises(BusinessFault) as context:
            self.service.admit(self.request("entry-1", {"type": "enter", "plate": "B 999 DEM"}))
        self.assertEqual(context.exception.detail.code, "IDEMPOTENCY_CONFLICT")
        absent = self.run_action("missing", {"type": "pay", "sessionId": "absent"})
        self.assertEqual((absent.status, absent.error.code), ("rejected", "NOT_FOUND"))
        self.assertEqual(self.service.admit(self.request("missing", {"type": "pay", "sessionId": "absent"})).result.status, "rejected")

    def test_unpaid_exit_cannot_be_revived_by_replay_after_payment(self):
        session_id, _ = self.enter()
        result = self.run_action("unpaid", {"type": "exit", "sessionId": session_id})
        self.assertEqual(result.error.code, "PAYMENT_REQUIRED")
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        replay = self.service.admit(self.request("unpaid", {"type": "exit", "sessionId": session_id}))
        self.assertEqual(replay.result.error.code, "PAYMENT_REQUIRED")
        self.assertEqual(self.service.process("unpaid").status, "rejected")

    def test_passage_keeps_last_claim_until_occupancy_transfer(self):
        self.occupied = [True, True, True, False]
        self.refresh()
        session_id, _ = self.enter(park=False)
        self.assertEqual(self.service.get_capacity().available, 0)
        result = self.run_action("second", {"type": "enter", "plate": "B 2 DEM"})
        self.assertEqual(result.error.code, "PARKING_FULL")
        self.occupied[3] = True
        self.service.account_occupancy(session_id, 4, self.telemetry(), evidence_id="park-last")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 0)
        self.assertEqual(self.service.get_capacity().available, 0)

    def test_raw_occupancy_cannot_consume_claim_and_ambiguous_count_is_unknown(self):
        self.enter(park=False)
        self.occupied[0] = True
        self.refresh()
        capacity = self.service.get_capacity()
        self.assertTrue(capacity.reconciliation_required)
        self.assertIsNone(capacity.available)
        self.assertEqual(capacity.outstanding_claims, 1)

    def test_concurrent_admission_processing_and_payment(self):
        self.occupied = [True, True, True, False]
        self.refresh()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda i: self.run_action(f"entry-{i}", {"type": "enter", "plate": f"B {i} DEM"}), range(2)))
        self.assertEqual(sum(result.status == "executing" for result in results), 1)
        self.assertEqual(self.count("claims"), 1)
        self.assertEqual(self.count("sessions"), 1)
        self.assertEqual(self.service.get_capacity().available, 0)

    def test_duplicate_plate_and_parallel_payments(self):
        session_id, _ = self.enter()
        result = self.run_action("duplicate", {"type": "enter", "plate": "b 101 dem"})
        self.assertEqual(result.error.code, "SESSION_CONFLICT")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda i: self.run_action(f"pay-{i}", {"type": "pay", "sessionId": session_id}), range(2)))
        self.assertTrue(all(result.status == "done" for result in results))
        self.assertEqual(self.count("payments"), 1)
        self.assertEqual(self.service.get_session(session_id).paid_bani, 500)

    def test_restart_preserves_intents_and_does_not_reuse_telemetry_or_resend(self):
        result, device = self.sent("entry-1", {"type": "enter", "plate": "B 1 DEM"})
        db2 = Database(self.path)
        service = ParkingService(db2, clock_ms=lambda: self.clock.wall, monotonic_ms=lambda: self.clock.mono)
        self.assertIsNone(service.get_telemetry())
        self.assertEqual(service.recover(), 1)
        self.assertEqual(service.get_command("entry-1").status, "unknown")
        self.assertEqual(service.get_capacity().outstanding_claims, 1)
        self.assertIsNone(service.claim_dispatch("entry-1"))
        replay = service.admit(self.request("entry-1", {"type": "enter", "plate": "B 1 DEM"}))
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result.session_id, result.session_id)
        self.assertEqual(self.count("device_commands"), 1)

    def test_definitive_refusal_releases_claim_but_timeout_and_conflict_do_not(self):
        result, device = self.sent("entry-1", {"type": "enter", "plate": "B 1 DEM"})
        self.service.record_device_result("entry-1", self.device_result(device, "rejected", 2))
        self.assertEqual(self.service.get_session(result.session_id).status, "cancelled")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 0)
        result, device = self.sent("entry-2", {"type": "enter", "plate": "B 2 DEM"})
        self.service.record_device_result("entry-2", self.device_result(device, "unknown", None))
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.service.record_device_result("entry-2", self.device_result(device))
        self.service.record_device_result("entry-2", self.device_result(device, "rejected", 2))
        self.assertEqual(self.service.get_command("entry-2").status, "unknown")
        self.service.record_device_result("entry-2", self.device_result(device, "rejected", 2))
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertEqual(self.service.get_command("entry-2").status, "unknown")

    def test_reingesting_same_sample_cannot_extend_its_lifetime(self):
        sample = self.telemetry()
        self.service.ingest_telemetry(sample)
        self.clock.advance(1500)
        self.service.ingest_telemetry(sample)
        self.assertEqual(self.service.get_capacity().available, 4)
        self.clock.advance(600)
        self.service.ingest_telemetry(sample)
        self.assertIsNone(self.service.get_capacity().available)
        self.assertEqual(self.service.get_telemetry().slots[0].age_ms, 2100)

    def test_payment_and_passage_dedup_survive_cold_restart(self):
        session_id, device = self.enter(park=False)
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        service = ParkingService(Database(self.path), clock_ms=lambda: self.clock.wall,
                                 monotonic_ms=lambda: self.clock.mono)
        service.recover()
        self.assertEqual(service.get_session(session_id).status, "paid")
        self.assertEqual(service.get_session(session_id).paid_bani, 500)
        self.assertFalse(service.consume_passage("entry-1", self.proof(device, "passage-entry-1")))
        replay = service.admit(self.request("pay", {"type": "pay", "sessionId": session_id}))
        self.assertEqual(replay.result.status, "done")
        self.assertEqual(self.count("payments"), 1)

    def test_stale_or_obstructed_dispatch_never_sends(self):
        result = self.run_action("entry-1", {"type": "enter", "plate": "B 1 DEM"})
        self.refresh(obstacle=True)
        self.assertIsNone(self.service.claim_dispatch("entry-1"))
        self.assertEqual(self.service.get_command("entry-1").status, "unknown")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.clock.advance(2000)
        self.assertIsNone(self.service.get_capacity().available)

    def test_evidence_is_bound_to_dispatch_and_consumed_once(self):
        result, device = self.sent("entry-1", {"type": "enter", "plate": "B 1 DEM"})
        self.service.record_device_result("entry-1", self.device_result(device))
        proof = self.proof(device, "proof-1")
        invalid = PassageEvidence.model_validate(proof.model_dump(by_alias=True) | {"occurredAt": self.clock.wall - 1})
        with self.assertRaises(BusinessFault):
            self.service.consume_passage("entry-1", invalid)
        self.assertEqual(self.count("evidence"), 0)
        self.assertTrue(self.service.consume_passage("entry-1", proof))
        self.assertFalse(self.service.consume_passage("entry-1", proof))
        self.assertEqual(self.count("evidence"), 1)
        with self.assertRaises(BusinessFault):
            self.service.consume_passage("entry-1", self.proof(device, "proof-2"))
        self.assertEqual(self.service.get_session(result.session_id).status, "active")

    def test_tariff_boundaries_stored_rate_and_clock_regression(self):
        self.assertEqual([tariff_bani(0, time, 500) for time in (0, 1, 3_600_000, 3_600_001)], [500, 500, 500, 1000])
        session_id, _ = self.enter()
        self.service.hourly_rate_bani = 900
        self.assertEqual(self.service.get_session(session_id).hourly_rate_bani, 500)
        self.clock.wall -= 1
        result = self.run_action("clock-pay", {"type": "pay", "sessionId": session_id})
        self.assertEqual(result.error.code, "DATA_UNAVAILABLE")
        self.assertEqual(self.count("payments"), 0)

    def test_atomic_rollback_replay_and_read_pagination(self):
        self.service.admit(self.request("accepted", {"type": "pay", "sessionId": "absent"}))
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as connection:
                connection.execute("UPDATE commands SET status='done' WHERE id='accepted'")
                raise RuntimeError("crash before commit")
        self.assertEqual(self.service.get_command("accepted").status, "accepted")
        self.assertIn("accepted", self.service.pending_commands())
        for i in range(3):
            self.run_action(f"missing-{i}", {"type": "pay", "sessionId": "absent"})
        first = self.service.list_events(limit=2)
        self.assertEqual(len(first.items), 2)
        second = self.service.list_events(limit=2, cursor=first.next_cursor)
        self.assertFalse({event.id for event in first.items} & {event.id for event in second.items})
        with self.assertRaises(BusinessFault):
            self.service.list_events(cursor="not a cursor")
        with self.db.transaction(write=False) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_payment_failure_rolls_back_business_effects_but_keeps_admission(self):
        session_id, _ = self.enter()
        self.service.admit(self.request("pay", {"type": "pay", "sessionId": session_id}))
        with self.db.transaction() as connection:
            connection.execute("""CREATE TRIGGER fail_payment_log BEFORE INSERT ON events
                WHEN NEW.code='PAYMENT_RECORDED' BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.process("pay")
        self.assertEqual(self.count("payments"), 0)
        self.assertEqual(self.service.get_session(session_id).status, "active")
        self.assertEqual(self.service.get_command("pay").status, "accepted")
        with self.db.transaction() as connection:
            connection.execute("DROP TRIGGER fail_payment_log")
        self.assertEqual(self.service.process("pay").status, "done")
        self.assertEqual(self.count("payments"), 1)

    def test_simulation_proof_and_demo_command_are_rejected_in_hardware(self):
        service = ParkingService(Database(Path(self.directory.name) / "hardware.sqlite3"), mode="hardware",
                                 clock_ms=lambda: self.clock.wall, monotonic_ms=lambda: self.clock.mono)
        for _ in range(3):
            service.ingest_telemetry(self.telemetry())
        service.admit(self.request("demo", {"type": "set-slot-sensor", "slotId": 1, "occupied": True}))
        self.assertEqual(service.process("demo").error.code, "SIMULATION_ONLY")
        service.admit(self.request("entry", {"type": "enter", "plate": "B 1 DEM"}))
        result = service.process("entry")
        device = service.claim_dispatch("entry")
        observed = self.device_result(device).model_dump(by_alias=True) | {"evidence": "coherent-record"}
        service.record_device_result("entry", DeviceCommandResult.model_validate(observed))
        with self.assertRaises(BusinessFault):
            service.consume_passage("entry", self.proof(device, "hardware-proof"))
        self.assertEqual(service.get_session(result.session_id).status, "pending_entry")

    def test_parallel_consumption_and_occupancy_replay(self):
        result, device = self.sent("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.service.record_device_result("entry", self.device_result(device))
        proof = self.proof(device, "passage")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.service.consume_passage("entry", proof), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.occupied[0] = True
        telemetry = self.telemetry()
        self.assertTrue(self.service.account_occupancy(result.session_id, 1, telemetry, evidence_id="occupancy"))
        self.assertFalse(self.service.account_occupancy(result.session_id, 1, telemetry, evidence_id="occupancy"))
        self.assertEqual(self.count("evidence"), 2)
        self.assertEqual(self.service.get_capacity().available, 3)

    def test_numeric_id_exhaustion_rolls_back_session_and_claim(self):
        with self.db.transaction() as connection:
            connection.execute("INSERT INTO device_counters VALUES ('S3',7,4294967295)")
        result = self.run_action("overflow", {"type": "enter", "plate": "B 1 DEM"})
        self.assertEqual(result.error.code, "DEVICE_INCOMPATIBLE")
        self.assertEqual(self.count("sessions"), 0)
        self.assertEqual(self.count("claims"), 0)
        self.assertEqual(self.count("device_commands"), 0)

    def test_older_free_snapshot_cannot_replace_newer_full_snapshot(self):
        old = self.service.get_telemetry()
        self.occupied = [True] * 4
        self.refresh()
        self.assertEqual(self.service.get_capacity().available, 0)
        self.service.ingest_telemetry(old)
        self.assertIsNone(self.service.get_capacity().available)
        rejected = self.run_action("stale-entry", {"type": "enter", "plate": "B OLD DEM"})
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(self.count("claims"), 0)
        self.refresh()
        self.assertEqual(self.service.get_capacity().available, 0)

    def test_unavailable_public_snapshot_preserves_expired_sample_history(self):
        old = self.service.get_telemetry()
        self.clock.advance(2500)
        self.service.ingest_telemetry(self.unavailable())
        for _ in range(3):
            self.service.ingest_telemetry(old)
            self.assertIsNone(self.service.get_capacity().available)
        self.refresh()
        self.assertEqual(self.service.get_capacity().available, 4)

    def test_sequence_wrap_needs_continuity_and_old_boot_never_returns(self):
        def frame(sequence, boot):
            data = self.telemetry().model_dump(by_alias=True)
            for station in data["stations"]:
                station.update(sampleSequence=sequence, bootEpoch=boot)
            return DeviceTelemetry.model_validate(data)

        for sequence in (0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF):
            self.service.ingest_telemetry(frame(sequence, 8))
        self.assertEqual(self.service.get_capacity().available, 4)
        self.service.ingest_telemetry(frame(0, 8))
        self.assertEqual(self.service.get_capacity().available, 4)
        self.service.ingest_telemetry(frame(1, 7))
        self.assertIsNone(self.service.get_capacity().available)
        # A wrap observed only AFTER an outage is ambiguous, unlike the one above.
        for sequence in (0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF):
            self.service.ingest_telemetry(frame(sequence, 9))
        self.service.ingest_telemetry(self.unavailable())
        for sequence in (0, 1, 2):
            self.service.ingest_telemetry(frame(sequence, 9))
            self.assertIsNone(self.service.get_capacity().available)
        for sequence in (1, 2, 3):
            self.service.ingest_telemetry(frame(sequence, 10))
        self.assertEqual(self.service.get_capacity().available, 4)

    def test_contradiction_survives_later_progress_restart_and_passage(self):
        result, device = self.sent("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.service.record_device_result("entry", self.device_result(device))
        self.service.record_device_result("entry", self.device_result(device, "rejected", 2))
        self.service = ParkingService(Database(self.path), clock_ms=lambda: self.clock.wall,
                                      monotonic_ms=lambda: self.clock.mono)
        self.service.recover()
        for status, code in (("accepted", 0), ("done", 1)):
            self.assertEqual(self.service.record_device_result("entry", self.device_result(device, status, code)).status, "unknown")
            with self.assertRaises(BusinessFault):
                self.service.consume_passage("entry", self.proof(device, "contradicted-proof"))
        self.assertEqual(self.service.get_session(result.session_id).status, "pending_entry")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertEqual(self.count("evidence"), 0)

    def test_progress_after_terminal_refusal_freezes_capacity_and_cannot_confirm(self):
        result, device = self.sent("entry", {"type": "enter", "plate": "B 1 DEM"})
        self.service.record_device_result("entry", self.device_result(device, "rejected", 2))
        self.assertEqual(self.service.get_capacity().available, 4)
        self.assertEqual(self.service.get_session(result.session_id).status, "cancelled")
        self.assertEqual(self.service.record_device_result("entry", self.device_result(device)).status, "unknown")
        self.assertTrue(self.service.get_capacity().reconciliation_required)
        self.assertIsNone(self.service.get_capacity().available)
        with self.assertRaises(BusinessFault):
            self.service.consume_passage("entry", self.proof(device, "late-proof"))
        # Neither another accepted nor a new sensor snapshot clears the latch.
        self.refresh()
        self.service.record_device_result("entry", self.device_result(device, "done", 1))
        self.assertIsNone(self.service.get_capacity().available)

    def test_occupancy_transfer_validates_the_effective_saved_snapshot(self):
        session_id, _ = self.enter(park=False)
        baseline = self.service.get_telemetry()
        evidence_count = self.count("evidence")
        self.clock.advance(1000)
        incoming = self.telemetry([True, False, False, False]).model_dump(by_alias=True)
        incoming["staleAfterMs"] = 500
        gateway = next(station for station in incoming["stations"] if station["id"] == "G")
        gateway["sampleSequence"] = baseline.stations[0].sample_sequence
        with self.assertRaises(BusinessFault):
            self.service.account_occupancy(session_id, 1, DeviceTelemetry.model_validate(incoming), evidence_id="expired-accounting")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertIsNone(self.service.get_session(session_id).slot_id)
        self.assertEqual(self.count("evidence"), evidence_count)
        self.refresh()
        self.assertEqual(self.service.get_capacity().available, 3)

    def test_prepared_entry_is_cancelled_on_restart_and_barrier_is_reusable(self):
        prepared = self.run_action("prepared", {"type": "enter", "plate": "B 1 DEM"})
        self.service = ParkingService(Database(self.path), clock_ms=lambda: self.clock.wall,
                                      monotonic_ms=lambda: self.clock.mono)
        self.assertEqual(self.service.recover(), 1)
        self.assertEqual(self.service.get_command("prepared").status, "rejected")
        self.assertEqual(self.service.get_session(prepared.session_id).status, "cancelled")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 0)
        self.assertIsNone(self.service.claim_dispatch("prepared"))
        self.refresh()
        result, device = self.sent("new-entry", {"type": "enter", "plate": "B 1 DEM"})
        self.assertEqual(result.status, "executing")
        self.assertEqual(device.command_id, 2)  # old numeric ID remains consumed

    def test_prepared_exit_is_cancelled_to_paid_on_restart(self):
        session_id, _ = self.enter()
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        self.run_action("prepared-exit", {"type": "exit", "sessionId": session_id})
        self.service = ParkingService(Database(self.path), clock_ms=lambda: self.clock.wall,
                                      monotonic_ms=lambda: self.clock.mono)
        self.service.recover()
        self.assertEqual(self.service.get_session(session_id).status, "paid")
        self.assertEqual(self.service.get_command("prepared-exit").status, "rejected")
        self.assertIsNone(self.service.claim_dispatch("prepared-exit"))
        self.refresh()
        self.assertEqual(self.run_action("new-exit", {"type": "exit", "sessionId": session_id}).status, "executing")

    def test_v1_database_migration_preserves_admitted_command(self):
        path = Path(self.directory.name) / "version1.sqlite3"
        connection = sqlite3.connect(path)
        try:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute("""INSERT INTO commands (id,action_json,mode,status,created_at,updated_at,message)
                VALUES ('old','{"type":"pay","sessionId":"missing"}','simulation','accepted',1,1,'accepted')""")
            connection.execute("PRAGMA user_version=1")
            connection.commit()
        finally:
            connection.close()
        service = ParkingService(Database(path))
        self.assertEqual(service.get_command("old").status, "accepted")
        with service.db.transaction(write=False) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_entry_contradiction_blocks_an_already_prepared_exit_dispatch(self):
        session_id, entry_device = self.enter(park=False)
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        self.assertEqual(self.run_action("exit", {"type": "exit", "sessionId": session_id}).status, "executing")
        self.service.record_device_result("entry-1", self.device_result(entry_device, "rejected", 2))
        self.assertIsNone(self.service.claim_dispatch("exit"))
        self.assertEqual(self.service.get_command("exit").status, "unknown")
        self.assertEqual(self.service.get_session(session_id).status, "pending_exit")
        with self.db.transaction(write=False) as connection:
            row = connection.execute("SELECT send_state,sent_at FROM device_commands WHERE command_id='exit'").fetchone()
            self.assertEqual(tuple(row), ("prepared", None))

    def test_entry_contradiction_after_exit_dispatch_blocks_exit_passage(self):
        session_id, entry_device = self.enter(park=False)
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        _, exit_device = self.sent("exit", {"type": "exit", "sessionId": session_id})
        self.service.record_device_result("exit", self.device_result(exit_device))
        self.service.record_device_result("entry-1", self.device_result(entry_device, "rejected", 2))
        evidence_count = self.count("evidence")
        with self.assertRaises(BusinessFault) as failure:
            self.service.consume_passage("exit", self.proof(exit_device, "blocked-exit"))
        self.assertEqual(failure.exception.detail.code, "SESSION_CONFLICT")
        self.assertEqual(self.service.get_session(session_id).status, "pending_exit")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)
        self.assertEqual(self.count("evidence"), evidence_count)

    def test_exit_contradiction_blocks_occupancy_without_any_database_mutation(self):
        session_id, _ = self.enter(park=False)
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        _, exit_device = self.sent("exit", {"type": "exit", "sessionId": session_id})
        self.service.record_device_result("exit", self.device_result(exit_device, "rejected", 2))
        self.service.record_device_result("exit", self.device_result(exit_device))
        self.assertEqual(self.service.get_session(session_id).status, "paid")

        def relevant_state():
            with self.db.transaction(write=False) as connection:
                return {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
                        for table in ("sessions", "claims", "evidence", "telemetry", "telemetry_history", "events")}

        before = relevant_state()
        incoming = self.telemetry([True, False, False, False])
        with self.assertRaises(BusinessFault) as failure:
            self.service.account_occupancy(session_id, 1, incoming, evidence_id="blocked-occupancy")
        self.assertEqual(failure.exception.detail.code, "SESSION_CONFLICT")
        self.assertEqual(relevant_state(), before)
        self.assertIsNone(self.service.get_session(session_id).slot_id)
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)

    def test_sibling_mcu_refusal_cannot_restore_a_contradictory_session_to_paid(self):
        session_id, entry_device = self.enter(park=False)
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        _, exit_device = self.sent("exit", {"type": "exit", "sessionId": session_id})
        self.service.record_device_result("entry-1", self.device_result(entry_device, "rejected", 2))
        result = self.service.record_device_result("exit", self.device_result(exit_device, "rejected", 2))
        self.assertEqual(result.status, "unknown")
        self.assertEqual(self.service.get_session(session_id).status, "pending_exit")
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)

    def test_recovery_cancels_unsent_exit_without_unfreezing_contradictory_session(self):
        session_id, entry_device = self.enter(park=False)
        self.run_action("pay", {"type": "pay", "sessionId": session_id})
        self.run_action("exit", {"type": "exit", "sessionId": session_id})
        self.service.record_device_result("entry-1", self.device_result(entry_device, "rejected", 2))
        service = ParkingService(Database(self.path), clock_ms=lambda: self.clock.wall,
                                 monotonic_ms=lambda: self.clock.mono)
        service.recover()
        self.assertEqual(service.get_command("exit").status, "rejected")
        self.assertEqual(service.get_session(session_id).status, "pending_exit")
        self.assertEqual(service.get_capacity().outstanding_claims, 1)
        self.assertIsNone(service.claim_dispatch("exit"))
        with service.db.transaction(write=False) as connection:
            self.assertEqual(connection.execute("SELECT contradiction FROM device_commands WHERE command_id='entry-1'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
