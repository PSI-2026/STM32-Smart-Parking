"""QueryService: application operations; repository calls use the caller transaction."""


import base64
import json
from uuid import uuid4
from pydantic import TypeAdapter
from ..contracts.api import EventPage, Identifier, ParkingEvent, ParkingSlot, ParkingSnapshot, SessionPage
from ..telemetry import unknown_telemetry

from .common import BusinessFault, canonical


class QueryService:
    def __init__(self, parking):
        self.parking = parking

    def _event(self, connection, code, message, *, command_id=None, session_id=None, node_id=None, level="info"):
        self.parking.repository.insert_event(connection, (
            uuid4().hex, self.parking.clock_ms(), level, code, message, node_id, session_id, command_id))

    def snapshot(self, *, transport="TCP") -> ParkingSnapshot:
        """One SQLite read snapshot and one valuation time for all business data."""
        with self.parking.db.transaction(write=False) as connection:
            telemetry = self.parking._current_telemetry(connection) or unknown_telemetry()
            selected_transport = self.parking.repository.simulation_transport(connection).fetchone()
            if self.parking.mode == "simulation" and selected_transport:
                transport = selected_transport[0]
            now = self.parking.clock_ms()
            sessions = [self.parking._session(connection, row, at=now) for row in self.parking.repository.open_sessions(connection)]
            assigned = {session.slot_id: session.id for session in sessions if session.slot_id is not None}
            slots = [ParkingSlot.model_validate(slot.model_dump(by_alias=True) | {"sessionId": assigned.get(slot.id)})
                     for slot in telemetry.slots]
            events = [ParkingEvent.from_internal(**dict(row)) for row in self.parking.repository.recent_events(connection)]
            commands = [self.parking._result(row) for row in self.parking.repository.latest_commands(connection)]
            return ParkingSnapshot.from_internal(
                mode=self.parking.mode, transport=transport, updated_at=now, hourly_rate_bani=self.parking.hourly_rate_bani,
                stale_after_ms=telemetry.stale_after_ms, stations=telemetry.stations, slots=slots,
                barriers=telemetry.barriers, capacity=self.parking._capacity(connection, telemetry),
                sessions=sessions, events=events, commands=commands,
            )

    def _pagination(self, limit, cursor):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise BusinessFault("VALIDATION_ERROR", "Limită de paginare invalidă.")
        if cursor is None:
            return None
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 512:
                raise ValueError()
            value = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
            if not isinstance(value, list) or len(value) != 2 or type(value[0]) is not int or not 0 <= value[0] <= 9007199254740991:
                raise ValueError()
            TypeAdapter(Identifier).validate_python(value[1], strict=True)
            return value
        except (ValueError, TypeError):
            raise BusinessFault("VALIDATION_ERROR", "Cursor invalid.") from None

    def _page(self, connection, table, time_column, limit, cursor):
        anchor = self.parking._pagination(limit, cursor)
        rows = self.parking.repository.page_rows(connection, table, time_column, anchor, limit)
        next_cursor = (base64.urlsafe_b64encode(canonical([rows[limit - 1][time_column], rows[limit - 1]["id"]]).encode()).decode().rstrip("=")
                       if len(rows) > limit else None)
        return rows[:limit], next_cursor

    def list_sessions(self, *, limit=50, cursor=None):
        with self.parking.db.transaction(write=False) as connection:
            rows, next_cursor = self.parking._page(connection, "sessions", "created_at", limit, cursor)
            return SessionPage.from_internal(items=[self.parking._session(connection, row) for row in rows], next_cursor=next_cursor)

    def list_events(self, *, limit=50, cursor=None):
        with self.parking.db.transaction(write=False) as connection:
            rows, next_cursor = self.parking._page(connection, "events", "at", limit, cursor)
            items = [ParkingEvent.from_internal(**dict(row)) for row in rows]
            return EventPage.from_internal(items=items, next_cursor=next_cursor)
