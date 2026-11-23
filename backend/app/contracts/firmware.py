"""Target parking MODBUS v2.1, requiring coherent observation records."""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from .api import DEVICE_SCHEMA_VERSION, Identifier, TelemetryTopology, Timestamp, WireModel

SCHEMA_VERSION = DEVICE_SCHEMA_VERSION
NODE_IDS = {"G": 247, "S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5}
NODE_ROLES = {"G": 0, "S1": 1, "S2": 1, "S3": 2, "S4": 3, "S5": 4}
IDENTITY_OFFSET = 0
IDENTITY_COUNT = 3
OBSERVATION_OFFSET = 0x0300
OBSERVATION_COUNT = 37
CONTROL_LEASE_OFFSET = 4
BARRIER_COMMAND_OFFSET = 0x0100
BARRIER_COMMAND_COUNT = 9
U32 = Annotated[int, Field(ge=0, le=0xFFFFFFFF)]
DeviceCommandId = Annotated[int, Field(ge=1, le=0xFFFFFFFF)]
CommandBlock = Annotated[list[Annotated[int, Field(ge=0, le=65535)]], Field(min_length=9, max_length=9)]


class DeviceCommand(WireModel):
    node_id: Literal["S3", "S4"]
    command_id: DeviceCommandId
    operation: Literal["open", "reset-fault"]
    ttl_ms: Annotated[int, Field(ge=0, le=10000)]
    authorization: Literal["none", "capacity", "payment"]
    expected_boot_epoch: U32

    @model_validator(mode="after")
    def authorized_operation(self):
        if self.operation == "reset-fault":
            if self.ttl_ms != 0 or self.authorization != "none":
                raise ValueError("fault reset requires ttl=0 and no authorization")
        elif self.ttl_ms < 100 or self.authorization != ("capacity" if self.node_id == "S3" else "payment"):
            raise ValueError("open requires TTL 100..10000 and lane-specific authorization")
        return self

    def registers(self) -> list[int]:
        return [
            self.command_id >> 16, self.command_id & 0xFFFF,
            1 if self.operation == "open" else 2, self.ttl_ms,
            {"none": 0, "capacity": 1, "payment": 2}[self.authorization],
            self.expected_boot_epoch >> 16, self.expected_boot_epoch & 0xFFFF, 0, 0,
        ]


class DeviceCommandResult(WireModel):
    """Requested identity; known results require a matching atomic record."""

    node_id: Literal["S3", "S4"]
    command_id: DeviceCommandId
    boot_epoch: U32
    status: Literal["accepted", "executing", "done", "rejected", "unknown", "expired", "failed"]
    result_code: Annotated[int, Field(ge=0, le=7)] | None
    command_block: CommandBlock | None
    evidence: Literal["coherent-record", "simulation", "unproven"]
    reason: Literal["matched", "write-timeout", "record-mismatch", "boot-changed", "record-unavailable", "incoherent"]

    @model_validator(mode="after")
    def consistent_result(self):
        allowed = {"accepted": {0}, "executing": {0}, "done": {1},
                   "rejected": {2, 3, 4, 5}, "expired": {6}, "failed": {7}}
        if self.status == "unknown":
            if self.result_code is not None or self.command_block is not None or self.evidence != "unproven" or self.reason == "matched":
                raise ValueError("unknown result requires no code and an explicit lack of proof")
        elif self.result_code not in allowed[self.status] or self.evidence == "unproven" or self.reason != "matched":
            raise ValueError("known status requires matching evidence and compatible result code")
        else:
            if self.command_block is None:
                raise ValueError("known result requires the exact processed FC16 block")
            block = self.command_block
            if (block[0] << 16 | block[1]) != self.command_id or (block[5] << 16 | block[6]) != self.boot_epoch:
                raise ValueError("record identity must match its echoed command block")
            # A rejected request may be precisely the request we must never emit.
            # Preserve its raw nine-u16 echo instead of applying sender policy.
            if self.status != "rejected":
                if block[2] not in (1, 2) or block[4] not in (0, 1, 2) or block[7:] != [0, 0]:
                    raise ValueError("invalid processed command block")
                DeviceCommand.from_internal(
                    node_id=self.node_id, command_id=self.command_id,
                    operation="open" if block[2] == 1 else "reset-fault", ttl_ms=block[3],
                    authorization={0: "none", 1: "capacity", 2: "payment"}[block[4]],
                    expected_boot_epoch=self.boot_epoch,
                )
        return self


class CommandObservation(WireModel):
    """Parsed from ONE atomic FC04 block, never assembled from separate reads."""

    node_id: Literal["S3", "S4"]
    boot_epoch: U32
    record: DeviceCommandResult | None

    @model_validator(mode="after")
    def same_node(self):
        if self.record is not None and self.record.node_id != self.node_id:
            raise ValueError("record node must match atomic observation identity")
        if self.record is not None and (self.record.evidence != "coherent-record" or self.record.status == "unknown"):
            raise ValueError("atomic observation must contain a proven record or no record")
        return self


def result_for(command: DeviceCommand, observation: CommandObservation | None) -> DeviceCommandResult:
    """Conservative lookup of the last processed request, including rejections."""
    reason = "record-unavailable"
    if observation is not None:
        if observation.node_id != command.node_id:
            reason = "record-mismatch"
        elif observation.boot_epoch != command.expected_boot_epoch:
            reason = "boot-changed"
        elif observation.record is not None:
            record = observation.record
            if (record.command_id == command.command_id and record.boot_epoch == command.expected_boot_epoch
                    and record.command_block == command.registers()):
                return record
            reason = "record-mismatch"
    return DeviceCommandResult.from_internal(
        node_id=command.node_id, command_id=command.command_id,
        boot_epoch=command.expected_boot_epoch, status="unknown", result_code=None, command_block=None,
        evidence="unproven", reason=reason,
    )


class PassageEvidence(WireModel):
    """Explicit evidence, never inferred from vehiclePresent transitions."""

    node_id: Literal["S3", "S4"]
    command_id: DeviceCommandId
    boot_epoch: U32
    state: Literal["confirmed", "unavailable", "lost"]
    source: Literal["simulation", "none"]
    evidence_id: Identifier | None
    occurred_at: Timestamp | None
    command_block: CommandBlock | None

    @model_validator(mode="after")
    def proof_required(self):
        if self.state == "confirmed":
            if self.source != "simulation" or self.evidence_id is None or self.occurred_at is None or self.command_block is None:
                raise ValueError("confirmed passage requires explicit simulation evidence")
            expected = DeviceCommand.from_internal(
                node_id=self.node_id, command_id=self.command_id, operation="open",
                ttl_ms=self.command_block[3], authorization="capacity" if self.node_id == "S3" else "payment",
                expected_boot_epoch=self.boot_epoch,
            )
            if self.command_block != expected.registers():
                raise ValueError("passage must identify the exact valid open block")
        elif self.source != "none" or self.evidence_id is not None or self.occurred_at is not None or self.command_block is not None:
            raise ValueError("missing/lost passage cannot claim an event")
        return self


def passage_matches(
    command: DeviceCommand, evidence: PassageEvidence, *,
    mode: Literal["simulation", "hardware"], business_action: Literal["enter", "exit"],
) -> bool:
    return (
        mode == "simulation" and evidence.source == "simulation" and command.operation == "open"
        and command.node_id == {"enter": "S3", "exit": "S4"}.get(business_action)
        and evidence.state == "confirmed" and evidence.node_id == command.node_id
        and evidence.command_id == command.command_id
        and evidence.boot_epoch == command.expected_boot_epoch
        and evidence.command_block == command.registers()
    )


class FreshnessProof(WireModel):
    sample_age_ms: U32
    round_trip_ms: Annotated[int, Field(ge=0)]
    elapsed_since_response_ms: Annotated[int, Field(ge=0)]
    elapsed_since_sequence_first_seen_ms: Annotated[int, Field(ge=0)]
    first_estimated_age_ms: Annotated[int, Field(ge=0)]

    def effective_age_ms(self) -> int:
        return max(
            self.sample_age_ms + self.round_trip_ms + self.elapsed_since_response_ms,
            self.first_estimated_age_ms + self.elapsed_since_sequence_first_seen_ms,
        )


class SlotSample(WireModel):
    """Payload validity after the adapter checks frame/path identity and age."""

    header_valid_mask: Annotated[int, Field(ge=0, le=3)]
    payload_valid_mask: Annotated[int, Field(ge=0, le=3)]
    occupancy_mask: Annotated[int, Field(ge=0, le=3)]
    free_count: Annotated[int, Field(ge=0, le=65535)]

    @model_validator(mode="after")
    def consistent_masks(self):
        if self.header_valid_mask != self.payload_valid_mask:
            raise ValueError("header and payload validity masks must match")
        expected = 2 - self.occupancy_mask.bit_count() if self.header_valid_mask == 3 else 65535
        if self.free_count != expected:
            raise ValueError("partial sensor validity requires unknown freeCount=65535")
        return self

    def slot_states(self) -> tuple[bool | None, bool | None]:
        return tuple(bool(self.occupancy_mask & (1 << i)) if self.header_valid_mask & (1 << i) else None
                     for i in range(2))


class DeviceTelemetry(TelemetryTopology):
    """Hardware fields only: no session IDs, tariffs or payments."""


class DeviceAdapter(Protocol):
    """One active controller. Reads uphold freshness and communication path invariants."""

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def read_telemetry(self) -> DeviceTelemetry: ...
    async def submit(self, command: DeviceCommand) -> DeviceCommandResult: ...
    async def read_command(self, command: DeviceCommand) -> DeviceCommandResult: ...
    async def read_passage(self, node_id: Literal["S3", "S4"], command_id: int, boot_epoch: int) -> PassageEvidence: ...


def register_manifest() -> dict:
    """Explicit extension of local v2 design, not evidence of MCU support."""
    return {
        "profile": "distributed-v2.1", "status": "target-not-hardware-validated",
        "schemaVersion": SCHEMA_VERSION, "addressing": "zero-based",
        "u32WordOrder": "high-first", "nodeIds": NODE_IDS, "nodeRoles": NODE_ROLES,
        "identity": {"object": "IR", "function": 4, "offset": IDENTITY_OFFSET, "count": IDENTITY_COUNT},
        "observation": {
            "object": "IR", "function": 4, "offset": OBSERVATION_OFFSET, "count": OBSERVATION_COUNT,
            "atomic": True, "access": "direct-unit-id-only", "gatewayCacheSupported": False,
            "fields": ["schemaVersion", "nodeRole", "nodeId", "statusFlags", "bootEpochHigh", "bootEpochLow",
                       "sampleSequenceHigh", "sampleSequenceLow", "sampleAgeMsHigh", "sampleAgeMsLow",
                       "validMask", "payloadCount", "payload0", "payload1", "payload2", "payload3",
                       "payload4", "payload5", "payload6", "payload7", "recordBootEpochHigh",
                       "recordBootEpochLow", "recordCommandIdHigh", "recordCommandIdLow",
                       "recordStatus", "recordResultCode", "recordPresent", "reservedZero",
                       *[f"recordCommandWord{i}" for i in range(9)]],
            "statusFlags": {"0": "ready", "1": "simulation", "2": "local-data-valid", "3": "interlock"},
            "requiredValidFlagsMask": 5,
            "freshness": {"defaultStaleAfterMs": 2000, "sampleAge": "MCU monotonic elapsed since actual acquisition, not since register read",
                          "effectiveAge": "max(sampleAgeMs + roundTripMs + elapsedSinceResponseMs, firstEstimatedAgeMs + elapsedSinceSequenceFirstSeenMs)",
                          "firstEstimate": "Store sampleAgeMs + firstRoundTripMs at first response for (nodeId,bootEpoch,sampleSequence); never reset for repeated reads",
                          "ambiguousWrap": "Preserve the accepted anchor; store a separate runtime-bound candidate. Never re-anchor the same boot/sequence, even after expiry or interruption. Once expired, require a distinct baseline sequence and a further advance in the same boot within the freshness limit before replacing the accepted anchor.",
                          "bootIdentity": "Persist the maximum boot immediately after decoding a coherent identity frame, before freshness validation or telemetry publication. Unknown sensor quality must not erase or delay this bound. Seed adapters and guard transactional command results and telemetry with the durable bound.",
                          "validWhen": "effectiveAge < staleAfterMs; identity matches; flags ready and local-data-valid; validMask permits field; gateway path valid"},
            "coherence": "One FC04 returns one immutable latched record including identity, boot, age, payload and command result. Partial or malformed reads are unusable.",
        },
        "payloads": {
            "G": {"count": 1, "fields": ["onlineMask"], "validMask": 1},
            "S1": {"count": 4, "fields": ["occupancyMask", "freeCount", "validMask", "ledOutputMask"], "fullValidMask": 3},
            "S2": {"count": 4, "fields": ["occupancyMask", "freeCount", "validMask", "ledOutputMask"], "fullValidMask": 3},
            "S3": {"count": 4, "fields": ["state", "vehiclePresent", "obstaclePresent", "positionFeedback"], "validMask": 15},
            "S4": {"count": 4, "fields": ["state", "vehiclePresent", "obstaclePresent", "positionFeedback"], "validMask": 15},
            "S5": {"count": 0, "fields": [], "validMask": 0},
        },
        "slotValidity": {
            "ledOutputMask": "Four output bits (0..15): green A, red A, green B, red B; [1,1,3,6] means A occupied, B free",
            "headerBits": {"0": "local slot A sensor valid", "1": "local slot B sensor valid"},
            "payloadMask": "payload2 must equal header validMask exactly; only bits 0 and 1 may be set",
            "mismatch": "Reject the entire node sample, publish both slots unknown",
            "partial": "Use occupancy bits only for valid sensors; other slots unknown",
            "freeCount": "Usable only when both masks equal 3; otherwise payload1 must be 65535, never a capacity value",
            "flags": "local-data-valid means coherent acquisition record, not that every sensor is valid",
        },
        "commandRecord": {
            "observationValidity": "Use the same monotonic boot/sequence/freshness history as polling; require current validated gateway path and target observation. Regressed boot, missing progress after interruption, or stale observation yields unknown. The retained command record itself has no age limit.",
            "scope": "last-processed-request-including-refusals", "historyQueryable": False,
            "match": ["nodeId == requested.nodeId", "observation.bootEpoch == requested.expectedBootEpoch",
                      "recordBootEpoch == requested.expectedBootEpoch", "recordCommandId == requested.commandId",
                      "recordCommandWord0..8 == requested FC16 block (exact nine words)"],
            "rejectedEcho": "Raw nine u16 words with matching record ID and requested boot; do not require sender authorization/TTL/operation policy to decode a rejection",
            "statuses": {"0": "none", "1": "accepted", "2": "executing", "3": "done", "4": "rejected", "5": "expired", "6": "failed"},
            "allowedStatusCodes": {"accepted": [0], "executing": [0], "done": [1], "rejected": [2, 3, 4, 5], "expired": [6], "failed": [7]},
            "results": {"0": "none", "1": "ok", "2": "interlock", "3": "authorization-missing", "4": "id-content-conflict", "5": "boot-mismatch", "6": "expired", "7": "actuator-fault"},
            "otherwise": "unknown; never attribute another request's status; never auto-replay an uncertain command",
        },
        "barrierStates": {"0": "CLOSED", "1": "OPENING", "2": "OPEN", "3": "CLOSING", "4": "FAULT"},
        "positionFeedback": {"0": "estimated", "1": "closed-measured", "2": "open-measured", "3": "intermediate-measured"},
        "passageEvidence": "unavailable in hardware v2.1; simulation requires an explicit correlated passage event",
        "leaseRenew": {"object": "HR", "function": 6, "offset": CONTROL_LEASE_OFFSET, "value": 1,
                       "issuer": "backend active adapter", "unitId": "same target as FC16: S3=3 or S4=4",
                       "route": "gateway routes FC06 unchanged; does not renew station leases independently in v2.1",
                       "checkedLease": "target station external-control lease, not gateway lease",
                       "durationMs": 2000, "expiry": "new open requires unexpired target lease at acceptance; does not force closing"},
        "barrierCommand": {"object": "HR", "function": 16, "offset": BARRIER_COMMAND_OFFSET,
                           "count": BARRIER_COMMAND_COUNT,
                           "fields": ["commandIdHigh", "commandIdLow", "operation", "ttlMs", "authorization", "expectedBootEpochHigh", "expectedBootEpochLow", "reservedZero", "reservedZero"]},
    }
