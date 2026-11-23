"""HTTP boundary tests use temporary SQLite and no network/device simulation."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.contracts.api import ParkingSnapshot
from app.contracts.firmware import DeviceCommandResult, DeviceTelemetry, PassageEvidence
from app.main import create_app
from app.parking import ParkingService
from app.settings import Settings
from app.storage import Database
from app.worker import process_batch


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "parking.sqlite3"
        self.service = ParkingService(Database(self.path), clock_ms=lambda: 1_800_000_000_000,
                                      monotonic_ms=lambda: 1000)
        self.settings = Settings(database_path=self.path, worker_enabled=False, simulator_enabled=False)
        self.app = create_app(self.settings, service=self.service)
        self.client = self.enterContext(TestClient(self.app, raise_server_exceptions=False))

    def warm_telemetry(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "contracts/examples/snapshot-unknown.json").read_text(encoding="utf-8"))
        data = {key: data[key] for key in ("stations", "slots", "barriers")}
        for index in range(1, 4):
            for station in data["stations"]:
                station.update(quality="valid", updatedAt=1_800_000_000_000, ageMs=0, online=True,
                               schemaVersion=513, bootEpoch=7, sampleSequence=index)
            for slot in data["slots"]:
                slot.pop("sessionId", None)
                slot.update(quality="valid", updatedAt=1_800_000_000_000, ageMs=0, occupied=False)
            for barrier in data["barriers"]:
                barrier.update(quality="valid", updatedAt=1_800_000_000_000, ageMs=0,
                               state="CLOSED", obstacle=False, vehiclePresent=True, feedback="estimated")
            self.service.ingest_telemetry(DeviceTelemetry.model_validate(data))

    def test_health_snapshot_and_real_openapi(self):
        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "healthy", "service": "smart-parking-backend", "version": "0.1.0"})
        snapshot = self.client.get("/api/v1/snapshot")
        self.assertEqual(snapshot.status_code, 200)
        validated = ParkingSnapshot.model_validate(snapshot.json())
        self.assertIsNone(validated.capacity.available)
        self.assertTrue(all(slot.occupied is None for slot in validated.slots))
        self.assertEqual(snapshot.headers["cache-control"], "no-store")
        spec = self.client.get("/openapi.json").json()
        self.assertEqual(len(spec["paths"]), 7)
        self.assertEqual(spec["paths"]["/api/v1/commands"]["post"]["operationId"], "submitCommand")

    def test_admission_replay_conflict_and_persistent_refusal(self):
        body = {"commandId": "entry-1", "action": {"type": "enter", "plate": "b 101 dem"}}
        first = self.client.post("/api/v1/commands", json=body)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["status"], "accepted")
        self.assertEqual(self.client.post("/api/v1/commands", json=body).status_code, 200)
        conflict = self.client.post("/api/v1/commands", json=body | {"action": {"type": "enter", "plate": "B 2 DEM"}})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")
        self.service.process("entry-1")  # no telemetry: persistent business refusal
        result = self.client.get("/api/v1/commands/entry-1").json()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"]["code"], "DATA_UNAVAILABLE")
        replay = self.client.post("/api/v1/commands", json=body)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["status"], "rejected")

    def test_validation_uses_camelcase_strict_types_and_uniform_errors(self):
        for body in (
            {"command_id": "c1", "action": {"type": "pay", "session_id": "s1"}},
            {"commandId": "c1", "action": {"type": "set-slot-sensor", "slotId": 1, "occupied": "false"}},
            {"commandId": "c1", "action": {"type": "pay", "sessionId": "s1"}, "extra": True},
        ):
            response = self.client.post("/api/v1/commands", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
            self.assertNotIn("detail", response.json())
        self.assertEqual(self.service.pending_commands(), [])
        for url in ("/api/v1/events?limit=0", "/api/v1/sessions?limit=201",
                    "/api/v1/events?cursor=bad%20cursor", "/api/v1/commands/bad.id"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        for url in ("/api/v1/commands/missing", "/api/v1/sessions/missing", "/api/v1/not-found"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_sessions_and_paginated_event_export(self):
        self.warm_telemetry()
        self.client.post("/api/v1/commands", json={"commandId": "entry", "action": {"type": "enter", "plate": "B 1 DEM"}})
        self.service.process("entry")
        command = self.client.get("/api/v1/commands/entry").json()
        session_id = command["sessionId"]
        self.assertEqual(self.client.get(f"/api/v1/sessions/{session_id}").json()["status"], "pending_entry")
        page = self.client.get("/api/v1/sessions?limit=1").json()
        self.assertEqual(page["items"][0]["id"], session_id)
        events, cursor = [], None
        while True:
            response = self.client.get("/api/v1/events", params={"limit": 1, **({"cursor": cursor} if cursor else {})})
            self.assertEqual(response.status_code, 200)
            page = response.json()
            events.extend(page["items"])
            cursor = page["nextCursor"]
            if cursor is None:
                break
        self.assertEqual(len(events), len({event["id"] for event in events}))
        self.assertGreaterEqual(len(events), 2)

    def test_snapshot_is_one_database_read_transaction_under_concurrent_write(self):
        self.warm_telemetry()
        original_capacity = self.service._capacity
        invoked = False

        def capacity_with_write(connection, telemetry):
            nonlocal invoked
            if not invoked:
                invoked = True
                def writer():
                    from app.contracts.api import CommandRequest
                    self.service.admit(CommandRequest.model_validate({"commandId": "concurrent", "action": {"type": "enter", "plate": "B 2 DEM"}}))
                    self.service.process("concurrent")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(writer).result(timeout=4)
            return original_capacity(connection, telemetry)

        with patch.object(self.service, "_capacity", side_effect=capacity_with_write):
            response = self.client.get("/api/v1/snapshot")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["capacity"]["outstandingClaims"], 0)
        self.assertEqual(response.json()["commands"], [])
        self.assertEqual(self.service.get_capacity().outstanding_claims, 1)

    def test_worker_processes_after_acceptance_and_stops_on_shutdown(self):
        settings = self.settings.model_copy(update={"worker_enabled": True, "worker_interval_seconds": 0.05})
        app = create_app(settings, service=self.service)
        with TestClient(app) as client:
            response = client.post("/api/v1/commands", json={"commandId": "pay", "action": {"type": "pay", "sessionId": "missing"}})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "accepted")
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                result = client.get("/api/v1/commands/pay").json()
                if result["status"] != "accepted":
                    break
                time.sleep(0.02)
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["error"]["code"], "NOT_FOUND")
        self.assertTrue(app.state.worker_task.done())

    def test_internal_and_database_errors_do_not_expose_details(self):
        with patch.object(self.service, "snapshot", side_effect=RuntimeError("PRIVATE_SECRET")):
            with self.assertLogs("app.main", level="ERROR"):
                response = self.client.get("/api/v1/snapshot")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
            self.assertNotIn("PRIVATE_SECRET", response.text)
        busy = sqlite3.OperationalError("database is locked")
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        with patch.object(self.service, "admit", side_effect=busy):
            response = self.client.post("/api/v1/commands", json={"commandId": "busy", "action": {"type": "pay", "sessionId": "missing"}})
            self.assertEqual(response.status_code, 503)
            self.assertTrue(response.json()["error"]["retryable"])
            self.assertEqual(self.service.pending_commands(), [])

    def test_failed_queue_batch_does_not_starve_later_commands(self):
        from app.contracts.api import CommandRequest
        # IDs sort at one fixed creation timestamp; the good command follows 50 failures.
        for identifier in [*[f"bad-{i:02d}" for i in range(50)], "good"]:
            self.service.admit(CommandRequest.model_validate({"commandId": identifier, "action": {"type": "pay", "sessionId": "missing"}}))
        original = self.service.process
        retries = {}
        def process(identifier):
            if identifier.startswith("bad-"):
                raise sqlite3.OperationalError("injected")
            return original(identifier)
        with patch.object(self.service, "process", side_effect=process), self.assertLogs("app.worker", level="ERROR"):
            process_batch(self.service, retries)
            process_batch(self.service, retries)
        self.assertEqual(self.service.get_command("good").status, "rejected")
        self.assertEqual(self.service.get_command("bad-00").status, "accepted")

    def test_slow_failures_cannot_overtake_first_attempts_after_backoff_expires(self):
        from app.contracts.api import CommandRequest
        for identifier in [*[f"slow-{i:02d}" for i in range(51)], "zz-good"]:
            self.service.admit(CommandRequest.model_validate({"commandId": identifier, "action": {"type": "pay", "sessionId": "missing"}}))
        original, retries, attempts = self.service.process, {}, []
        now = [0.0]
        def slow_process(identifier):
            attempts.append(identifier)
            if identifier.startswith("slow-"):
                now[0] += 6  # one failure exceeds the entire backoff interval
                raise sqlite3.OperationalError("injected slow failure")
            return original(identifier)
        with patch.object(self.service, "process", side_effect=slow_process), self.assertLogs("app.worker", level="ERROR"):
            process_batch(self.service, retries, clock=lambda: now[0])
            self.assertEqual(len(attempts), 50)
            process_batch(self.service, retries, clock=lambda: now[0])
        self.assertEqual(attempts[50:52], ["slow-50", "zz-good"])
        self.assertEqual(self.service.get_command("zz-good").status, "rejected")

    def test_invalid_body_encoding_is_422_but_wrong_method_is_405_with_allow(self):
        for body in (b'\xff', b'{"commandId":"x","action":\xff}', b'{"commandId":'):
            response = self.client.post("/api/v1/commands", content=body,
                                        headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
            self.assertNotIn("Metodă HTTP nepermisă", response.json()["error"]["message"])
            self.assertEqual(set(response.json()), {"error"})
        self.assertEqual(self.service.pending_commands(), [])
        response = self.client.put("/api/v1/commands", json={})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["message"], "Metodă HTTP nepermisă.")
        self.assertIn("POST", response.headers["allow"])

    def test_closed_queue_retries_a_transient_failure_despite_51_slow_failures(self):
        from app.contracts.api import CommandRequest
        for identifier in [*[f"slow-{i:02d}" for i in range(51)], "zz-recoverable"]:
            self.service.admit(CommandRequest.model_validate({"commandId": identifier, "action": {"type": "pay", "sessionId": "missing"}}))
        original, retries, attempts = self.service.process, {}, []
        now = [0.0]
        def process(identifier):
            attempts.append(identifier)
            if identifier.startswith("slow-") or attempts.count(identifier) == 1:
                now[0] += 6
                raise sqlite3.OperationalError("injected slow or transient failure")
            return original(identifier)
        with patch.object(self.service, "process", side_effect=process), self.assertLogs("app.worker", level="ERROR"):
            for _ in range(3):
                process_batch(self.service, retries, clock=lambda: now[0])
        self.assertEqual(attempts.count("zz-recoverable"), 2)
        self.assertEqual(self.service.get_command("zz-recoverable").status, "rejected")
        self.assertNotIn("zz-recoverable", retries)

    def test_retries_follow_deadline_then_id_instead_of_creation_order(self):
        from app.contracts.api import CommandRequest
        for identifier in ("a-latest", "z-oldest", "m-oldest"):
            self.service.admit(CommandRequest.model_validate({"commandId": identifier, "action": {"type": "pay", "sessionId": "missing"}}))
        retries = {"a-latest": 20, "z-oldest": 10, "m-oldest": 10}
        original, attempts = self.service.process, []
        def process(identifier):
            attempts.append(identifier)
            return original(identifier)
        with patch.object(self.service, "process", side_effect=process):
            process_batch(self.service, retries, clock=lambda: 30)
        self.assertEqual(attempts, ["m-oldest", "z-oldest", "a-latest"])

    def test_http_entry_payment_exit_with_explicit_adapter_evidence(self):
        self.warm_telemetry()
        def submit(identifier, action):
            response = self.client.post("/api/v1/commands", json={"commandId": identifier, "action": action})
            self.assertEqual(response.status_code, 202)
            self.service.process(identifier)
            return self.client.get(f"/api/v1/commands/{identifier}").json()

        def confirm(identifier):
            device = self.service.claim_dispatch(identifier)
            self.assertIsNotNone(device)
            self.service.record_device_result(identifier, DeviceCommandResult.from_internal(
                node_id=device.node_id, command_id=device.command_id, boot_epoch=device.expected_boot_epoch,
                status="accepted", result_code=0, command_block=device.registers(), evidence="simulation", reason="matched"))
            self.service.consume_passage(identifier, PassageEvidence.from_internal(
                node_id=device.node_id, command_id=device.command_id, boot_epoch=device.expected_boot_epoch,
                state="confirmed", source="simulation", evidence_id=f"proof-{identifier}", occurred_at=1_800_000_000_000,
                command_block=device.registers()))

        entry = submit("entry", {"type": "enter", "plate": "B 1 DEM"})
        session_id = entry["sessionId"]
        confirm("entry")
        self.assertEqual(self.client.get(f"/api/v1/sessions/{session_id}").json()["amountDueBani"], 500)
        self.assertEqual(submit("pay", {"type": "pay", "sessionId": session_id})["status"], "done")
        self.assertEqual(self.client.get(f"/api/v1/sessions/{session_id}").json()["paidBani"], 500)
        self.assertEqual(submit("exit", {"type": "exit", "sessionId": session_id})["status"], "executing")
        confirm("exit")
        self.assertEqual(self.client.get(f"/api/v1/sessions/{session_id}").json()["status"], "completed")
        snapshot = self.client.get("/api/v1/snapshot").json()
        self.assertEqual(snapshot["sessions"], [])
        self.assertEqual(snapshot["capacity"]["available"], 4)

    def test_http_replay_survives_application_restart(self):
        body = {"commandId": "restart", "action": {"type": "pay", "sessionId": "missing"}}
        self.assertEqual(self.client.post("/api/v1/commands", json=body).status_code, 202)
        new_app = create_app(self.settings)
        with TestClient(new_app) as client:
            self.assertEqual(client.post("/api/v1/commands", json=body).status_code, 200)
            new_app.state.parking.process("restart")
            replay = client.post("/api/v1/commands", json=body)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json()["error"]["code"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
