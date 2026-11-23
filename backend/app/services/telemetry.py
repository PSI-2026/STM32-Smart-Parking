"""TelemetryService: application operations; repository calls use the caller transaction."""


import json
from pydantic import TypeAdapter
from ..contracts.api import Capacity, Identifier, SlotId
from ..contracts.firmware import DeviceTelemetry
from ..telemetry import age_telemetry, normalize_telemetry
from ..observations import boot_floors, remember_boot

from .common import BusinessFault, canonical


class TelemetryService:
    def __init__(self, parking):
        self.parking = parking

    def record_boot_observation(self, node, boot):
        from ..contracts.firmware import NODE_IDS
        if node not in NODE_IDS or type(boot) is not int or not 0 <= boot <= 0xFFFFFFFF:
            raise ValueError("Invalid device identity")
        with self.parking.db.transaction() as connection:
            remember_boot(connection, node, boot)

    def _current_telemetry(self, connection):
        row = self.parking.repository.cached_telemetry(connection).fetchone()
        if row is None or row["runtime_id"] != self.parking.db.runtime_id:
            return None
        elapsed = self.parking.monotonic_ms() - row["received_mono_ms"]
        if elapsed < 0:
            return None
        data = json.loads(row["payload_json"])
        floors = boot_floors(connection)
        for station in data["stations"]:
            if station["bootEpoch"] is not None and station["bootEpoch"] < floors.get(station["id"], 0):
                station.update(quality="unknown", online=False)
        # Apply the normal path invalidation before this cache is consumed by
        # snapshots, capacity, preparation or dispatch in the same transaction.
        return age_telemetry(data, elapsed)

    def get_telemetry(self):
        with self.parking.db.transaction(write=False) as connection:
            return self.parking._current_telemetry(connection)

    def _store_telemetry(self, connection, telemetry, *, observed_at):
        now = self.parking.monotonic_ms()
        if now < observed_at:
            raise BusinessFault("DATA_UNAVAILABLE", "Ceasul monoton a regresat în timpul validării.")
        telemetry = age_telemetry(telemetry.model_dump(by_alias=True), now - observed_at)
        self.parking.repository.store_telemetry(connection, (
            telemetry.model_dump_json(by_alias=True), self.parking.db.runtime_id, now))
        return telemetry

    def ingest_telemetry(self, telemetry: DeviceTelemetry):
        telemetry = DeviceTelemetry.model_validate(telemetry.model_dump(by_alias=True))
        with self.parking.db.transaction() as connection:
            old = self.parking._current_telemetry(connection)
            observed_at = self.parking.monotonic_ms()
            telemetry = normalize_telemetry(connection, telemetry, runtime_id=self.parking.db.runtime_id, now_ms=observed_at)
            telemetry = self.parking._store_telemetry(connection, telemetry, observed_at=observed_at)
            held = self.parking.repository.held_claim_count(connection).fetchone()[0]
            if held and (old is None or any(
                a.occupied != b.occupied or a.quality != "valid" or b.quality != "valid"
                for a, b in zip(sorted(old.slots, key=lambda x: x.id), sorted(telemetry.slots, key=lambda x: x.id))
            )):
                self.parking.repository.require_reconciliation(connection)

    def _capacity(self, connection, telemetry):
        occupied = (sum(slot.occupied is True for slot in telemetry.slots)
                    if telemetry and all(slot.quality == "valid" for slot in telemetry.slots) else None)
        claims = self.parking.repository.held_claim_count(connection).fetchone()[0]
        reconciliation = self.parking.repository.reconciliation_required(connection).fetchone()[0] == "1"
        reconciliation |= occupied is not None and occupied + claims > 4
        return Capacity.from_internal(physical_occupied=occupied, outstanding_claims=claims,
            available=None if occupied is None or reconciliation else 4 - occupied - claims,
            reconciliation_required=reconciliation)

    def get_capacity(self):
        with self.parking.db.transaction(write=False) as connection:
            return self.parking._capacity(connection, self.parking._current_telemetry(connection))

    def account_occupancy(self, session_id, slot_id, telemetry: DeviceTelemetry, *, evidence_id):
        """Trusted simulator transaction: explicit occupancy event, not inferred plate ID."""
        TypeAdapter(Identifier).validate_python(evidence_id, strict=True)
        TypeAdapter(SlotId).validate_python(slot_id, strict=True)
        if self.parking.mode != "simulation":
            raise BusinessFault("SIMULATION_ONLY", "Contabilizarea simulată nu este permisă în hardware.")
        telemetry = DeviceTelemetry.model_validate(telemetry.model_dump(by_alias=True))
        payload = canonical({"kind": "occupancy", "sessionId": session_id, "slotId": slot_id,
                             "telemetry": telemetry.model_dump(by_alias=True)})
        with self.parking.db.transaction() as connection:
            if self.parking._existing_evidence(connection, evidence_id, payload):
                return False
            session = self.parking._session_row(connection, session_id)
            self.parking._ensure_session_reconciled(connection, session_id)
            claim = self.parking.repository.session_claim(connection, (session_id,)).fetchone()
            old = self.parking._current_telemetry(connection)
            if session["status"] not in ("active", "paid") or claim is None or claim["state"] != "held" or old is None:
                raise BusinessFault("SESSION_CONFLICT", "Nu există o intrare confirmată necontabilizată.")
            binding = self.parking.repository.device_contradiction(connection, (claim["command_id"],)).fetchone()
            if binding is None or binding[0]:
                raise BusinessFault("SESSION_CONFLICT", "Contabilizarea nu poate rezolva o contradicție MCU.")
            observed_at = self.parking.monotonic_ms()
            telemetry = normalize_telemetry(connection, telemetry, runtime_id=self.parking.db.runtime_id, now_ms=observed_at)
            # Save inside this transaction FIRST; rejection below rolls back both
            # the candidate snapshot/history and every business mutation.
            telemetry = self.parking._store_telemetry(connection, telemetry, observed_at=observed_at)
            before = {slot.id: slot for slot in old.slots}
            after = {slot.id: slot for slot in telemetry.slots}
            if slot_id not in before or any(slot.quality != "valid" for slot in [*before.values(), *after.values()]):
                raise BusinessFault("DATA_UNAVAILABLE", "Contabilizarea necesită senzori valizi.")
            if before[slot_id].occupied is not False or after[slot_id].occupied is not True or any(
                before[i].occupied != after[i].occupied for i in before if i != slot_id
            ):
                raise BusinessFault("SESSION_CONFLICT", "Dovada nu reprezintă o singură ocupare corelată.")
            if self.parking.repository.assigned_slot(connection, (slot_id,)).fetchone():
                raise BusinessFault("SESSION_CONFLICT", "Locul este deja asociat unei sesiuni.")
            self.parking.repository.insert_occupancy(connection, (
                evidence_id, claim["command_id"], session_id, payload, self.parking.clock_ms()))
            self.parking.repository.account_claim(connection, (self.parking.clock_ms(), session_id))
            self.parking.repository.assign_slot(connection, (slot_id, session_id))
            # No ambiguity is cleared merely because a matching net count appears.
            self.parking._event(connection, "OCCUPANCY_ACCOUNTED", "Rezervarea a fost transferată către ocuparea confirmată.",
                        command_id=claim["command_id"], session_id=session_id)
            return True

    def account_departure(self, command_id, slot_id, telemetry):
        """Correlated simulator exit; an unrelated held claim is not consumed."""
        if self.parking.mode != "simulation":
            raise BusinessFault("SIMULATION_ONLY", "Eliberarea simulată nu este permisă în hardware.")
        TypeAdapter(SlotId).validate_python(slot_id, strict=True)
        telemetry = DeviceTelemetry.model_validate(telemetry.model_dump(by_alias=True))
        with self.parking.db.transaction() as connection:
            command = self.parking._command(connection, command_id)
            self.parking._ensure_session_reconciled(connection, command["session_id"])
            session = self.parking._session_row(connection, command["session_id"])
            if (json.loads(command["action_json"])["type"] != "exit" or command["status"] != "done"
                    or session["status"] != "completed" or session["slot_id"] != slot_id
                    or not self.parking.repository.has_passage(connection, (command_id,)).fetchone()):
                raise BusinessFault("SESSION_CONFLICT", "Eliberarea nu are o ieșire confirmată asociată.")
            if self.parking.repository.departure_accounted(connection, (command_id,)).fetchone():
                return False
            old = self.parking._current_telemetry(connection)
            observed_at = self.parking.monotonic_ms()
            candidate = normalize_telemetry(connection, telemetry, runtime_id=self.parking.db.runtime_id, now_ms=observed_at)
            candidate = self.parking._store_telemetry(connection, candidate, observed_at=observed_at)
            if old is None or any(slot.quality != "valid" for slot in [*old.slots, *candidate.slots]):
                raise BusinessFault("DATA_UNAVAILABLE", "Eliberarea necesită senzori valizi.")
            before, after = {slot.id: slot for slot in old.slots}, {slot.id: slot for slot in candidate.slots}
            if after[slot_id].occupied is not False or any(before[i].occupied != after[i].occupied for i in before if i != slot_id):
                raise BusinessFault("SESSION_CONFLICT", "Eliberarea modifică alte locuri sau nu confirmă locul liber.")
            self.parking._event(connection, "DEPARTURE_ACCOUNTED", "Senzorul simulat confirmă locul liber după ieșire.",
                        command_id=command_id, session_id=session["id"])
            return True
