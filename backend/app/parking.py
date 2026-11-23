"""Transactional parking application; HTTP and device I/O live outside this module."""

import base64
from dataclasses import dataclass
import json
import time
from uuid import uuid4

from pydantic import TypeAdapter

from .contracts.api import (
    Capacity, CommandRequest, CommandResult, ErrorDetail, EventPage, Identifier,
    ParkingEvent, ParkingSession, ParkingSlot, ParkingSnapshot, SessionPage, SlotId,
)
from .contracts.firmware import DeviceCommand, DeviceCommandResult, DeviceTelemetry, PassageEvidence, passage_matches
from .storage import Database
from .telemetry import age_telemetry, normalize_telemetry, unknown_telemetry


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class BusinessFault(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.detail = ErrorDetail(code=code, message=message, retryable=retryable)
        super().__init__(message)


@dataclass(frozen=True)
class Admission:
    result: CommandResult
    replayed: bool


def tariff_bani(entered_at: int, at: int, hourly_rate_bani: int) -> int:
    if at < entered_at:
        raise BusinessFault("DATA_UNAVAILABLE", "Ceasul gazdei este anterior intrării confirmate.")
    hours = max(1, (at - entered_at + 3_600_000 - 1) // 3_600_000)
    amount = hours * hourly_rate_bani
    if amount > 9007199254740991:
        raise BusinessFault("DATA_UNAVAILABLE", "Tariful calculat depășește domeniul monetar al contractului.")
    return amount


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
        with self.db.transaction() as connection:
            stored = connection.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
            if stored and stored[0] != mode:
                raise ValueError("Database mode cannot be changed; use a separate database")
            connection.execute("INSERT OR IGNORE INTO metadata VALUES ('mode',?)", (mode,))

    def _command(self, connection, command_id):
        row = connection.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
        if row is None:
            raise BusinessFault("NOT_FOUND", "Comanda nu există.")
        return row

    def _result(self, row):
        return CommandResult.from_internal(command_id=row["id"], status=row["status"], message=row["message"],
            created_at=row["created_at"], updated_at=row["updated_at"], session_id=row["session_id"],
            error=ErrorDetail.model_validate_json(row["error_json"]) if row["error_json"] else None)

    def _event(self, connection, code, message, *, command_id=None, session_id=None, node_id=None, level="info"):
        connection.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (
            uuid4().hex, self.clock_ms(), level, code, message, node_id, session_id, command_id))

    def _transition(self, connection, row, status, message, error=None):
        connection.execute("UPDATE commands SET status=?,message=?,updated_at=?,error_json=? WHERE id=?", (
            status, message, max(self.clock_ms(), row["updated_at"]),
            error.model_dump_json(by_alias=True) if error else None, row["id"]))
        self._event(connection, f"COMMAND_{status.upper()}", message, command_id=row["id"],
                    session_id=row["session_id"], level="warning" if error else "info")

    def admit(self, request: CommandRequest) -> Admission:
        request = CommandRequest.model_validate(request.model_dump(by_alias=True))
        action = request.action.model_dump(by_alias=True)
        if action["type"] == "enter":
            action["plate"] = " ".join(action["plate"].split()).upper()
            if not action["plate"] or len(action["plate"]) > 20:
                raise BusinessFault("VALIDATION_ERROR", "Număr de înmatriculare invalid după normalizare.")
        payload = canonical(action)
        with self.db.transaction() as connection:
            row = connection.execute("SELECT * FROM commands WHERE id=?", (request.command_id,)).fetchone()
            if row:
                if row["action_json"] != payload:
                    raise BusinessFault("IDEMPOTENCY_CONFLICT", "ID-ul comenzii identifică altă acțiune.")
                return Admission(self._result(row), True)
            now = self.clock_ms()
            connection.execute("""INSERT INTO commands
                (id,action_json,mode,status,created_at,updated_at,message) VALUES (?,?,?,'accepted',?,?,?)""",
                (request.command_id, payload, self.mode, now, now, "Comanda a fost înregistrată."))
            self._event(connection, "COMMAND_ACCEPTED", "Comanda a fost înregistrată.", command_id=request.command_id)
            return Admission(self._result(self._command(connection, request.command_id)), False)

    def get_command(self, command_id) -> CommandResult:
        with self.db.transaction(write=False) as connection:
            return self._result(self._command(connection, command_id))

    def get_device_command(self, command_id) -> DeviceCommand | None:
        with self.db.transaction(write=False) as connection:
            self._command(connection, command_id)
            row = connection.execute("SELECT block_json FROM device_commands WHERE command_id=?", (command_id,)).fetchone()
            return DeviceCommand.model_validate_json(row[0]) if row else None

    def recent_commands(self, *, limit=50):
        self._pagination(limit, None)
        with self.db.transaction(write=False) as connection:
            return [self._result(row) for row in connection.execute(
                "SELECT * FROM commands ORDER BY created_at DESC,id DESC LIMIT ?", (limit,))]

    def _current_telemetry(self, connection):
        row = connection.execute("SELECT * FROM telemetry WHERE id=1").fetchone()
        if row is None or row["runtime_id"] != self.db.runtime_id:
            return None
        elapsed = self.monotonic_ms() - row["received_mono_ms"]
        if elapsed < 0:
            return None
        return age_telemetry(json.loads(row["payload_json"]), elapsed)

    def get_telemetry(self):
        with self.db.transaction(write=False) as connection:
            return self._current_telemetry(connection)

    def _store_telemetry(self, connection, telemetry, *, observed_at):
        now = self.monotonic_ms()
        if now < observed_at:
            raise BusinessFault("DATA_UNAVAILABLE", "Ceasul monoton a regresat în timpul validării.")
        telemetry = age_telemetry(telemetry.model_dump(by_alias=True), now - observed_at)
        connection.execute("INSERT OR REPLACE INTO telemetry VALUES (1,?,?,?)", (
            telemetry.model_dump_json(by_alias=True), self.db.runtime_id, now))
        return telemetry

    def ingest_telemetry(self, telemetry: DeviceTelemetry):
        telemetry = DeviceTelemetry.model_validate(telemetry.model_dump(by_alias=True))
        with self.db.transaction() as connection:
            old = self._current_telemetry(connection)
            observed_at = self.monotonic_ms()
            telemetry = normalize_telemetry(connection, telemetry, runtime_id=self.db.runtime_id, now_ms=observed_at)
            telemetry = self._store_telemetry(connection, telemetry, observed_at=observed_at)
            held = connection.execute("SELECT COUNT(*) FROM claims WHERE state='held'").fetchone()[0]
            if held and (old is None or any(
                a.occupied != b.occupied or a.quality != "valid" or b.quality != "valid"
                for a, b in zip(sorted(old.slots, key=lambda x: x.id), sorted(telemetry.slots, key=lambda x: x.id))
            )):
                connection.execute("UPDATE metadata SET value='1' WHERE key='reconciliation_required'")

    def _capacity(self, connection, telemetry):
        occupied = (sum(slot.occupied is True for slot in telemetry.slots)
                    if telemetry and all(slot.quality == "valid" for slot in telemetry.slots) else None)
        claims = connection.execute("SELECT COUNT(*) FROM claims WHERE state='held'").fetchone()[0]
        reconciliation = connection.execute("SELECT value FROM metadata WHERE key='reconciliation_required'").fetchone()[0] == "1"
        reconciliation |= occupied is not None and occupied + claims > 4
        return Capacity.from_internal(physical_occupied=occupied, outstanding_claims=claims,
            available=None if occupied is None or reconciliation else 4 - occupied - claims,
            reconciliation_required=reconciliation)

    def get_capacity(self):
        with self.db.transaction(write=False) as connection:
            return self._capacity(connection, self._current_telemetry(connection))

    def _session_row(self, connection, session_id):
        row = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise BusinessFault("NOT_FOUND", "Sesiunea nu există.")
        return row

    def _session(self, connection, row, *, at=None):
        paid = connection.execute("SELECT COALESCE(SUM(amount_bani),0) FROM payments WHERE session_id=?", (row["id"],)).fetchone()[0]
        due = (max(0, tariff_bani(row["entered_at"], self.clock_ms() if at is None else at, row["hourly_rate_bani"]) - paid)
               if row["entered_at"] is not None and row["paid_at"] is None else 0)
        return ParkingSession.from_internal(id=row["id"], plate=row["plate"], slot_id=row["slot_id"],
            entered_at=row["entered_at"], exited_at=row["exited_at"], status=row["status"],
            hourly_rate_bani=row["hourly_rate_bani"], amount_due_bani=due, paid_bani=paid)

    def get_session(self, session_id):
        with self.db.transaction(write=False) as connection:
            return self._session(connection, self._session_row(connection, session_id))

    def open_sessions(self):
        with self.db.transaction(write=False) as connection:
            return [self._session(connection, row) for row in connection.execute(
                "SELECT * FROM sessions WHERE status NOT IN ('completed','cancelled') ORDER BY created_at DESC,id DESC")]

    def process(self, command_id) -> CommandResult:
        """Persist business effects/prepared device command; never perform I/O here."""
        with self.db.transaction() as connection:
            row = self._command(connection, command_id)
            if row["status"] != "accepted":
                return self._result(row)
            action = json.loads(row["action_json"])
            # Business failures are results, not rolled-back command admission.
            connection.execute("SAVEPOINT business")
            try:
                if action["type"] == "pay":
                    self._pay(connection, row, action["sessionId"])
                elif action["type"] in ("enter", "exit"):
                    self._prepare_access(connection, row, action)
                elif self.mode == "hardware":
                    raise BusinessFault("SIMULATION_ONLY", "Acțiunea este rezervată simulării.")
                elif self.simulation_handler is not None:
                    self.simulation_handler(connection, row, action)
                else:
                    raise NotImplementedError("Demo actions are delegated to the simulator in step 5")
            except BusinessFault as failure:
                connection.execute("ROLLBACK TO business")
                self._transition(connection, row, "rejected", str(failure), failure.detail)
            finally:
                connection.execute("RELEASE business")
            return self._result(self._command(connection, command_id))

    def _pay(self, connection, command, session_id):
        session = self._session_row(connection, session_id)
        self._ensure_session_reconciled(connection, session_id)
        if session["status"] not in ("active", "paid"):
            raise BusinessFault("SESSION_CONFLICT", "Sesiunea nu permite plata.")
        if session["paid_at"] is None:
            now = self.clock_ms()
            amount = tariff_bani(session["entered_at"], now, session["hourly_rate_bani"])
            connection.execute("INSERT INTO payments VALUES (?,?,?,?,?)", (uuid4().hex, session_id, command["id"], amount, now))
            connection.execute("UPDATE sessions SET paid_at=?,status='paid' WHERE id=?", (now, session_id))
            self._event(connection, "PAYMENT_RECORDED", "Plata simulată a fost salvată.", command_id=command["id"], session_id=session_id)
        connection.execute("UPDATE commands SET session_id=? WHERE id=?", (session_id, command["id"]))
        self._transition(connection, self._command(connection, command["id"]), "done", "Sesiunea este plătită.")

    def _ensure_session_reconciled(self, connection, session_id):
        if connection.execute("""SELECT 1 FROM device_commands d JOIN commands c ON c.id=d.command_id
            WHERE c.session_id=? AND d.contradiction=1""", (session_id,)).fetchone():
            raise BusinessFault("SESSION_CONFLICT", "Sesiunea are o contradicție MCU nereconciliată.")

    def _prepare_access(self, connection, command, action):
        entrance = action["type"] == "enter"
        node_id, barrier_id = ("S3", "entry") if entrance else ("S4", "exit")
        telemetry = self._current_telemetry(connection)
        if telemetry is None:
            raise BusinessFault("DATA_UNAVAILABLE", "Telemetria nu este disponibilă.", retryable=True)
        barrier = next(item for item in telemetry.barriers if item.id == barrier_id)
        if barrier.quality != "valid":
            raise BusinessFault("DATA_UNAVAILABLE", "Starea barierei este necunoscută.", retryable=True)
        if barrier.obstacle or barrier.state != "CLOSED":
            raise BusinessFault("INTERLOCK_ACTIVE", "Bariera nu permite o nouă deschidere.")
        busy = connection.execute("""SELECT 1 FROM device_commands d JOIN commands c ON c.id=d.command_id
            WHERE d.node_id=? AND c.status IN ('executing','unknown')""", (node_id,)).fetchone()
        if busy:
            raise BusinessFault("INTERLOCK_ACTIVE", "Există o comandă nerezolvată pe această barieră.")
        if entrance:
            if connection.execute("SELECT 1 FROM sessions WHERE plate=? AND status NOT IN ('completed','cancelled')", (action["plate"],)).fetchone():
                raise BusinessFault("SESSION_CONFLICT", "Vehiculul are deja o sesiune deschisă.")
            capacity = self._capacity(connection, telemetry)
            if capacity.available is None:
                raise BusinessFault("DATA_UNAVAILABLE", "Capacitatea necesită date valide și reconciliate.", retryable=True)
            if capacity.available == 0:
                raise BusinessFault("PARKING_FULL", "Parcarea este plină.")
            session_id = uuid4().hex
            connection.execute("""INSERT INTO sessions (id,plate,created_at,status,hourly_rate_bani)
                VALUES (?,?,?,'pending_entry',?)""", (session_id, action["plate"], self.clock_ms(), self.hourly_rate_bani))
            connection.execute("INSERT INTO claims VALUES (?,?,'held',?)", (session_id, command["id"], self.clock_ms()))
        else:
            session = self._session_row(connection, action["sessionId"])
            self._ensure_session_reconciled(connection, session["id"])
            if session["status"] == "active":
                raise BusinessFault("PAYMENT_REQUIRED", "Ieșirea necesită plata simulată.")
            if session["status"] != "paid":
                raise BusinessFault("SESSION_CONFLICT", "Sesiunea nu permite ieșirea.")
            session_id = session["id"]
            connection.execute("UPDATE sessions SET status='pending_exit' WHERE id=?", (session_id,))
        boot = next(item.boot_epoch for item in telemetry.stations if item.id == node_id)
        counter = connection.execute("SELECT last_id FROM device_counters WHERE node_id=? AND boot_epoch=?", (node_id, boot)).fetchone()
        numeric_id = (counter[0] if counter else 0) + 1
        if numeric_id > 0xFFFFFFFF:
            raise BusinessFault("DEVICE_INCOMPATIBLE", "Spațiul ID MCU este epuizat; este necesară mentenanță.")
        device = DeviceCommand.from_internal(node_id=node_id, command_id=numeric_id, operation="open", ttl_ms=2000,
            authorization="capacity" if entrance else "payment", expected_boot_epoch=boot)
        connection.execute("INSERT OR REPLACE INTO device_counters VALUES (?,?,?)", (node_id, boot, numeric_id))
        connection.execute("""INSERT INTO device_commands
            (command_id,node_id,boot_epoch,device_id,block_json,send_state) VALUES (?,?,?,?,?,'prepared')""",
            (command["id"], node_id, boot, numeric_id, device.model_dump_json(by_alias=True)))
        connection.execute("UPDATE commands SET session_id=? WHERE id=?", (session_id, command["id"]))
        self._transition(connection, self._command(connection, command["id"]), "executing", "Accesul a fost pregătit; trecerea nu este confirmată.")

    def claim_dispatch(self, command_id) -> DeviceCommand | None:
        """Persist the send intent BEFORE I/O. A crash never triggers blind resend."""
        with self.db.transaction() as connection:
            command = self._command(connection, command_id)
            row = connection.execute("SELECT * FROM device_commands WHERE command_id=?", (command_id,)).fetchone()
            if row is None or row["send_state"] != "prepared" or command["status"] != "executing":
                return None
            try:
                self._ensure_session_reconciled(connection, command["session_id"])
            except BusinessFault as failure:
                self._transition(connection, command, "unknown", "Dispatch blocat de contradicția sesiunii.", failure.detail)
                return None
            device = DeviceCommand.model_validate_json(row["block_json"])
            # Recheck after preparation: telemetry may have expired while queued.
            telemetry = self._current_telemetry(connection)
            station = next((s for s in telemetry.stations if s.id == device.node_id), None) if telemetry else None
            barrier = next((b for b in telemetry.barriers if b.node_id == device.node_id), None) if telemetry else None
            unsafe = (barrier is None or barrier.quality != "valid" or barrier.obstacle or barrier.state != "CLOSED")
            if json.loads(command["action_json"])["type"] == "enter":
                unsafe |= self._capacity(connection, telemetry).available is None
            if station is None or station.quality != "valid" or station.boot_epoch != device.expected_boot_epoch or unsafe:
                self._transition(connection, command, "unknown", "Dispozitivul nu mai poate fi validat înainte de trimitere.",
                                 ErrorDetail(code="DATA_UNAVAILABLE", message="Reconciliere necesară.", retryable=True))
                return None
            connection.execute("UPDATE device_commands SET send_state='sent',sent_at=? WHERE command_id=?", (self.clock_ms(), command_id))
            return device

    def record_device_result(self, command_id, result: DeviceCommandResult):
        result = DeviceCommandResult.model_validate(result.model_dump(by_alias=True))
        with self.db.transaction() as connection:
            command = self._command(connection, command_id)
            binding = connection.execute("SELECT * FROM device_commands WHERE command_id=?", (command_id,)).fetchone()
            if binding is None or binding["send_state"] != "sent":
                raise BusinessFault("SESSION_CONFLICT", "Comanda nu a fost trimisă.")
            device = DeviceCommand.model_validate_json(binding["block_json"])
            if (result.node_id, result.command_id, result.boot_epoch) != (device.node_id, device.command_id, device.expected_boot_epoch):
                raise BusinessFault("SESSION_CONFLICT", "Rezultatul aparține altei comenzi.")
            if result.status != "unknown" and result.command_block != device.registers():
                raise BusinessFault("SESSION_CONFLICT", "Ecoul comenzii nu corespunde.")
            if self.mode == "hardware" and result.evidence == "simulation":
                raise BusinessFault("SIMULATION_ONLY", "Rezultat de simulator în modul hardware.")
            progress = result.status in ("accepted", "executing", "done", "failed", "expired")
            refused = result.status == "rejected"
            contradiction = binding["contradiction"] or (refused and binding["progress_seen"]) or (progress and binding["refusal_seen"])
            connection.execute("""UPDATE device_commands SET progress_seen=MAX(progress_seen,?),
                refusal_seen=MAX(refusal_seen,?),contradiction=MAX(contradiction,?) WHERE command_id=?""",
                (int(progress), int(refused), int(bool(contradiction)), command_id))
            if contradiction:
                connection.execute("UPDATE device_commands SET result_json=? WHERE command_id=?", (result.model_dump_json(by_alias=True), command_id))
                connection.execute("UPDATE metadata SET value='1' WHERE key='reconciliation_required'")
                # A late contradiction may invalidate a previously released claim.
                # Freeze capacity globally rather than silently recreating a cancelled session.
                self._transition(connection, command, "unknown", "Rezultate MCU contradictorii; reconciliere explicită necesară.",
                                 ErrorDetail(code="COMMAND_FAILED", message="Contradicție MCU persistentă."))
                return self._result(self._command(connection, command_id))
            if command["status"] not in ("executing", "unknown"):
                return self._result(command)
            connection.execute("UPDATE device_commands SET result_json=? WHERE command_id=?", (result.model_dump_json(by_alias=True), command_id))
            try:
                self._ensure_session_reconciled(connection, command["session_id"])
            except BusinessFault as failure:
                self._transition(connection, command, "unknown", "Rezultat MCU salvat fără tranziția sesiunii contradictorii.", failure.detail)
                return self._result(self._command(connection, command_id))
            if result.status == "rejected":
                action = json.loads(command["action_json"])
                if action["type"] == "enter":
                    connection.execute("UPDATE sessions SET status='cancelled' WHERE id=?", (command["session_id"],))
                    connection.execute("UPDATE claims SET state='released',updated_at=? WHERE session_id=?", (self.clock_ms(), command["session_id"]))
                else:
                    connection.execute("UPDATE sessions SET status='paid' WHERE id=?", (command["session_id"],))
                self._transition(connection, command, "rejected", "Dispozitivul a refuzat accesul înainte de executare.",
                                 ErrorDetail(code="COMMAND_FAILED", message=f"Refuz MCU: {result.result_code}"))
            elif result.status in ("accepted", "executing"):
                self._transition(connection, command, "executing", "Comanda MCU este în curs; se așteaptă dovada trecerii.")
            else:
                self._transition(connection, command, "unknown", "Rezultatul accesului necesită dovadă de trecere/reconciliere.",
                                 ErrorDetail(code="DEVICE_TIMEOUT" if result.status == "unknown" else "COMMAND_FAILED",
                                             message="Trecerea nu este demonstrată.", retryable=True))
            return self._result(self._command(connection, command_id))

    def _existing_evidence(self, connection, evidence_id, payload):
        stored = connection.execute("SELECT payload_json FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        if stored is None:
            return False
        if stored[0] != payload:
            raise BusinessFault("SESSION_CONFLICT", "ID-ul dovezii identifică alt conținut.")
        return True

    def consume_passage(self, command_id, evidence: PassageEvidence) -> bool:
        evidence = PassageEvidence.model_validate(evidence.model_dump(by_alias=True))
        payload = canonical({"commandId": command_id, "evidence": evidence.model_dump(by_alias=True)})
        with self.db.transaction() as connection:
            if evidence.evidence_id and self._existing_evidence(connection, evidence.evidence_id, payload):
                return False
            command = self._command(connection, command_id)
            self._ensure_session_reconciled(connection, command["session_id"])
            action = json.loads(command["action_json"])
            binding = connection.execute("SELECT * FROM device_commands WHERE command_id=?", (command_id,)).fetchone()
            if binding is None or binding["send_state"] != "sent" or command["status"] not in ("executing", "unknown"):
                raise BusinessFault("SESSION_CONFLICT", "Comanda nu permite o nouă dovadă de trecere.")
            if binding["contradiction"]:
                raise BusinessFault("SESSION_CONFLICT", "Contradicția MCU interzice confirmarea automată.")
            device = DeviceCommand.model_validate_json(binding["block_json"])
            if not passage_matches(device, evidence, mode=self.mode, business_action=action["type"]):
                raise BusinessFault("SESSION_CONFLICT", "Dovada nu corespunde accesului și modului curent.")
            if evidence.occurred_at < binding["sent_at"] or evidence.occurred_at > self.clock_ms():
                raise BusinessFault("SESSION_CONFLICT", "Dovada este în afara intervalului comenzii.")
            progress = DeviceCommandResult.model_validate_json(binding["result_json"]) if binding["result_json"] else None
            if progress is None or progress.status not in ("accepted", "executing", "done"):
                raise BusinessFault("DATA_UNAVAILABLE", "Nu există progres MCU neconflictual pentru dovadă.")
            session = self._session_row(connection, command["session_id"])
            entrance = action["type"] == "enter"
            expected_status = "pending_entry" if entrance else "pending_exit"
            if session["status"] != expected_status:
                raise BusinessFault("SESSION_CONFLICT", "Sesiunea nu așteaptă această trecere.")
            if not entrance and evidence.occurred_at < max(session["entered_at"], session["paid_at"]):
                raise BusinessFault("SESSION_CONFLICT", "Ieșirea precedă intrarea sau plata.")
            connection.execute("INSERT INTO evidence VALUES (?,'passage',?,?,?,?)", (
                evidence.evidence_id, command_id, session["id"], payload, evidence.occurred_at))
            if entrance:
                connection.execute("UPDATE sessions SET status='active',entered_at=? WHERE id=?", (evidence.occurred_at, session["id"]))
            else:
                connection.execute("UPDATE sessions SET status='completed',exited_at=? WHERE id=?", (evidence.occurred_at, session["id"]))
                connection.execute("UPDATE claims SET state='released',updated_at=? WHERE session_id=? AND state='held'", (self.clock_ms(), session["id"]))
            self._transition(connection, command, "done", "Trecerea a fost confirmată și salvată.")
            self._event(connection, "PASSAGE_CONFIRMED", "Dovadă de trecere consumată.", command_id=command_id,
                        session_id=session["id"], node_id=device.node_id, level="success")
            return True

    def account_occupancy(self, session_id, slot_id, telemetry: DeviceTelemetry, *, evidence_id):
        """Trusted simulator transaction: explicit occupancy event, not inferred plate ID."""
        TypeAdapter(Identifier).validate_python(evidence_id, strict=True)
        TypeAdapter(SlotId).validate_python(slot_id, strict=True)
        if self.mode != "simulation":
            raise BusinessFault("SIMULATION_ONLY", "Contabilizarea simulată nu este permisă în hardware.")
        telemetry = DeviceTelemetry.model_validate(telemetry.model_dump(by_alias=True))
        payload = canonical({"kind": "occupancy", "sessionId": session_id, "slotId": slot_id,
                             "telemetry": telemetry.model_dump(by_alias=True)})
        with self.db.transaction() as connection:
            if self._existing_evidence(connection, evidence_id, payload):
                return False
            session = self._session_row(connection, session_id)
            self._ensure_session_reconciled(connection, session_id)
            claim = connection.execute("SELECT * FROM claims WHERE session_id=?", (session_id,)).fetchone()
            old = self._current_telemetry(connection)
            if session["status"] not in ("active", "paid") or claim is None or claim["state"] != "held" or old is None:
                raise BusinessFault("SESSION_CONFLICT", "Nu există o intrare confirmată necontabilizată.")
            binding = connection.execute("SELECT contradiction FROM device_commands WHERE command_id=?", (claim["command_id"],)).fetchone()
            if binding is None or binding[0]:
                raise BusinessFault("SESSION_CONFLICT", "Contabilizarea nu poate rezolva o contradicție MCU.")
            observed_at = self.monotonic_ms()
            telemetry = normalize_telemetry(connection, telemetry, runtime_id=self.db.runtime_id, now_ms=observed_at)
            # Save inside this transaction FIRST; rejection below rolls back both
            # the candidate snapshot/history and every business mutation.
            telemetry = self._store_telemetry(connection, telemetry, observed_at=observed_at)
            before = {slot.id: slot for slot in old.slots}
            after = {slot.id: slot for slot in telemetry.slots}
            if slot_id not in before or any(slot.quality != "valid" for slot in [*before.values(), *after.values()]):
                raise BusinessFault("DATA_UNAVAILABLE", "Contabilizarea necesită senzori valizi.")
            if before[slot_id].occupied is not False or after[slot_id].occupied is not True or any(
                before[i].occupied != after[i].occupied for i in before if i != slot_id
            ):
                raise BusinessFault("SESSION_CONFLICT", "Dovada nu reprezintă o singură ocupare corelată.")
            if connection.execute("SELECT 1 FROM sessions WHERE slot_id=? AND status NOT IN ('completed','cancelled')", (slot_id,)).fetchone():
                raise BusinessFault("SESSION_CONFLICT", "Locul este deja asociat unei sesiuni.")
            connection.execute("INSERT INTO evidence VALUES (?,'occupancy',?,?,?,?)", (
                evidence_id, claim["command_id"], session_id, payload, self.clock_ms()))
            connection.execute("UPDATE claims SET state='accounted',updated_at=? WHERE session_id=?", (self.clock_ms(), session_id))
            connection.execute("UPDATE sessions SET slot_id=? WHERE id=?", (slot_id, session_id))
            # No ambiguity is cleared merely because a matching net count appears.
            self._event(connection, "OCCUPANCY_ACCOUNTED", "Rezervarea a fost transferată către ocuparea confirmată.",
                        command_id=claim["command_id"], session_id=session_id)
            return True

    def recover(self):
        """Called once at startup, before workers; never called per request."""
        with self.db.transaction() as connection:
            prepared = connection.execute("""SELECT c.* FROM commands c JOIN device_commands d ON d.command_id=c.id
                WHERE d.send_state='prepared' AND c.status IN ('executing','unknown')""").fetchall()
            for row in prepared:
                try:
                    self._ensure_session_reconciled(connection, row["session_id"])
                except BusinessFault:
                    self._transition(connection, row, "rejected", "Pregătire netrimisă anulată; sesiunea contradictorie rămâne înghețată.",
                                     ErrorDetail(code="SESSION_CONFLICT", message="Reconciliere explicită a sesiunii necesară."))
                    continue
                action = json.loads(row["action_json"])
                if action["type"] == "enter":
                    connection.execute("UPDATE sessions SET status='cancelled' WHERE id=? AND status='pending_entry'", (row["session_id"],))
                    connection.execute("UPDATE claims SET state='released',updated_at=? WHERE session_id=? AND state='held'", (self.clock_ms(), row["session_id"]))
                else:
                    connection.execute("UPDATE sessions SET status='paid' WHERE id=? AND status='pending_exit'", (row["session_id"],))
                self._transition(connection, row, "rejected", "Pregătire anulată la restart: intenția de trimitere nu a fost înregistrată.",
                                 ErrorDetail(code="COMMAND_FAILED", message="Comandă sigur netrimisă; se poate crea o intenție nouă."))
            rows = connection.execute("SELECT * FROM commands WHERE status='executing'").fetchall()
            for row in rows:
                self._transition(connection, row, "unknown", "Execuție întreruptă de restart; fără retrimitere automată.",
                                 ErrorDetail(code="DEVICE_TIMEOUT", message="Este necesară reconcilierea.", retryable=True))
            connection.execute("DELETE FROM telemetry")
            connection.execute("UPDATE telemetry_history SET continuity=0")
            return len(rows) + len(prepared)

    def account_departure(self, command_id, slot_id, telemetry):
        """Correlated simulator exit; an unrelated held claim is not consumed."""
        if self.mode != "simulation":
            raise BusinessFault("SIMULATION_ONLY", "Eliberarea simulată nu este permisă în hardware.")
        TypeAdapter(SlotId).validate_python(slot_id, strict=True)
        telemetry = DeviceTelemetry.model_validate(telemetry.model_dump(by_alias=True))
        with self.db.transaction() as connection:
            command = self._command(connection, command_id)
            self._ensure_session_reconciled(connection, command["session_id"])
            session = self._session_row(connection, command["session_id"])
            if (json.loads(command["action_json"])["type"] != "exit" or command["status"] != "done"
                    or session["status"] != "completed" or session["slot_id"] != slot_id
                    or not connection.execute("SELECT 1 FROM evidence WHERE command_id=? AND kind='passage'", (command_id,)).fetchone()):
                raise BusinessFault("SESSION_CONFLICT", "Eliberarea nu are o ieșire confirmată asociată.")
            if connection.execute("SELECT 1 FROM events WHERE command_id=? AND code='DEPARTURE_ACCOUNTED'", (command_id,)).fetchone():
                return False
            old = self._current_telemetry(connection)
            observed_at = self.monotonic_ms()
            candidate = normalize_telemetry(connection, telemetry, runtime_id=self.db.runtime_id, now_ms=observed_at)
            candidate = self._store_telemetry(connection, candidate, observed_at=observed_at)
            if old is None or any(slot.quality != "valid" for slot in [*old.slots, *candidate.slots]):
                raise BusinessFault("DATA_UNAVAILABLE", "Eliberarea necesită senzori valizi.")
            before, after = {slot.id: slot for slot in old.slots}, {slot.id: slot for slot in candidate.slots}
            if after[slot_id].occupied is not False or any(before[i].occupied != after[i].occupied for i in before if i != slot_id):
                raise BusinessFault("SESSION_CONFLICT", "Eliberarea modifică alte locuri sau nu confirmă locul liber.")
            self._event(connection, "DEPARTURE_ACCOUNTED", "Senzorul simulat confirmă locul liber după ieșire.",
                        command_id=command_id, session_id=session["id"])
            return True

    def pending_commands(self):
        with self.db.transaction(write=False) as connection:
            return [row[0] for row in connection.execute("SELECT id FROM commands WHERE status='accepted' ORDER BY created_at,id")]

    def processable_commands(self, *, limit=50, excluded=frozenset(), ordered_ids=None):
        self._pagination(limit, None)
        with self.db.transaction(write=False) as connection:
            commands = []
            rows = (connection.execute("SELECT id,action_json FROM commands WHERE id=? AND status='accepted'", (identifier,)).fetchone()
                    for identifier in ordered_ids) if ordered_ids is not None else connection.execute(
                        "SELECT id,action_json FROM commands WHERE status='accepted' ORDER BY created_at,id")
            for row in rows:
                if row is not None and row["id"] not in excluded and (self.mode == "hardware" or self.simulation_handler is not None or json.loads(row["action_json"])["type"] in ("enter", "pay", "exit")):
                    commands.append(row["id"])
                    if len(commands) == limit:
                        break
            return commands

    def snapshot(self, *, transport="TCP") -> ParkingSnapshot:
        """One SQLite read snapshot and one valuation time for all business data."""
        with self.db.transaction(write=False) as connection:
            telemetry = self._current_telemetry(connection) or unknown_telemetry()
            selected_transport = connection.execute("SELECT value FROM metadata WHERE key='simulation_transport'").fetchone()
            if self.mode == "simulation" and selected_transport:
                transport = selected_transport[0]
            now = self.clock_ms()
            sessions = [self._session(connection, row, at=now) for row in connection.execute(
                "SELECT * FROM sessions WHERE status NOT IN ('completed','cancelled') ORDER BY created_at DESC,id DESC")]
            assigned = {session.slot_id: session.id for session in sessions if session.slot_id is not None}
            slots = [ParkingSlot.model_validate(slot.model_dump(by_alias=True) | {"sessionId": assigned.get(slot.id)})
                     for slot in telemetry.slots]
            events = [ParkingEvent.from_internal(**dict(row)) for row in connection.execute(
                "SELECT * FROM events ORDER BY at DESC,id DESC LIMIT 50")]
            commands = [self._result(row) for row in connection.execute(
                "SELECT * FROM commands ORDER BY created_at DESC,id DESC LIMIT 50")]
            return ParkingSnapshot.from_internal(
                mode=self.mode, transport=transport, updated_at=now, hourly_rate_bani=self.hourly_rate_bani,
                stale_after_ms=telemetry.stale_after_ms, stations=telemetry.stations, slots=slots,
                barriers=telemetry.barriers, capacity=self._capacity(connection, telemetry),
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
        anchor = self._pagination(limit, cursor)
        where = f"WHERE ({time_column},id) < (?,?)" if anchor else ""
        rows = connection.execute(f"SELECT * FROM {table} {where} ORDER BY {time_column} DESC,id DESC LIMIT ?",
                                  (*anchor, limit + 1) if anchor else (limit + 1,)).fetchall()
        next_cursor = (base64.urlsafe_b64encode(canonical([rows[limit - 1][time_column], rows[limit - 1]["id"]]).encode()).decode().rstrip("=")
                       if len(rows) > limit else None)
        return rows[:limit], next_cursor

    def list_sessions(self, *, limit=50, cursor=None):
        with self.db.transaction(write=False) as connection:
            rows, next_cursor = self._page(connection, "sessions", "created_at", limit, cursor)
            return SessionPage.from_internal(items=[self._session(connection, row) for row in rows], next_cursor=next_cursor)

    def list_events(self, *, limit=50, cursor=None):
        with self.db.transaction(write=False) as connection:
            rows, next_cursor = self._page(connection, "events", "at", limit, cursor)
            items = [ParkingEvent.from_internal(**dict(row)) for row in rows]
            return EventPage.from_internal(items=items, next_cursor=next_cursor)
