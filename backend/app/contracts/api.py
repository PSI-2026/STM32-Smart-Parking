"""HTTP v1 wire models. JSON uses camelCase and UTC Unix milliseconds."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

CONTRACT_VERSION = "1.0.0"
DEVICE_SCHEMA_VERSION = 0x0201
NodeId = Literal["G", "S1", "S2", "S3", "S4", "S5"]
BarrierId = Literal["entry", "exit"]
Transport = Literal["TCP", "USB"]
Quality = Literal["valid", "unknown", "stale", "unavailable"]
CommandStatus = Literal["accepted", "executing", "done", "rejected", "unknown", "expired", "failed"]
Timestamp = Annotated[int, Field(ge=0, le=9007199254740991)]
Money = Annotated[int, Field(ge=0, le=9007199254740991)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
SlotId = Annotated[int, Field(ge=1, le=4)]


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_alias=True, validate_by_name=False,
        extra="forbid", strict=True
    )

    @classmethod
    def from_internal(cls, **values):
        """Explicit Python-only construction; HTTP validation remains alias-only."""
        return cls.model_validate(values, by_alias=False, by_name=True)


class Health(WireModel):
    status: Literal["healthy"] = "healthy"
    service: Literal["smart-parking-backend"] = "smart-parking-backend"
    version: str = "0.1.0"


class Observation(WireModel):
    quality: Quality
    updated_at: Timestamp | None
    age_ms: Annotated[int, Field(ge=0)] | None

    @model_validator(mode="after")
    def valid_sample_has_time(self):
        if self.quality in ("valid", "stale") and (self.updated_at is None or self.age_ms is None):
            raise ValueError("valid/stale observations require sample time and age")
        return self


class SlotTelemetry(Observation):
    id: SlotId
    node_id: Literal["S1", "S2"]
    occupied: bool | None

    @model_validator(mode="after")
    def consistent_slot(self):
        if self.node_id != ("S1" if self.id <= 2 else "S2"):
            raise ValueError("slot does not belong to node")
        if (self.quality == "valid") != (self.occupied is not None):
            raise ValueError("occupied must be null exactly when quality is not valid")
        return self


class Station(Observation):
    id: NodeId
    role: Literal["gateway", "slots", "entry", "exit", "environment"]
    online: bool
    schema_version: Annotated[int, Field(ge=0, le=65535)] | None
    boot_epoch: Annotated[int, Field(ge=0, le=4294967295)] | None
    sample_sequence: Annotated[int, Field(ge=0, le=4294967295)] | None = None

    @model_validator(mode="after")
    def consistent_station(self):
        roles = {"G": "gateway", "S1": "slots", "S2": "slots", "S3": "entry", "S4": "exit", "S5": "environment"}
        if self.role != roles[self.id]:
            raise ValueError("station role does not match node identity")
        if self.quality == "valid" and not self.online:
            raise ValueError("offline station cannot have valid data")
        if self.quality == "valid" and (self.schema_version != DEVICE_SCHEMA_VERSION or self.boot_epoch is None or self.sample_sequence is None):
            raise ValueError("valid station requires compatible schema, boot and sample sequence")
        return self


class ParkingSlot(SlotTelemetry):
    session_id: Identifier | None


class Barrier(Observation):
    id: BarrierId
    node_id: Literal["S3", "S4"]
    state: Literal["CLOSED", "OPENING", "OPEN", "CLOSING", "FAULT", "UNKNOWN"]
    obstacle: bool | None
    vehicle_present: bool | None
    feedback: Literal["estimated", "measured", "unknown"]

    @model_validator(mode="after")
    def consistent_barrier(self):
        if self.node_id != ("S3" if self.id == "entry" else "S4"):
            raise ValueError("barrier does not belong to node")
        if self.quality == "valid":
            if self.state == "UNKNOWN" or self.obstacle is None or self.vehicle_present is None:
                raise ValueError("valid barrier requires known state and inputs")
        elif self.state != "UNKNOWN" or self.obstacle is not None or self.vehicle_present is not None or self.feedback != "unknown":
            raise ValueError("invalid barrier data must be explicitly unknown")
        return self


class ParkingSession(WireModel):
    id: Identifier
    plate: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    slot_id: SlotId | None
    entered_at: Timestamp | None
    exited_at: Timestamp | None
    status: Literal["pending_entry", "active", "paid", "pending_exit", "completed", "cancelled"]
    hourly_rate_bani: Money
    amount_due_bani: Money
    paid_bani: Money

    @model_validator(mode="after")
    def consistent_times(self):
        if self.status in ("active", "paid", "pending_exit", "completed") and self.entered_at is None:
            raise ValueError("confirmed session requires entry time")
        if self.status == "completed" and self.exited_at is None:
            raise ValueError("completed session requires exit time")
        if self.status == "pending_entry" and self.entered_at is not None:
            raise ValueError("pending entry cannot already have a confirmed entry time")
        if self.status != "completed" and self.exited_at is not None:
            raise ValueError("only completed sessions have an exit time")
        if self.status in ("paid", "pending_exit", "completed") and self.amount_due_bani != 0:
            raise ValueError("paid or exiting sessions cannot have an unpaid balance")
        if self.exited_at is not None and (self.entered_at is None or self.exited_at < self.entered_at):
            raise ValueError("exit time must follow entry time")
        return self


class ParkingEvent(WireModel):
    id: Identifier
    at: Timestamp
    level: Literal["info", "success", "warning", "error"]
    code: str
    message: str
    node_id: NodeId | None = None
    session_id: Identifier | None = None
    command_id: Identifier | None = None


class ErrorDetail(WireModel):
    code: Literal[
        "VALIDATION_ERROR", "NOT_FOUND", "IDEMPOTENCY_CONFLICT", "SESSION_CONFLICT",
        "PARKING_FULL", "DATA_UNAVAILABLE", "PAYMENT_REQUIRED", "INTERLOCK_ACTIVE",
        "SIMULATION_ONLY", "DEVICE_INCOMPATIBLE", "DEVICE_TIMEOUT", "COMMAND_FAILED",
        "SERVICE_UNAVAILABLE", "INTERNAL_ERROR",
    ]
    message: str
    retryable: bool = False


class ApiError(WireModel):
    error: ErrorDetail


class EnterAction(WireModel):
    type: Literal["enter"]
    plate: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class PayAction(WireModel):
    type: Literal["pay"]
    session_id: Identifier


class ExitAction(WireModel):
    type: Literal["exit"]
    session_id: Identifier


class SetSlotSensorAction(WireModel):
    type: Literal["set-slot-sensor"]
    slot_id: SlotId
    occupied: bool


class SetAllSlotSensorsAction(WireModel):
    type: Literal["set-all-slot-sensors"]
    occupied: bool


class SetNodeOnlineAction(WireModel):
    type: Literal["set-node-online"]
    node_id: NodeId
    online: bool


class SetObstacleAction(WireModel):
    type: Literal["set-obstacle"]
    barrier_id: BarrierId
    active: bool


class SetBarrierPresenceAction(WireModel):
    type: Literal["set-barrier-presence"]
    barrier_id: BarrierId
    present: bool


class SetTransportAction(WireModel):
    type: Literal["set-transport"]
    transport: Transport


ParkingAction = Annotated[
    EnterAction | PayAction | ExitAction | SetSlotSensorAction | SetAllSlotSensorsAction
    | SetNodeOnlineAction | SetObstacleAction | SetBarrierPresenceAction | SetTransportAction,
    Field(discriminator="type"),
]


class CommandRequest(WireModel):
    command_id: Identifier
    action: ParkingAction


class CommandResult(WireModel):
    command_id: Identifier
    status: CommandStatus
    message: str
    created_at: Timestamp
    updated_at: Timestamp
    session_id: Identifier | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def consistent_result(self):
        if self.updated_at < self.created_at:
            raise ValueError("command update cannot precede creation")
        if self.status == "done" and self.error is not None:
            raise ValueError("successful command cannot contain an error")
        return self


class TelemetryTopology(WireModel):
    stale_after_ms: Annotated[int, Field(ge=500, le=10000)] = 2000
    stations: list[Station]
    slots: list[SlotTelemetry]
    barriers: list[Barrier]

    @model_validator(mode="after")
    def consistent_topology(self):
        for values, expected in (
            (self.stations, {"G", "S1", "S2", "S3", "S4", "S5"}),
            (self.slots, {1, 2, 3, 4}), (self.barriers, {"entry", "exit"}),
        ):
            if len(values) != len(expected) or {item.id for item in values} != expected:
                raise ValueError("telemetry must include each topology element exactly once")
        stations = {station.id: station for station in self.stations}
        gateway = stations["G"]
        for item in [*self.stations, *self.slots, *self.barriers]:
            if item.quality == "valid":
                if item.age_ms is None or item.age_ms >= self.stale_after_ms:
                    raise ValueError("valid sample exceeds freshness deadline")
                if gateway.quality != "valid" or not gateway.online:
                    raise ValueError("valid data requires a valid gateway path")
                if isinstance(item, Station):
                    continue
                station = stations[item.node_id]
                if station.quality != "valid" or not station.online:
                    raise ValueError("valid sensor data requires a valid station path")
                if item.age_ms < station.age_ms or item.age_ms < gateway.age_ms:
                    raise ValueError("sensor data cannot be fresher than its communication path")
        return self


class Capacity(WireModel):
    physical_occupied: Annotated[int, Field(ge=0, le=4)] | None
    outstanding_claims: Annotated[int, Field(ge=0, le=4)]
    available: Annotated[int, Field(ge=0, le=4)] | None
    reconciliation_required: bool

    @model_validator(mode="after")
    def conservative_available(self):
        if self.physical_occupied is None or self.reconciliation_required:
            if self.available is not None:
                raise ValueError("uncertain capacity must be null")
        else:
            remaining = 4 - self.physical_occupied - self.outstanding_claims
            if remaining < 0 or self.available != remaining:
                raise ValueError("capacity must account for both occupancy and outstanding claims")
        return self


class ParkingSnapshot(TelemetryTopology):
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    mode: Literal["simulation", "hardware"]
    transport: Transport
    updated_at: Timestamp
    hourly_rate_bani: Money
    capacity: Capacity
    slots: list[ParkingSlot]
    sessions: list[ParkingSession]
    events: list[ParkingEvent]
    commands: list[CommandResult]

    @model_validator(mode="after")
    def capacity_matches_sensors(self):
        measured = sum(slot.occupied is True for slot in self.slots) if all(slot.quality == "valid" for slot in self.slots) else None
        if self.capacity.physical_occupied != measured:
            raise ValueError("capacity physical occupancy must match valid sensor data")
        return self



class SessionPage(WireModel):
    items: list[ParkingSession]
    next_cursor: str | None


class EventPage(WireModel):
    items: list[ParkingEvent]
    next_cursor: str | None
