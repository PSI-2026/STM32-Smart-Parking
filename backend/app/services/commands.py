"""CommandService: application operations; repository calls use the caller transaction."""


import json
from ..contracts.api import CommandRequest, CommandResult, ErrorDetail
from ..contracts.firmware import DeviceCommand

from .common import Admission, BusinessFault, canonical


class CommandService:
    def __init__(self, parking):
        self.parking = parking

    def _command(self, connection, command_id):
        row = self.parking.repository.command(connection, (command_id,)).fetchone()
        if row is None:
            raise BusinessFault("NOT_FOUND", "Comanda nu există.")
        return row

    def _result(self, row):
        return CommandResult.from_internal(command_id=row["id"], status=row["status"], message=row["message"],
            created_at=row["created_at"], updated_at=row["updated_at"], session_id=row["session_id"],
            error=ErrorDetail.model_validate_json(row["error_json"]) if row["error_json"] else None)

    def _transition(self, connection, row, status, message, error=None):
        self.parking.repository.transition_command(connection, (
            status, message, max(self.parking.clock_ms(), row["updated_at"]),
            error.model_dump_json(by_alias=True) if error else None, row["id"]))
        self.parking._event(connection, f"COMMAND_{status.upper()}", message, command_id=row["id"],
                    session_id=row["session_id"], level="warning" if error else "info")

    def admit(self, request: CommandRequest) -> Admission:
        request = CommandRequest.model_validate(request.model_dump(by_alias=True))
        action = request.action.model_dump(by_alias=True)
        if action["type"] == "enter":
            action["plate"] = " ".join(action["plate"].split()).upper()
            if not action["plate"] or len(action["plate"]) > 20:
                raise BusinessFault("VALIDATION_ERROR", "Număr de înmatriculare invalid după normalizare.")
        payload = canonical(action)
        with self.parking.db.transaction() as connection:
            row = self.parking.repository.command(connection, (request.command_id,)).fetchone()
            if row:
                if row["action_json"] != payload:
                    raise BusinessFault("IDEMPOTENCY_CONFLICT", "ID-ul comenzii identifică altă acțiune.")
                return Admission(self.parking._result(row), True)
            now = self.parking.clock_ms()
            self.parking.repository.insert_command(connection, (request.command_id, payload, self.parking.mode, now, now, "Comanda a fost înregistrată."))
            self.parking._event(connection, "COMMAND_ACCEPTED", "Comanda a fost înregistrată.", command_id=request.command_id)
            return Admission(self.parking._result(self.parking._command(connection, request.command_id)), False)

    def get_command(self, command_id) -> CommandResult:
        with self.parking.db.transaction(write=False) as connection:
            return self.parking._result(self.parking._command(connection, command_id))

    def get_device_command(self, command_id) -> DeviceCommand | None:
        with self.parking.db.transaction(write=False) as connection:
            self.parking._command(connection, command_id)
            row = self.parking.repository.device_block(connection, (command_id,)).fetchone()
            return DeviceCommand.model_validate_json(row[0]) if row else None

    def recent_commands(self, *, limit=50):
        self.parking._pagination(limit, None)
        with self.parking.db.transaction(write=False) as connection:
            return [self.parking._result(row) for row in self.parking.repository.recent_commands(connection, (limit,))]

    def process(self, command_id) -> CommandResult:
        """Persist business effects/prepared device command; never perform I/O here."""
        with self.parking.db.transaction() as connection:
            row = self.parking._command(connection, command_id)
            if row["status"] != "accepted":
                return self.parking._result(row)
            action = json.loads(row["action_json"])
            # Business failures are results, not rolled-back command admission.
            connection.execute("SAVEPOINT business")
            try:
                if action["type"] == "pay":
                    self.parking._pay(connection, row, action["sessionId"])
                elif action["type"] in ("enter", "exit"):
                    self.parking._prepare_access(connection, row, action)
                elif self.parking.mode == "hardware":
                    raise BusinessFault("SIMULATION_ONLY", "Acțiunea este rezervată simulării.")
                elif self.parking.simulation_handler is not None:
                    self.parking.simulation_handler(connection, row, action)
                else:
                    raise NotImplementedError("Demo actions are delegated to the simulator in step 5")
            except BusinessFault as failure:
                connection.execute("ROLLBACK TO business")
                self.parking._transition(connection, row, "rejected", str(failure), failure.detail)
            finally:
                connection.execute("RELEASE business")
            return self.parking._result(self.parking._command(connection, command_id))

    def pending_commands(self):
        with self.parking.db.transaction(write=False) as connection:
            return [row[0] for row in self.parking.repository.pending_commands(connection)]

    def processable_commands(self, *, limit=50, excluded=frozenset(), ordered_ids=None):
        self.parking._pagination(limit, None)
        with self.parking.db.transaction(write=False) as connection:
            commands = []
            rows = (self.parking.repository.accepted_command(connection, (identifier,)).fetchone()
                    for identifier in ordered_ids) if ordered_ids is not None else self.parking.repository.accepted_commands(connection)
            for row in rows:
                if row is not None and row["id"] not in excluded and (self.parking.mode == "hardware" or self.parking.simulation_handler is not None or json.loads(row["action_json"])["type"] in ("enter", "pay", "exit")):
                    commands.append(row["id"])
                    if len(commands) == limit:
                        break
            return commands
