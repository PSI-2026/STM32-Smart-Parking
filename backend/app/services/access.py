"""AccessService: application operations; repository calls use the caller transaction."""


import json
from uuid import uuid4
from ..contracts.api import ErrorDetail
from ..contracts.firmware import DeviceCommand, DeviceCommandResult, PassageEvidence, passage_matches
from ..observations import boot_floors

from .common import BusinessFault, canonical


class AccessService:
    def __init__(self, parking):
        self.parking = parking

    def _prepare_access(self, connection, command, action):
        entrance = action["type"] == "enter"
        node_id, barrier_id = ("S3", "entry") if entrance else ("S4", "exit")
        telemetry = self.parking._current_telemetry(connection)
        if telemetry is None:
            raise BusinessFault("DATA_UNAVAILABLE", "Telemetria nu este disponibilă.", retryable=True)
        barrier = next(item for item in telemetry.barriers if item.id == barrier_id)
        if barrier.quality != "valid":
            raise BusinessFault("DATA_UNAVAILABLE", "Starea barierei este necunoscută.", retryable=True)
        if barrier.obstacle or barrier.state != "CLOSED":
            raise BusinessFault("INTERLOCK_ACTIVE", "Bariera nu permite o nouă deschidere.")
        busy = self.parking.repository.barrier_busy(connection, (node_id,)).fetchone()
        if busy:
            raise BusinessFault("INTERLOCK_ACTIVE", "Există o comandă nerezolvată pe această barieră.")
        if entrance:
            if self.parking.repository.open_plate(connection, (action["plate"],)).fetchone():
                raise BusinessFault("SESSION_CONFLICT", "Vehiculul are deja o sesiune deschisă.")
            capacity = self.parking._capacity(connection, telemetry)
            if capacity.available is None:
                raise BusinessFault("DATA_UNAVAILABLE", "Capacitatea necesită date valide și reconciliate.", retryable=True)
            if capacity.available == 0:
                raise BusinessFault("PARKING_FULL", "Parcarea este plină.")
            session_id = uuid4().hex
            self.parking.repository.insert_session(connection, (session_id, action["plate"], self.parking.clock_ms(), self.parking.hourly_rate_bani))
            self.parking.repository.insert_claim(connection, (session_id, command["id"], self.parking.clock_ms()))
        else:
            session = self.parking._session_row(connection, action["sessionId"])
            self.parking._ensure_session_reconciled(connection, session["id"])
            if session["status"] == "active":
                raise BusinessFault("PAYMENT_REQUIRED", "Ieșirea necesită plata simulată.")
            if session["status"] != "paid":
                raise BusinessFault("SESSION_CONFLICT", "Sesiunea nu permite ieșirea.")
            session_id = session["id"]
            self.parking.repository.prepare_exit(connection, (session_id,))
        boot = next(item.boot_epoch for item in telemetry.stations if item.id == node_id)
        counter = self.parking.repository.device_counter(connection, (node_id, boot)).fetchone()
        numeric_id = (counter[0] if counter else 0) + 1
        if numeric_id > 0xFFFFFFFF:
            raise BusinessFault("DEVICE_INCOMPATIBLE", "Spațiul ID MCU este epuizat; este necesară mentenanță.")
        device = DeviceCommand.from_internal(node_id=node_id, command_id=numeric_id, operation="open", ttl_ms=2000,
            authorization="capacity" if entrance else "payment", expected_boot_epoch=boot)
        self.parking.repository.save_device_counter(connection, (node_id, boot, numeric_id))
        self.parking.repository.prepare_device_command(connection, (command["id"], node_id, boot, numeric_id, device.model_dump_json(by_alias=True)))
        self.parking.repository.bind_command_session(connection, (session_id, command["id"]))
        self.parking._transition(connection, self.parking._command(connection, command["id"]), "executing", "Accesul a fost pregătit; trecerea nu este confirmată.")

    def claim_dispatch(self, command_id) -> DeviceCommand | None:
        """Persist the send intent BEFORE I/O. A crash never triggers blind resend."""
        with self.parking.db.transaction() as connection:
            command = self.parking._command(connection, command_id)
            row = self.parking.repository.device_binding(connection, (command_id,)).fetchone()
            if row is None or row["send_state"] != "prepared" or command["status"] != "executing":
                return None
            try:
                self.parking._ensure_session_reconciled(connection, command["session_id"])
            except BusinessFault as failure:
                self.parking._transition(connection, command, "unknown", "Dispatch blocat de contradicția sesiunii.", failure.detail)
                return None
            device = DeviceCommand.model_validate_json(row["block_json"])
            # Recheck after preparation: telemetry may have expired while queued.
            telemetry = self.parking._current_telemetry(connection)
            station = next((s for s in telemetry.stations if s.id == device.node_id), None) if telemetry else None
            barrier = next((b for b in telemetry.barriers if b.node_id == device.node_id), None) if telemetry else None
            unsafe = (barrier is None or barrier.quality != "valid" or barrier.obstacle or barrier.state != "CLOSED")
            if json.loads(command["action_json"])["type"] == "enter":
                unsafe |= self.parking._capacity(connection, telemetry).available is None
            if station is None or station.quality != "valid" or station.boot_epoch != device.expected_boot_epoch or unsafe:
                self.parking._transition(connection, command, "unknown", "Dispozitivul nu mai poate fi validat înainte de trimitere.",
                                 ErrorDetail(code="DATA_UNAVAILABLE", message="Reconciliere necesară.", retryable=True))
                return None
            self.parking.repository.mark_device_sent(connection, (self.parking.clock_ms(), command_id))
            return device

    def record_device_result(self, command_id, result: DeviceCommandResult):
        result = DeviceCommandResult.model_validate(result.model_dump(by_alias=True))
        with self.parking.db.transaction() as connection:
            command = self.parking._command(connection, command_id)
            binding = self.parking.repository.device_binding(connection, (command_id,)).fetchone()
            if binding is None or binding["send_state"] != "sent":
                raise BusinessFault("SESSION_CONFLICT", "Comanda nu a fost trimisă.")
            device = DeviceCommand.model_validate_json(binding["block_json"])
            if (result.node_id, result.command_id, result.boot_epoch) != (device.node_id, device.command_id, device.expected_boot_epoch):
                raise BusinessFault("SESSION_CONFLICT", "Rezultatul aparține altei comenzi.")
            if result.status != "unknown" and result.command_block != device.registers():
                raise BusinessFault("SESSION_CONFLICT", "Ecoul comenzii nu corespunde.")
            if self.parking.mode == "hardware" and result.evidence == "simulation":
                raise BusinessFault("SIMULATION_ONLY", "Rezultat de simulator în modul hardware.")
            if self.parking.mode == "hardware" and result.status != "unknown":
                # Durable boot floor checked atomically with every result effect.
                if result.boot_epoch < boot_floors(connection).get(device.node_id, 0):
                    from ..contracts.firmware import result_for
                    result = result_for(device, None)
            progress = result.status in ("accepted", "executing", "done", "failed", "expired")
            refused = result.status == "rejected"
            contradiction = binding["contradiction"] or (refused and binding["progress_seen"]) or (progress and binding["refusal_seen"])
            self.parking.repository.update_device_flags(connection, (int(progress), int(refused), int(bool(contradiction)), command_id))
            if contradiction:
                self.parking.repository.save_device_result(connection, (result.model_dump_json(by_alias=True), command_id))
                self.parking.repository.require_reconciliation(connection)
                # A late contradiction may invalidate a previously released claim.
                # Freeze capacity globally rather than silently recreating a cancelled session.
                self.parking._transition(connection, command, "unknown", "Rezultate MCU contradictorii; reconciliere explicită necesară.",
                                 ErrorDetail(code="COMMAND_FAILED", message="Contradicție MCU persistentă."))
                return self.parking._result(self.parking._command(connection, command_id))
            if command["status"] not in ("executing", "unknown"):
                return self.parking._result(command)
            self.parking.repository.save_device_result(connection, (result.model_dump_json(by_alias=True), command_id))
            try:
                self.parking._ensure_session_reconciled(connection, command["session_id"])
            except BusinessFault as failure:
                self.parking._transition(connection, command, "unknown", "Rezultat MCU salvat fără tranziția sesiunii contradictorii.", failure.detail)
                return self.parking._result(self.parking._command(connection, command_id))
            if result.status == "rejected":
                action = json.loads(command["action_json"])
                if action["type"] == "enter":
                    self.parking.repository.cancel_session(connection, (command["session_id"],))
                    self.parking.repository.release_claim(connection, (self.parking.clock_ms(), command["session_id"]))
                else:
                    self.parking.repository.restore_paid(connection, (command["session_id"],))
                self.parking._transition(connection, command, "rejected", "Dispozitivul a refuzat accesul înainte de executare.",
                                 ErrorDetail(code="COMMAND_FAILED", message=f"Refuz MCU: {result.result_code}"))
            elif result.status in ("accepted", "executing"):
                self.parking._transition(connection, command, "executing", "Comanda MCU este în curs; se așteaptă dovada trecerii.")
            else:
                self.parking._transition(connection, command, "unknown", "Rezultatul accesului necesită dovadă de trecere/reconciliere.",
                                 ErrorDetail(code="DEVICE_TIMEOUT" if result.status == "unknown" else "COMMAND_FAILED",
                                             message="Trecerea nu este demonstrată.", retryable=True))
            return self.parking._result(self.parking._command(connection, command_id))

    def _existing_evidence(self, connection, evidence_id, payload):
        stored = self.parking.repository.evidence(connection, (evidence_id,)).fetchone()
        if stored is None:
            return False
        if stored[0] != payload:
            raise BusinessFault("SESSION_CONFLICT", "ID-ul dovezii identifică alt conținut.")
        return True

    def consume_passage(self, command_id, evidence: PassageEvidence) -> bool:
        evidence = PassageEvidence.model_validate(evidence.model_dump(by_alias=True))
        payload = canonical({"commandId": command_id, "evidence": evidence.model_dump(by_alias=True)})
        with self.parking.db.transaction() as connection:
            if evidence.evidence_id and self.parking._existing_evidence(connection, evidence.evidence_id, payload):
                return False
            command = self.parking._command(connection, command_id)
            self.parking._ensure_session_reconciled(connection, command["session_id"])
            action = json.loads(command["action_json"])
            binding = self.parking.repository.device_binding(connection, (command_id,)).fetchone()
            if binding is None or binding["send_state"] != "sent" or command["status"] not in ("executing", "unknown"):
                raise BusinessFault("SESSION_CONFLICT", "Comanda nu permite o nouă dovadă de trecere.")
            if binding["contradiction"]:
                raise BusinessFault("SESSION_CONFLICT", "Contradicția MCU interzice confirmarea automată.")
            device = DeviceCommand.model_validate_json(binding["block_json"])
            if not passage_matches(device, evidence, mode=self.parking.mode, business_action=action["type"]):
                raise BusinessFault("SESSION_CONFLICT", "Dovada nu corespunde accesului și modului curent.")
            if evidence.occurred_at < binding["sent_at"] or evidence.occurred_at > self.parking.clock_ms():
                raise BusinessFault("SESSION_CONFLICT", "Dovada este în afara intervalului comenzii.")
            progress = DeviceCommandResult.model_validate_json(binding["result_json"]) if binding["result_json"] else None
            if progress is None or progress.status not in ("accepted", "executing", "done"):
                raise BusinessFault("DATA_UNAVAILABLE", "Nu există progres MCU neconflictual pentru dovadă.")
            session = self.parking._session_row(connection, command["session_id"])
            entrance = action["type"] == "enter"
            expected_status = "pending_entry" if entrance else "pending_exit"
            if session["status"] != expected_status:
                raise BusinessFault("SESSION_CONFLICT", "Sesiunea nu așteaptă această trecere.")
            if not entrance and evidence.occurred_at < max(session["entered_at"], session["paid_at"]):
                raise BusinessFault("SESSION_CONFLICT", "Ieșirea precedă intrarea sau plata.")
            self.parking.repository.insert_passage(connection, (
                evidence.evidence_id, command_id, session["id"], payload, evidence.occurred_at))
            if entrance:
                self.parking.repository.activate_session(connection, (evidence.occurred_at, session["id"]))
            else:
                self.parking.repository.complete_session(connection, (evidence.occurred_at, session["id"]))
                self.parking.repository.release_held_claim(connection, (self.parking.clock_ms(), session["id"]))
            self.parking._transition(connection, command, "done", "Trecerea a fost confirmată și salvată.")
            self.parking._event(connection, "PASSAGE_CONFIRMED", "Dovadă de trecere consumată.", command_id=command_id,
                        session_id=session["id"], node_id=device.node_id, level="success")
            return True

    def recover(self):
        """Called once at startup, before workers; never called per request."""
        with self.parking.db.transaction() as connection:
            prepared = self.parking.repository.prepared_commands(connection).fetchall()
            for row in prepared:
                try:
                    self.parking._ensure_session_reconciled(connection, row["session_id"])
                except BusinessFault:
                    self.parking._transition(connection, row, "rejected", "Pregătire netrimisă anulată; sesiunea contradictorie rămâne înghețată.",
                                     ErrorDetail(code="SESSION_CONFLICT", message="Reconciliere explicită a sesiunii necesară."))
                    continue
                action = json.loads(row["action_json"])
                if action["type"] == "enter":
                    self.parking.repository.cancel_pending_entry(connection, (row["session_id"],))
                    self.parking.repository.release_held_claim(connection, (self.parking.clock_ms(), row["session_id"]))
                else:
                    self.parking.repository.restore_pending_exit(connection, (row["session_id"],))
                self.parking._transition(connection, row, "rejected", "Pregătire anulată la restart: intenția de trimitere nu a fost înregistrată.",
                                 ErrorDetail(code="COMMAND_FAILED", message="Comandă sigur netrimisă; se poate crea o intenție nouă."))
            rows = self.parking.repository.executing_commands(connection).fetchall()
            for row in rows:
                self.parking._transition(connection, row, "unknown", "Execuție întreruptă de restart; fără retrimitere automată.",
                                 ErrorDetail(code="DEVICE_TIMEOUT", message="Este necesară reconcilierea.", retryable=True))
            self.parking.repository.clear_telemetry(connection)
            self.parking.repository.interrupt_telemetry_history(connection)
            return len(rows) + len(prepared)
