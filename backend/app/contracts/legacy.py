"""Diagnostic v1 observation, deliberately separate from v2 parking telemetry."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .api import Timestamp, WireModel


class LegacyTelemetry(WireModel):
    profile: Literal["hybrid-v1-readonly"] = "hybrid-v1-readonly"
    selected: bool
    enabled: bool
    read_only: Literal[True] = True
    unit_id: Annotated[int, Field(ge=1, le=247)]
    protocol_version: Literal[256] | None
    connected: bool
    quality: Literal["reported", "unknown", "stale", "unavailable", "incompatible", "disabled"]
    observed_at: Timestamp | None
    age_ms: Annotated[int, Field(ge=0)] | None
    stale_after_ms: Annotated[int, Field(ge=500, le=10000)]
    device_health: Literal[1, 2] | None
    physical_slot_id: Literal[1] = 1
    device_known: bool | None
    occupied: bool | None
    raw_registers: Annotated[list[Annotated[int, Field(ge=0, le=65535)]], Field(min_length=6, max_length=6)] | None
    freshness_guarantee: Literal["communication-only"] = "communication-only"
    message: str

    @model_validator(mode="after")
    def no_invented_sensor_proof(self):
        if self.quality == "reported":
            if (not self.selected or not self.enabled or not self.connected or self.protocol_version != 256
                or self.device_known is not True or self.occupied is None or self.raw_registers is None
                or self.observed_at is None or self.age_ms is None or self.age_ms >= self.stale_after_ms):
                raise ValueError("reported observation requires a recent compatible response")
            if (self.raw_registers[:3] != [self.unit_id, 256, self.device_health]
                or not self.raw_registers[5] & 1 or self.occupied != bool(self.raw_registers[3])):
                raise ValueError("P01 must match the reported physical bit and known mask")
        elif self.occupied is not None:
            raise ValueError("missing/expired diagnostic observation cannot claim occupancy")
        return self
