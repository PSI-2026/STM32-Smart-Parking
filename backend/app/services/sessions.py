"""SessionService: application operations; repository calls use the caller transaction."""


from uuid import uuid4
from ..contracts.api import ParkingSession

from .common import BusinessFault, tariff_bani


class SessionService:
    def __init__(self, parking):
        self.parking = parking

    def _session_row(self, connection, session_id):
        row = self.parking.repository.session(connection, (session_id,)).fetchone()
        if row is None:
            raise BusinessFault("NOT_FOUND", "Sesiunea nu există.")
        return row

    def _session(self, connection, row, *, at=None):
        paid = self.parking.repository.paid_total(connection, (row["id"],)).fetchone()[0]
        due = (max(0, tariff_bani(row["entered_at"], self.parking.clock_ms() if at is None else at, row["hourly_rate_bani"]) - paid)
               if row["entered_at"] is not None and row["paid_at"] is None else 0)
        return ParkingSession.from_internal(id=row["id"], plate=row["plate"], slot_id=row["slot_id"],
            entered_at=row["entered_at"], exited_at=row["exited_at"], status=row["status"],
            hourly_rate_bani=row["hourly_rate_bani"], amount_due_bani=due, paid_bani=paid)

    def get_session(self, session_id):
        with self.parking.db.transaction(write=False) as connection:
            return self.parking._session(connection, self.parking._session_row(connection, session_id))

    def open_sessions(self):
        with self.parking.db.transaction(write=False) as connection:
            return [self.parking._session(connection, row) for row in self.parking.repository.open_sessions(connection)]

    def _pay(self, connection, command, session_id):
        session = self.parking._session_row(connection, session_id)
        self.parking._ensure_session_reconciled(connection, session_id)
        if session["status"] not in ("active", "paid"):
            raise BusinessFault("SESSION_CONFLICT", "Sesiunea nu permite plata.")
        if session["paid_at"] is None:
            now = self.parking.clock_ms()
            amount = tariff_bani(session["entered_at"], now, session["hourly_rate_bani"])
            self.parking.repository.insert_payment(connection, (uuid4().hex, session_id, command["id"], amount, now))
            self.parking.repository.mark_session_paid(connection, (now, session_id))
            self.parking._event(connection, "PAYMENT_RECORDED", "Plata simulată a fost salvată.", command_id=command["id"], session_id=session_id)
        self.parking.repository.bind_command_session(connection, (session_id, command["id"]))
        self.parking._transition(connection, self.parking._command(connection, command["id"]), "done", "Sesiunea este plătită.")

    def _ensure_session_reconciled(self, connection, session_id):
        if self.parking.repository.session_contradiction(connection, (session_id,)).fetchone():
            raise BusinessFault("SESSION_CONFLICT", "Sesiunea are o contradicție MCU nereconciliată.")
