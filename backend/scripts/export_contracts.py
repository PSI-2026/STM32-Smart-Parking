"""Export proposed OpenAPI, firmware schema and validated examples.

Run from repository root: backend/.venv/Scripts/python backend/scripts/export_contracts.py
Use --check to detect artifacts that differ from their Python source.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import TypeAdapter

from app.contracts.api import (
    ApiError, CommandRequest, CommandResult, EventPage, Health,
    ParkingSnapshot, SessionPage,
)
from app.contracts.firmware import (
    CommandObservation, DeviceCommand, DeviceCommandResult, DeviceTelemetry,
    FreshnessProof, PassageEvidence, SlotSample, register_manifest, result_for,
)


def artifacts() -> dict[str, dict]:
    schema = TypeAdapter(Union[
        Health, ApiError, CommandRequest, CommandResult, ParkingSnapshot,
        SessionPage, EventPage, DeviceCommand, DeviceCommandResult, DeviceTelemetry,
        PassageEvidence, CommandObservation, FreshnessProof, SlotSample,
    ]).json_schema(ref_template="#/components/schemas/{model}", mode="serialization")
    components = schema["$defs"]

    def response(model, description):
        return {"description": description, "content": {"application/json": {
            "schema": {"$ref": f"#/components/schemas/{model}"}}}}

    def operation(operation_id, model, *, status="200", implemented=True, parameters=None, errors=()):
        result = {
            "operationId": operation_id, "x-implemented": implemented,
            "responses": {status: response(model, "Success"), **{
                str(code): response("ApiError", description)
                for code, description in errors}},
        }
        if parameters:
            result["parameters"] = parameters
        return result

    command_id = [{"name": "commandId", "in": "path", "required": True,
                   "schema": components["CommandRequest"]["properties"]["commandId"]}]
    session_id = [{"name": "sessionId", "in": "path", "required": True,
                   "schema": components["ParkingSession"]["properties"]["id"]}]
    pagination = [
        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
        {"name": "cursor", "in": "query", "schema": {"type": "string", "minLength": 1, "maxLength": 512}},
    ]
    internal = (500, "Internal error")
    unavailable = (503, "Service or persistence unavailable")
    invalid = (422, "Invalid request")
    missing = (404, "Not found")
    submit = operation("submitCommand", "CommandResult", status="202", errors=(
        (409, "ID already identifies a different normalized action"),
        (422, "Invalid request; command ID not reserved"), unavailable, internal))
    submit["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/CommandRequest"}}}}
    submit["responses"]["200"] = response("CommandResult", "Previously stored command (idempotent replay)")
    spec = {
        "openapi": "3.1.0", "info": {"title": "Smart Parking target API", "version": "1.0.0",
            "description": "HTTP API implemented in step 4. Device I/O and the simulator are integrated in subsequent steps."},
        "servers": [{"url": "http://127.0.0.1:8000"}],
        "paths": {
            "/api/v1/health": {"get": operation("healthCheck", "Health", implemented=True)},
            "/api/v1/snapshot": {"get": operation("getSnapshot", "ParkingSnapshot", errors=(internal, unavailable))},
            "/api/v1/commands": {"post": submit},
            "/api/v1/commands/{commandId}": {"get": operation("getCommand", "CommandResult", parameters=command_id, errors=(missing, invalid, internal, unavailable))},
            "/api/v1/sessions": {"get": operation("listSessions", "SessionPage", parameters=pagination, errors=(invalid, internal, unavailable))},
            "/api/v1/sessions/{sessionId}": {"get": operation("getSession", "ParkingSession", parameters=session_id, errors=(missing, invalid, internal, unavailable))},
            "/api/v1/events": {"get": operation("listEvents", "EventPage", parameters=pagination, errors=(invalid, internal, unavailable))},
        },
        "components": {"schemas": components},
    }
    enter = CommandRequest.model_validate({"commandId": "demo-entry-001", "action": {"type": "enter", "plate": "B 101 DEM"}})
    unknown = ParkingSnapshot.model_validate({
        "mode": "hardware", "transport": "TCP", "updatedAt": 1795420800000, "hourlyRateBani": 500,
        "capacity": {"physicalOccupied": None, "outstandingClaims": 0, "available": None, "reconciliationRequired": False},
        "stations": [{"id": node, "role": role, "online": False, "quality": "unknown",
                      "updatedAt": None, "ageMs": None, "schemaVersion": None, "bootEpoch": None}
                     for node, role in zip(["G", "S1", "S2", "S3", "S4", "S5"],
                                           ["gateway", "slots", "slots", "entry", "exit", "environment"])],
        "slots": [{"id": i, "nodeId": "S1" if i <= 2 else "S2", "occupied": None,
                   "sessionId": None, "quality": "unknown", "updatedAt": None, "ageMs": None}
                  for i in range(1, 5)],
        "barriers": [{"id": lane, "nodeId": node, "state": "UNKNOWN", "obstacle": None,
                      "vehiclePresent": None, "feedback": "unknown", "quality": "unknown",
                      "updatedAt": None, "ageMs": None} for lane, node in [("entry", "S3"), ("exit", "S4")]],
        "sessions": [], "commands": [], "events": [],
    })
    device = DeviceCommand.from_internal(node_id="S4", command_id=1, operation="open", ttl_ms=2000,
                           authorization="payment", expected_boot_epoch=7)
    accepted = CommandResult.from_internal(command_id="demo-entry-001", status="accepted",
                             message="Comanda a fost înregistrată.",
                             created_at=1795420800000, updated_at=1795420800000)
    error = ApiError.model_validate({"error": {"code": "DATA_UNAVAILABLE",
                                    "message": "Disponibilitatea parcării nu este cunoscută.", "retryable": True}})
    def observed(command, status, code):
        record = DeviceCommandResult.from_internal(
            node_id=command.node_id, command_id=command.command_id, boot_epoch=command.expected_boot_epoch,
            status=status, result_code=code, command_block=command.registers(), evidence="coherent-record", reason="matched")
        return CommandObservation.from_internal(node_id=command.node_id, boot_epoch=7, record=record)

    command_b = DeviceCommand.from_internal(node_id="S4", command_id=2, operation="open", ttl_ms=2000,
                                            authorization="payment", expected_boot_epoch=7)
    last_b = observed(command_b, "rejected", 2)
    boot_changed = CommandObservation.from_internal(node_id="S4", boot_epoch=8, record=None)
    passage_missing = PassageEvidence.from_internal(
        node_id="S4", command_id=1, boot_epoch=7, state="unavailable", source="none", evidence_id=None, occurred_at=None, command_block=None)
    same_id_reset = DeviceCommand.from_internal(node_id="S4", command_id=1, operation="reset-fault", ttl_ms=0,
                                                 authorization="none", expected_boot_epoch=7)
    scenarios = []
    for name, requested, observation, business, note in (
        ("timeout-then-matching-record", device, observed(device, "accepted", 0), "executing", "No resend; acceptance is not passage."),
        ("B-refused-after-A", command_b, last_b, "rejected", "B is explicitly identified even though never accepted."),
        ("A-evicted-by-B", device, last_b, "unknown", "B refusal must not be attributed to A."),
        ("MCU-restart", device, boot_changed, "unknown", "Keep old application command and claims; never allocate new device ID to retry it."),
        ("record-unavailable-after-timeout", device, None, "unknown", "No blind replay."),
        ("device-done-without-passage", device, observed(device, "done", 1), "unknown", "Session remains pending_exit; capacity is not released."),
        ("same-ID-different-block", same_id_reset, observed(device, "done", 1), "unknown", "An open result cannot prove a reset with the same ID."),
        ("original-open-after-conflicting-reset", device, observed(same_id_reset, "rejected", 4), "unknown", "Conflict rejection describes the reset block, not the original open."),
    ):
        scenarios.append({"name": name, "request": requested.model_dump(by_alias=True),
                          "observation": observation.model_dump(by_alias=True) if observation else None,
                          "adapterResult": result_for(requested, observation).model_dump(by_alias=True),
                          "passage": passage_missing.model_dump(by_alias=True) | {"commandId": requested.command_id},
                          "applicationStatus": business, "rule": note})
    simulated_passage = PassageEvidence.from_internal(
        node_id="S4", command_id=1, boot_epoch=7, state="confirmed", source="simulation",
        evidence_id="sim-passage-1", occurred_at=1795420800500, command_block=device.registers())
    scenarios.append({
        "name": "explicit-simulated-exit", "request": device.model_dump(by_alias=True),
        "passage": simulated_passage.model_dump(by_alias=True), "applicationStatus": "done",
        "rule": "After checking identity and persisting the unique passage event, complete the session. Slot occupancy still comes from its sensor.",
    })
    old_sample = FreshnessProof.from_internal(sample_age_ms=1900, round_trip_ms=50,
                                             elapsed_since_response_ms=100, elapsed_since_sequence_first_seen_ms=150,
                                             first_estimated_age_ms=1900)
    frozen_sample = FreshnessProof.from_internal(sample_age_ms=1500, round_trip_ms=10,
                        elapsed_since_response_ms=0, elapsed_since_sequence_first_seen_ms=600,
                        first_estimated_age_ms=1510)
    partial = SlotSample.from_internal(header_valid_mask=1, payload_valid_mask=1, occupancy_mask=1, free_count=65535)
    # All words of one FC04 response: no command record at this sensor node.
    partial_frame = [513, 1, 1, 5, 0, 7, 0, 42, 0, 20, 1, 4,
                     1, 65535, 1, 2, 0, 0, 0, 0, *([0] * 17)]
    return {
        "openapi.v1.json": spec,
        "modbus-parking.v2.json": register_manifest(),
        "examples/enter.json": enter.model_dump(by_alias=True),
        "examples/command-accepted.json": accepted.model_dump(by_alias=True),
        "examples/error-unavailable.json": error.model_dump(by_alias=True),
        "examples/snapshot-unknown.json": unknown.model_dump(by_alias=True),
        "examples/device-open-exit.json": {"command": device.model_dump(by_alias=True), "registers": device.registers()},
        "examples/reconciliation.json": {"scenarios": scenarios},
        "examples/partial-validity-fc04.json": {
            "unitId": 1, "function": 4, "offset": 768, "count": len(partial_frame),
            "registers": partial_frame, "slotSample": partial.model_dump(by_alias=True),
            "occupied": list(partial.slot_states()), "freeCountUsable": False,
            "rule": "A occupied and valid; B unknown. Header=payload mask=1; freeCount=65535. A mask mismatch invalidates both slots."},
        "examples/lease-routing.json": {"lanes": [
            {"nodeId": node, "transactions": [
                {"unitId": unit, "function": 4, "offset": 0, "count": 3, "purpose": "verify v2.1 identity"},
                {"unitId": unit, "function": 4, "offset": 768, "count": 37, "purpose": "read coherent boot and telemetry"},
                {"unitId": unit, "function": 6, "offset": 4, "value": 1, "purpose": "renew target station lease"},
                {"unitId": unit, "function": 16, "offset": 256,
                 "registers": DeviceCommand.from_internal(node_id=node, command_id=1, operation="open", ttl_ms=2000,
                        authorization=auth, expected_boot_epoch=7).registers()},
            ]} for node, unit, auth in [("S3", 3, "capacity"), ("S4", 4, "payment")]],
            "rule": "Backend emits both writes; G routes to same Unit ID. Only that station's lease authorizes FC16."},
        "examples/frozen-sample.json": {
            "key": {"nodeId": "S1", "bootEpoch": 7, "sampleSequence": 42},
            "firstRead": {"sampleAgeMs": 1500, "roundTripMs": 10, "firstEstimatedAgeMs": 1510},
            "laterRead": frozen_sample.model_dump(by_alias=True), "effectiveAgeMs": frozen_sample.effective_age_ms(),
            "staleAfterMs": 2000, "quality": "stale", "occupied": None},
        "examples/capacity.json": {
            "lastSpace": [
                {"physicalOccupied": 3, "outstandingClaims": 0, "available": 1, "reconciliationRequired": False},
                {"physicalOccupied": 3, "outstandingClaims": 1, "available": 0, "reconciliationRequired": False},
                {"physicalOccupied": 3, "outstandingClaims": 1, "available": 0, "reconciliationRequired": False},
                {"physicalOccupied": 4, "outstandingClaims": 0, "available": 0, "reconciliationRequired": False},
            ],
            "ambiguousOccupancy": {"physicalOccupied": 4, "outstandingClaims": 1, "available": None, "reconciliationRequired": True},
            "rule": "Admission and claim creation are atomic. Passage alone never consumes a claim; transfer to physical occupancy requires correlated evidence.",
        },
        "examples/expired-sample.json": {
            "sampleSequence": 42, "observation": old_sample.model_dump(by_alias=True),
            "effectiveAgeMs": old_sample.effective_age_ms(), "staleAfterMs": 2000,
            "adapterQuality": "stale", "occupied": None, "barrierState": "UNKNOWN",
            "rule": "Successful FC04 is not a new acquisition. Both API and adapter reject quality=valid at age >= 2000 ms."},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "contracts"
    for name, value in artifacts().items():
        target = destination / name
        content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Outdated contract: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    print("Contracts are current." if args.check else "Contracts exported.")
