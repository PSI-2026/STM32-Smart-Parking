"""Contract edge cases that protect the future HTTP/device boundaries."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.contracts.api import Barrier, Capacity, CommandRequest, CommandResult, DEVICE_SCHEMA_VERSION, ParkingSession, ParkingSlot, ParkingSnapshot, Station
from app.contracts.firmware import OBSERVATION_COUNT, CommandObservation, DeviceCommand, DeviceCommandResult, DeviceTelemetry, FreshnessProof, PassageEvidence, SlotSample, passage_matches, result_for
from app.main import create_app
from app.settings import Settings


class ContractTests(unittest.TestCase):
    def test_rejected_echo_does_not_require_permission_to_emit_it(self):
        request = DeviceCommand.from_internal(node_id="S4", command_id=1, operation="open", ttl_ms=2000,
                                               authorization="payment", expected_boot_epoch=7)
        unauthorized_block = request.registers()
        unauthorized_block[4] = 0
        raw_result = dict(node_id="S4", command_id=1, boot_epoch=7, status="rejected", result_code=3,
                          command_block=unauthorized_block, evidence="coherent-record", reason="matched")
        record = DeviceCommandResult.from_internal(**raw_result)
        self.assertEqual(record.command_block, unauthorized_block)
        observed = CommandObservation.from_internal(node_id="S4", boot_epoch=7, record=record)
        self.assertEqual(result_for(request, observed).status, "unknown")
        with self.assertRaises(ValidationError):
            DeviceCommand.from_internal(node_id="S4", command_id=1, operation="open", ttl_ms=2000,
                                        authorization="none", expected_boot_epoch=7)
        with self.assertRaises(ValidationError):
            DeviceCommandResult.from_internal(**(raw_result | {"status": "done", "result_code": 1}))
        with self.assertRaises(ValidationError):
            DeviceCommandResult.from_internal(**(raw_result | {"command_block": unauthorized_block[:8]}))

    def valid_snapshot(self):
        path = Path(__file__).resolve().parents[1] / "contracts/examples/snapshot-unknown.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        for station in snapshot["stations"]:
            station.update(online=True, quality="valid", updatedAt=100, ageMs=0,
                           schemaVersion=DEVICE_SCHEMA_VERSION, bootEpoch=1, sampleSequence=1)
        for slot in snapshot["slots"]:
            slot.update(quality="valid", updatedAt=100, ageMs=0, occupied=False)
        for barrier in snapshot["barriers"]:
            barrier.update(quality="valid", updatedAt=100, ageMs=0, state="CLOSED",
                           obstacle=False, vehiclePresent=False, feedback="estimated")
        snapshot["capacity"].update(physicalOccupied=0, outstandingClaims=0, available=4)
        return snapshot

    def test_http_aliases_match_published_schema(self):
        camel = {"commandId": "c1", "action": {"type": "pay", "sessionId": "s1"}}
        CommandRequest.model_validate_json(json.dumps(camel))
        for payload in (
            {"command_id": "c1", "action": {"type": "pay", "session_id": "s1"}},
            camel | {"action": {"type": "pay", "session_id": "s1"}},
        ):
            with self.assertRaises(ValidationError):
                CommandRequest.model_validate_json(json.dumps(payload))
        schema = CommandRequest.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("commandId", schema["properties"])
        self.assertNotIn("command_id", schema["properties"])

    def test_lost_path_or_expired_sample_invalidates_children(self):
        ParkingSnapshot.model_validate(self.valid_snapshot())
        for node in ("G", "S1", "S3"):
            snapshot = self.valid_snapshot()
            station = next(s for s in snapshot["stations"] if s["id"] == node)
            station.update(quality="unavailable", online=False)
            with self.subTest(node=node), self.assertRaises(ValidationError):
                ParkingSnapshot.model_validate(snapshot)
        snapshot = self.valid_snapshot()
        snapshot["slots"][0]["ageMs"] = 2000
        with self.assertRaises(ValidationError):
            ParkingSnapshot.model_validate(snapshot)
        snapshot = self.valid_snapshot()
        snapshot["stations"][1]["schemaVersion"] = 0x0200
        with self.assertRaises(ValidationError):
            ParkingSnapshot.model_validate(snapshot)

    def test_adapter_has_same_path_rules_without_session_ids(self):
        snapshot = self.valid_snapshot()
        telemetry = {key: snapshot[key] for key in ("stations", "slots", "barriers")}
        with self.assertRaises(ValidationError):
            DeviceTelemetry.model_validate(telemetry)  # sessionId belongs to service only
        telemetry["slots"] = [{key: value for key, value in slot.items() if key != "sessionId"}
                              for slot in telemetry["slots"]]
        DeviceTelemetry.model_validate(telemetry)
        telemetry["stations"][0].update(quality="unavailable", online=False)
        with self.assertRaises(ValidationError):
            DeviceTelemetry.model_validate(telemetry)

    def test_repeated_reads_do_not_refresh_frozen_sample(self):
        proof = FreshnessProof.from_internal(sample_age_ms=0, round_trip_ms=1,
                    elapsed_since_response_ms=0, elapsed_since_sequence_first_seen_ms=2000, first_estimated_age_ms=0)
        self.assertEqual(proof.effective_age_ms(), 2000)
        proof = FreshnessProof.from_internal(sample_age_ms=1900, round_trip_ms=50,
                    elapsed_since_response_ms=100, elapsed_since_sequence_first_seen_ms=150, first_estimated_age_ms=1900)
        self.assertEqual(proof.effective_age_ms(), 2050)
        frozen = FreshnessProof.from_internal(sample_age_ms=1500, round_trip_ms=10,
                    elapsed_since_response_ms=0, elapsed_since_sequence_first_seen_ms=600, first_estimated_age_ms=1510)
        self.assertEqual(frozen.effective_age_ms(), 2110)

    def test_command_result_is_correlated_even_after_rejection_or_restart(self):
        request = DeviceCommand.from_internal(node_id="S4", command_id=2, operation="open", ttl_ms=2000,
                                               authorization="payment", expected_boot_epoch=7)
        params = dict(node_id="S4", command_id=2, boot_epoch=7, status="rejected", result_code=2,
                      evidence="coherent-record", reason="matched", command_block=request.registers())
        record = DeviceCommandResult.from_internal(**params)
        observed = CommandObservation.from_internal(node_id="S4", boot_epoch=7, record=record)
        self.assertEqual(result_for(request, observed).status, "rejected")
        old_request = DeviceCommand.from_internal(**(dict(node_id="S4", command_id=1, operation="open", ttl_ms=2000,
                                               authorization="payment", expected_boot_epoch=7)))
        self.assertEqual(result_for(old_request, observed).reason, "record-mismatch")
        self.assertIsNone(result_for(old_request, observed).result_code)
        restarted = CommandObservation.from_internal(node_id="S4", boot_epoch=8, record=record)
        self.assertEqual(result_for(request, restarted).reason, "boot-changed")
        self.assertEqual(result_for(request, None).status, "unknown")
        for changes in ({"status": "done", "result_code": 7},
                        {"status": "accepted", "result_code": 1},
                        {"status": "unknown", "result_code": 2},
                        {"evidence": "unproven"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                DeviceCommandResult.from_internal(**(params | changes))

    def test_passage_requires_explicit_correlated_evidence(self):
        request = DeviceCommand.from_internal(node_id="S3", command_id=1, operation="open", ttl_ms=2000,
                                               authorization="capacity", expected_boot_epoch=7)
        data = dict(node_id="S3", command_id=1, boot_epoch=7, state="confirmed", source="simulation",
                    evidence_id="event-1", occurred_at=1000, command_block=request.registers())
        evidence = PassageEvidence.from_internal(**data)
        self.assertTrue(passage_matches(request, evidence, mode="simulation", business_action="enter"))
        self.assertFalse(passage_matches(request, evidence, mode="hardware", business_action="enter"))
        self.assertFalse(passage_matches(request, evidence, mode="simulation", business_action="exit"))
        reset = DeviceCommand.from_internal(node_id="S3", command_id=1, operation="reset-fault", ttl_ms=0,
                                            authorization="none", expected_boot_epoch=7)
        self.assertFalse(passage_matches(reset, evidence, mode="simulation", business_action="enter"))
        changed_block = DeviceCommand.from_internal(node_id="S3", command_id=1, operation="open", ttl_ms=3000,
                                                     authorization="capacity", expected_boot_epoch=7)
        self.assertFalse(passage_matches(changed_block, evidence, mode="simulation", business_action="enter"))
        for changes in ({"command_id": 2}, {"boot_epoch": 8}):
            other = DeviceCommand.from_internal(node_id="S3", command_id=changes.get("command_id", 1),
                operation="open", ttl_ms=2000, authorization="capacity", expected_boot_epoch=changes.get("boot_epoch", 7))
            self.assertFalse(passage_matches(other, evidence, mode="simulation", business_action="enter"))
        with self.assertRaises(ValidationError):
            PassageEvidence.from_internal(**(data | {"source": "none"}))

    def test_same_id_cannot_attribute_result_of_different_fc16_block(self):
        original = DeviceCommand.from_internal(node_id="S4", command_id=1, operation="open", ttl_ms=2000,
                                                authorization="payment", expected_boot_epoch=7)
        reset = DeviceCommand.from_internal(node_id="S4", command_id=1, operation="reset-fault", ttl_ms=0,
                                             authorization="none", expected_boot_epoch=7)
        success = DeviceCommandResult.from_internal(node_id="S4", command_id=1, boot_epoch=7,
            status="done", result_code=1, command_block=original.registers(), evidence="coherent-record", reason="matched")
        observed = CommandObservation.from_internal(node_id="S4", boot_epoch=7, record=success)
        self.assertEqual(result_for(original, observed).status, "done")
        self.assertEqual(result_for(reset, observed).status, "unknown")
        conflict = DeviceCommandResult.from_internal(node_id="S4", command_id=1, boot_epoch=7,
            status="rejected", result_code=4, command_block=reset.registers(), evidence="coherent-record", reason="matched")
        observed = CommandObservation.from_internal(node_id="S4", boot_epoch=7, record=conflict)
        self.assertEqual(result_for(original, observed).status, "unknown")
        self.assertEqual(result_for(reset, observed).status, "rejected")

    def test_slot_validity_masks_must_agree_and_partial_count_is_unknown(self):
        sample = SlotSample.from_internal(header_valid_mask=1, payload_valid_mask=1,
                                          occupancy_mask=1, free_count=65535)
        self.assertEqual(sample.slot_states(), (True, None))
        for changes in ({"payload_valid_mask": 3}, {"header_valid_mask": 3}, {"free_count": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SlotSample.from_internal(**(dict(header_valid_mask=1, payload_valid_mask=1,
                                                 occupancy_mask=1, free_count=65535) | changes))

    def test_last_capacity_is_held_until_occupancy_accounted(self):
        for occupied, claims, available in ((3, 0, 1), (3, 1, 0), (3, 1, 0), (4, 0, 0)):
            Capacity.from_internal(physical_occupied=occupied, outstanding_claims=claims,
                                   available=available, reconciliation_required=False)
        with self.assertRaises(ValidationError):
            Capacity.from_internal(physical_occupied=3, outstanding_claims=1, available=1,
                                   reconciliation_required=False)
        Capacity.from_internal(physical_occupied=4, outstanding_claims=1, available=None,
                               reconciliation_required=True)

    def test_existing_health_and_runtime_spec_remain_compatible(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Settings(allow_anonymous_simulation=True,
            database_path=Path(directory) / "parking.sqlite3", worker_enabled=False, simulator_enabled=False))) as client:
            response = client.get("/api/v1/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "healthy", "service": "smart-parking-backend", "version": "0.1.0"})
            self.assertEqual(set(client.get("/openapi.json").json()["paths"]), {
                "/api/v1/health", "/api/v1/snapshot", "/api/v1/commands", "/api/v1/commands/{commandId}",
                "/api/v1/sessions", "/api/v1/sessions/{sessionId}", "/api/v1/events"})

    def test_station_identity_and_barrier_quality(self):
        sample = dict(quality="valid", updatedAt=100, ageMs=0)
        with self.assertRaises(ValidationError):
            Station.model_validate(sample | dict(id="S1", role="entry", online=True, schemaVersion=512, bootEpoch=1))
        barrier = sample | dict(id="entry", nodeId="S3", state="OPEN", obstacle=False,
                                vehiclePresent=True, feedback="estimated")
        Barrier.model_validate(barrier)
        for changes in ({"quality": "stale"}, {"nodeId": "S4"}, {"vehiclePresent": None}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Barrier.model_validate(barrier | changes)

    def test_session_and_command_time_invariants(self):
        session = dict(id="s1", plate="B 101 DEM", slotId=None, enteredAt=100,
                       exitedAt=200, status="completed", hourlyRateBani=500,
                       amountDueBani=0, paidBani=500)
        ParkingSession.model_validate(session)
        for changes in ({"enteredAt": None}, {"exitedAt": 99}, {"amountDueBani": 1},
                        {"status": "active"}, {"hourlyRateBani": 1.5}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ParkingSession.model_validate(session | changes)
        with self.assertRaises(ValidationError):
            CommandResult.from_internal(command_id="c1", status="accepted", message="ok", created_at=100, updated_at=99)

    def test_command_discriminator_and_strict_values(self):
        valid = {"commandId": "request-1", "action": {"type": "set-slot-sensor", "slotId": 1, "occupied": True}}
        self.assertEqual(CommandRequest.model_validate(valid).action.slot_id, 1)
        for action in (
            {"type": "set-slot-sensor", "slotId": 5, "occupied": True},
            {"type": "set-slot-sensor", "slotId": 1, "occupied": "false"},
            {"type": "pay", "sessionId": "session-1", "amount": 0},
            {"type": "unknown"}, {"type": "enter", "plate": "   "},
        ):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                CommandRequest.model_validate({"commandId": "request-1", "action": action})

    def test_unknown_slot_is_not_free(self):
        sample = dict(id=1, nodeId="S1", sessionId=None, quality="unknown", updatedAt=None, ageMs=None)
        self.assertIsNone(ParkingSlot.model_validate({**sample, "occupied": None}).occupied)
        for value in (False, True):
            with self.assertRaises(ValidationError):
                ParkingSlot.model_validate({**sample, "occupied": value})
        with self.assertRaises(ValidationError):
            ParkingSlot.model_validate({**sample, "occupied": False, "quality": "valid"})

    def test_device_command_word_order_and_authorization(self):
        params = dict(node_id="S4", command_id=0x12345678, operation="open", ttl_ms=2000,
                      authorization="payment", expected_boot_epoch=0x9ABCDEF0)
        self.assertEqual(DeviceCommand.from_internal(**params).registers(),
                         [0x1234, 0x5678, 1, 2000, 2, 0x9ABC, 0xDEF0, 0, 0])
        for changes in ({"authorization": "capacity"}, {"ttl_ms": 99},
                        {"command_id": 0}, {"command_id": 0x100000000},
                        {"operation": "reset-fault"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                DeviceCommand.from_internal(**(params | changes))
        reset = DeviceCommand.from_internal(**(params | {"operation": "reset-fault", "ttl_ms": 0, "authorization": "none"}))
        self.assertEqual(reset.registers()[2:5], [2, 0, 0])

    def test_generated_artifacts_and_snapshot_topology(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "export_contracts.py"
        spec = importlib.util.spec_from_file_location("export_contracts", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        artifacts = module.artifacts()
        snapshot = artifacts["examples/snapshot-unknown.json"]
        ParkingSnapshot.model_validate(snapshot)
        with self.assertRaises(ValidationError):
            ParkingSnapshot.model_validate(snapshot | {"slots": snapshot["slots"][:3]})
        openapi = artifacts["openapi.v1.json"]
        self.assertEqual(set(openapi["paths"]["/api/v1/health"]["get"]["responses"]), {"200"})
        self.assertEqual(set(openapi["paths"]["/api/v1/commands"]["post"]["responses"]),
                         {"200", "202", "401", "403", "409", "422", "503", "500"})
        cases = artifacts["examples/reconciliation.json"]["scenarios"]
        by_name = {case["name"]: case for case in cases}
        self.assertEqual(by_name["B-refused-after-A"]["adapterResult"]["status"], "rejected")
        self.assertEqual(by_name["A-evicted-by-B"]["adapterResult"]["status"], "unknown")
        self.assertEqual(by_name["device-done-without-passage"]["applicationStatus"], "unknown")
        self.assertEqual(by_name["same-ID-different-block"]["adapterResult"]["status"], "unknown")
        self.assertEqual(by_name["original-open-after-conflicting-reset"]["adapterResult"]["status"], "unknown")
        manifest = artifacts["modbus-parking.v2.json"]
        self.assertEqual(manifest["observation"]["count"], len(manifest["observation"]["fields"]))
        partial = artifacts["examples/partial-validity-fc04.json"]
        words = partial["registers"]
        self.assertEqual(len(words), OBSERVATION_COUNT)
        self.assertEqual(partial["count"], OBSERVATION_COUNT)
        decoded = SlotSample.from_internal(header_valid_mask=words[10], payload_valid_mask=words[14],
                                          occupancy_mask=words[12], free_count=words[13])
        self.assertEqual(decoded.slot_states(), (True, None))
        self.assertEqual(words[20:], [0] * 17)  # no command record on slot node
        for lane in artifacts["examples/lease-routing.json"]["lanes"]:
            transactions = lane["transactions"]
            expected_unit = 3 if lane["nodeId"] == "S3" else 4
            self.assertTrue(all(transaction["unitId"] == expected_unit for transaction in transactions))
            self.assertEqual(transactions[2], {"unitId": expected_unit, "function": 6, "offset": 4,
                                               "value": 1, "purpose": "renew target station lease"})
            self.assertEqual(transactions[3]["registers"][4], 1 if expected_unit == 3 else 2)
        self.assertEqual(artifacts["examples/frozen-sample.json"]["effectiveAgeMs"], 2110)
        for case in cases:
            PassageEvidence.model_validate(case["passage"])
        for case in artifacts["examples/capacity.json"]["lastSpace"]:
            Capacity.model_validate(case)
        # A client generator must never receive dangling component references.
        schemas = openapi["components"]["schemas"]

        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    self.assertIn(value["$ref"].split("/")[-1], schemas)
                for child in value.values():
                    check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)

        check_refs(openapi)
        for name, value in artifacts.items():
            generated = Path(__file__).resolve().parents[1] / "contracts" / name
            self.assertEqual(json.loads(generated.read_text(encoding="utf-8")), value)


if __name__ == "__main__":
    unittest.main()
