"""Explicit environment configuration; existing .env files are never loaded."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARKING_", env_file=None, extra="ignore", hide_input_in_errors=True)

    database_path: Path = Path(__file__).resolve().parents[1] / "data" / "parking.sqlite3"
    mode: Literal["simulation", "hardware"] = "simulation"
    transport: Literal["TCP", "USB"] = "TCP"
    hourly_rate_bani: int = Field(default=500, ge=0, le=1_000_000_000)
    worker_enabled: bool = True
    worker_interval_seconds: float = Field(default=0.1, ge=0.05, le=5)
    simulator_enabled: bool = True
    simulator_step_delay_ms: int = Field(default=200, ge=50, le=10000)
    simulator_auto_passage: bool = True
    hardware_enabled: bool = False
    modbus_host: str = "127.0.0.1"
    modbus_port: int = Field(default=502, ge=1, le=65535)
    modbus_serial_port: str = "COM3"
    modbus_baudrate: int = Field(default=19200, ge=1200, le=115200)
    modbus_parity: Literal["N", "E", "O"] = "N"
    modbus_timeout_seconds: float = Field(default=0.3, ge=0.05, le=2)
    viewer_token: SecretStr | None = None
    operator_token: SecretStr | None = None
    admin_token: SecretStr | None = None
    allow_anonymous_simulation: bool = False

    @model_validator(mode="after")
    def validate_access(self):
        tokens = [value.get_secret_value() for value in
                  (self.viewer_token, self.operator_token, self.admin_token) if value is not None]
        if any(len(token) < 32 or any(c.isspace() for c in token) for token in tokens):
            raise ValueError("Access tokens require at least 32 non-whitespace characters")
        if len(tokens) != len(set(tokens)):
            raise ValueError("Access tokens must be distinct across roles")
        if self.mode == "hardware" and self.allow_anonymous_simulation:
            raise ValueError("Anonymous access is never allowed in hardware mode")
        return self
