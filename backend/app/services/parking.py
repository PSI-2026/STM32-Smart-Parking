"""Public application facade; specialized services share one transaction owner."""


import time
from ..contracts.api import CommandRequest
from ..contracts.firmware import DeviceCommandResult, DeviceTelemetry, PassageEvidence
from ..storage import Database

from .common import Admission, BusinessFault, canonical, tariff_bani

from ..repositories.parking import ParkingRepository

from .commands import CommandService

from .sessions import SessionService

from .access import AccessService

from .telemetry import TelemetryService

from .queries import QueryService


class ParkingService:

    def __init__(self, database: Database, *, mode="simulation", hourly_rate_bani=500,
                 clock_ms=None, monotonic_ms=None):
        if mode not in ("simulation", "hardware"):
            raise ValueError("Invalid parking mode")
        if type(hourly_rate_bani) is not int or not 0 <= hourly_rate_bani <= 1_000_000_000:
            raise ValueError("Invalid hourly rate in bani")
        self.db, self.mode, self.hourly_rate_bani = database, mode, hourly_rate_bani
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.simulation_handler = None
        self.repository = ParkingRepository()
        self.commands = CommandService(self)
        self.sessions = SessionService(self)
        self.access = AccessService(self)
        self.telemetry = TelemetryService(self)
        self.queries = QueryService(self)
        with self.db.transaction() as connection:
            stored = self.repository.mode(connection).fetchone()
            if stored and stored[0] != mode:
                raise ValueError("Database mode cannot be changed; use a separate database")
            self.repository.ensure_mode(connection, (mode,))

    def _command(self, connection, command_id):
        return self.commands._command(connection, command_id)

    def _result(self, row):
        return self.commands._result(row)

    def _transition(self, connection, row, status, message, error=None):
        return self.commands._transition(connection, row, status, message, error)

    def admit(self, request: CommandRequest):
        return self.commands.admit(request)

    def get_command(self, command_id):
        return self.commands.get_command(command_id)

    def get_device_command(self, command_id):
        return self.commands.get_device_command(command_id)

    def recent_commands(self, *, limit=50):
        return self.commands.recent_commands(limit=limit)

    def process(self, command_id):
        return self.commands.process(command_id)

    def pending_commands(self):
        return self.commands.pending_commands()

    def processable_commands(self, *, limit=50, excluded=frozenset(), ordered_ids=None):
        return self.commands.processable_commands(limit=limit, excluded=excluded, ordered_ids=ordered_ids)

    def _session_row(self, connection, session_id):
        return self.sessions._session_row(connection, session_id)

    def _session(self, connection, row, *, at=None):
        return self.sessions._session(connection, row, at=at)

    def get_session(self, session_id):
        return self.sessions.get_session(session_id)

    def open_sessions(self):
        return self.sessions.open_sessions()

    def _pay(self, connection, command, session_id):
        return self.sessions._pay(connection, command, session_id)

    def _ensure_session_reconciled(self, connection, session_id):
        return self.sessions._ensure_session_reconciled(connection, session_id)

    def _prepare_access(self, connection, command, action):
        return self.access._prepare_access(connection, command, action)

    def claim_dispatch(self, command_id):
        return self.access.claim_dispatch(command_id)

    def record_device_result(self, command_id, result: DeviceCommandResult):
        return self.access.record_device_result(command_id, result)

    def _existing_evidence(self, connection, evidence_id, payload):
        return self.access._existing_evidence(connection, evidence_id, payload)

    def consume_passage(self, command_id, evidence: PassageEvidence):
        return self.access.consume_passage(command_id, evidence)

    def recover(self):
        return self.access.recover()

    def record_boot_observation(self, node, boot):
        return self.telemetry.record_boot_observation(node, boot)

    def _current_telemetry(self, connection):
        return self.telemetry._current_telemetry(connection)

    def get_telemetry(self):
        return self.telemetry.get_telemetry()

    def _store_telemetry(self, connection, telemetry, *, observed_at):
        return self.telemetry._store_telemetry(connection, telemetry, observed_at=observed_at)

    def ingest_telemetry(self, telemetry: DeviceTelemetry):
        return self.telemetry.ingest_telemetry(telemetry)

    def _capacity(self, connection, telemetry):
        return self.telemetry._capacity(connection, telemetry)

    def get_capacity(self):
        return self.telemetry.get_capacity()

    def account_occupancy(self, session_id, slot_id, telemetry: DeviceTelemetry, *, evidence_id):
        return self.telemetry.account_occupancy(session_id, slot_id, telemetry, evidence_id=evidence_id)

    def account_departure(self, command_id, slot_id, telemetry):
        return self.telemetry.account_departure(command_id, slot_id, telemetry)

    def _event(self, connection, code, message, *, command_id=None, session_id=None, node_id=None, level='info'):
        return self.queries._event(connection, code, message, command_id=command_id, session_id=session_id, node_id=node_id, level=level)

    def snapshot(self, *, transport='TCP'):
        return self.queries.snapshot(transport=transport)

    def _pagination(self, limit, cursor):
        return self.queries._pagination(limit, cursor)

    def _page(self, connection, table, time_column, limit, cursor):
        return self.queries._page(connection, table, time_column, limit, cursor)

    def list_sessions(self, *, limit=50, cursor=None):
        return self.queries.list_sessions(limit=limit, cursor=cursor)

    def list_events(self, *, limit=50, cursor=None):
        return self.queries.list_events(limit=limit, cursor=cursor)
