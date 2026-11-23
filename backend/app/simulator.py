"""Persistent virtual device adapter and atomic simulator/business coordinator.

All effects are SQLite/CPU-only. No physical I/O occurs in these transactions.
"""

from typing import Annotated, Literal
import logging

from pydantic import Field, model_validator

from .contracts.api import BarrierId, DEVICE_SCHEMA_VERSION, NodeId, WireModel
from .contracts.firmware import DeviceCommand, DeviceCommandResult, DeviceTelemetry, PassageEvidence
from .services.parking import BusinessFault
from .worker import process_batch

NODES = {"G": "gateway", "S1": "slots", "S2": "slots", "S3": "entry", "S4": "exit", "S5": "environment"}
LANES = {"S3": "entry", "S4": "exit"}
logger = logging.getLogger(__name__)


class VirtualBarrier(WireModel):
    state: Literal["CLOSED", "OPENING", "OPEN", "CLOSING", "FAULT"] = "CLOSED"
    obstacle: bool = False
    vehicle_present: bool = False


class VirtualWorld(WireModel):
    occupied: Annotated[list[bool], Field(min_length=4, max_length=4)]
    online: dict[NodeId, bool]
    barriers: dict[BarrierId, VirtualBarrier]
    boot_epoch: Annotated[int, Field(ge=0, le=0xFFFFFFFF)]
    sequence: Annotated[int, Field(ge=0, le=0xFFFFFFFF)]
    transport: Literal["TCP", "USB"]
    last_results: dict[Literal["S3", "S4"], DeviceCommandResult] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fixed_nodes(self):
        if set(self.online) != set(NODES) or set(self.barriers) != {"entry", "exit"}:
            raise ValueError("Incomplete virtual topology")
        return self


class SimulatedDeviceAdapter:
    """Implements DeviceAdapter async methods; sync entry points serve the worker."""

    def __init__(self, service, *, step_delay_ms=200, transport="TCP"):
        if service.mode != "simulation":
            raise ValueError("Simulator cannot attach to a hardware service")
        self.service, self.db = service, service.db
        self.delay, self.initial_transport, self.connected = step_delay_ms, transport, False

    def world(self, connection):
        if not self.connected:
            raise RuntimeError("Simulator adapter is closed")
        row = connection.execute("SELECT payload_json FROM simulator_state WHERE id=1").fetchone()
        if row is None:
            raise RuntimeError("Simulator is not connected")
        return VirtualWorld.model_validate_json(row[0])

    def save(self, connection, world):
        connection.execute("INSERT OR REPLACE INTO simulator_state VALUES (1,?)", (world.model_dump_json(by_alias=True),))
        connection.execute("INSERT OR REPLACE INTO metadata VALUES ('simulation_transport',?)", (world.transport,))

    def open_sync(self):
        if self.connected:
            return
        with self.db.transaction() as connection:
            row = connection.execute("SELECT payload_json FROM simulator_state WHERE id=1").fetchone()
            if row is None and connection.execute("SELECT 1 FROM sessions LIMIT 1").fetchone():
                raise RuntimeError("Simulator state missing for existing sessions; use a separate simulation database")
            world = VirtualWorld.model_validate_json(row[0]) if row else VirtualWorld.from_internal(
                occupied=[False] * 4, online={node: True for node in NODES},
                barriers={lane: VirtualBarrier() for lane in ("entry", "exit")},
                boot_epoch=0, sequence=0, transport=self.initial_transport)
            if world.boot_epoch == 0xFFFFFFFF:
                raise RuntimeError("Simulator boot epoch exhausted")
            for pending in connection.execute("SELECT * FROM simulator_commands WHERE phase IN ('opening','open','closing')").fetchall():
                command = self.service._command(connection, pending["api_command_id"]) if pending["api_command_id"] else None
                lane = LANES[pending["node_id"]]
                settled = pending["phase"] == "closing" and command is not None and command["status"] == "done"
                world.barriers[lane].state = "CLOSED" if settled and not world.barriers[lane].obstacle else "FAULT"
                connection.execute("UPDATE simulator_commands SET phase=? WHERE node_id=? AND boot_epoch=? AND device_id=?",
                                   ("closed" if settled and not world.barriers[lane].obstacle else "lost", pending["node_id"], pending["boot_epoch"], pending["device_id"]))
            world.boot_epoch += 1
            world.sequence = 0
            world.last_results = {}
            self.save(connection, world)
        self.connected = True

    async def connect(self):
        self.open_sync()

    async def close(self):
        self.connected = False

    def sample(self):
        with self.db.transaction() as connection:
            world = self.world(connection)
            world.sequence = (world.sequence + 1) & 0xFFFFFFFF
            self.save(connection, world)
            now = self.service.clock_ms()
            observation = dict(updatedAt=now, ageMs=0)
            stations = []
            for node, role in NODES.items():
                valid = world.online["G"] and world.online[node]
                stations.append(dict(id=node, role=role, online=valid, quality="valid" if valid else "unavailable",
                    schemaVersion=DEVICE_SCHEMA_VERSION if valid else None, bootEpoch=world.boot_epoch if valid else None,
                    sampleSequence=world.sequence if valid else None, **observation))
            slots = []
            for i, occupied in enumerate(world.occupied):
                node = "S1" if i < 2 else "S2"
                valid = world.online["G"] and world.online[node]
                slots.append(dict(id=i + 1, nodeId=node, occupied=occupied if valid else None,
                                  quality="valid" if valid else "unavailable", **observation))
            barriers = []
            for node, lane in LANES.items():
                valid, barrier = world.online["G"] and world.online[node], world.barriers[lane]
                barriers.append(dict(id=lane, nodeId=node, state=barrier.state if valid else "UNKNOWN",
                    obstacle=barrier.obstacle if valid else None, vehiclePresent=barrier.vehicle_present if valid else None,
                    feedback="estimated" if valid else "unknown", quality="valid" if valid else "unavailable", **observation))
            return DeviceTelemetry.model_validate(dict(stations=stations, slots=slots, barriers=barriers))

    async def read_telemetry(self):
        return self.sample()

    def unknown(self, command, reason):
        return DeviceCommandResult.from_internal(node_id=command.node_id, command_id=command.command_id,
            boot_epoch=command.expected_boot_epoch, status="unknown", result_code=None, command_block=None,
            evidence="unproven", reason=reason)

    def result(self, command, status, code):
        return DeviceCommandResult.from_internal(node_id=command.node_id, command_id=command.command_id,
            boot_epoch=command.expected_boot_epoch, status=status, result_code=code, command_block=command.registers(),
            evidence="simulation", reason="matched")

    def submit_sync(self, command: DeviceCommand, *, api_command_id=None):
        command = DeviceCommand.model_validate(command.model_dump(by_alias=True))
        with self.db.transaction() as connection:
            world = self.world(connection)
            if not world.online["G"] or not world.online[command.node_id]:
                return self.unknown(command, "record-unavailable")
            if command.expected_boot_epoch != world.boot_epoch:
                return self.unknown(command, "boot-changed")
            old = connection.execute("SELECT * FROM simulator_commands WHERE node_id=? AND boot_epoch=? AND device_id=?",
                                     (command.node_id, command.expected_boot_epoch, command.command_id)).fetchone()
            if old:
                original = DeviceCommand.model_validate_json(old["command_json"])
                if original.registers() != command.registers():
                    world.last_results[command.node_id] = self.result(command, "rejected", 4)
                    self.save(connection, world)
                    return world.last_results[command.node_id]
                return self.read_command_sync(command)
            previous_id = connection.execute("SELECT MAX(device_id) FROM simulator_commands WHERE node_id=? AND boot_epoch=?",
                                             (command.node_id, command.expected_boot_epoch)).fetchone()[0]
            barrier = world.barriers[LANES[command.node_id]]
            old_id = previous_id is not None and command.command_id <= previous_id
            rejected = barrier.obstacle or barrier.state != "CLOSED" or old_id
            status, code = ("rejected", 2) if rejected else (("done", 1) if command.operation == "reset-fault" else ("accepted", 0))
            if command.operation == "reset-fault" and not barrier.obstacle and not old_id and barrier.state in ("CLOSED", "FAULT"):
                status, code, rejected = "done", 1, False
            phase = "refused" if rejected else ("closed" if command.operation == "reset-fault" else "opening")
            result = self.result(command, status, code)
            connection.execute("INSERT INTO simulator_commands VALUES (?,?,?,?,?,?,NULL,?)", (
                command.node_id, command.expected_boot_epoch, command.command_id, command.model_dump_json(by_alias=True),
                phase, self.service.monotonic_ms() + self.delay, api_command_id))
            if not rejected:
                barrier.state = "CLOSED" if command.operation == "reset-fault" else "OPENING"
                barrier.vehicle_present = command.operation == "open"
            world.last_results[command.node_id] = result
            self.save(connection, world)
            return result

    async def submit(self, command):
        return self.submit_sync(command)

    def read_command_sync(self, command):
        with self.db.transaction(write=False) as connection:
            world = self.world(connection)
            if not world.online["G"] or not world.online[command.node_id]:
                return self.unknown(command, "record-unavailable")
            if world.boot_epoch != command.expected_boot_epoch:
                return self.unknown(command, "boot-changed")
            stored = connection.execute("SELECT phase,command_json FROM simulator_commands WHERE node_id=? AND boot_epoch=? AND device_id=?",
                                        (command.node_id, command.expected_boot_epoch, command.command_id)).fetchone()
            if (stored and stored[0] == "lost"
                    and DeviceCommand.model_validate_json(stored[1]).registers() == command.registers()):
                return self.unknown(command, "record-unavailable")
            result = world.last_results.get(command.node_id)
            if result and result.command_id == command.command_id and result.command_block == command.registers():
                return result
            return self.unknown(command, "record-mismatch")

    async def read_command(self, command):
        return self.read_command_sync(command)

    async def read_passage(self, node_id, command_id, boot_epoch):
        with self.db.transaction(write=False) as connection:
            world = self.world(connection)
            row = connection.execute("SELECT passage_json,phase FROM simulator_commands WHERE node_id=? AND boot_epoch=? AND device_id=?",
                                     (node_id, boot_epoch, command_id)).fetchone()
            if world.boot_epoch == boot_epoch and world.online["G"] and world.online[node_id] and row and row[0]:
                return PassageEvidence.model_validate_json(row[0])
            return PassageEvidence.from_internal(node_id=node_id, command_id=command_id, boot_epoch=boot_epoch,
                state="lost" if world.boot_epoch != boot_epoch or (row and row[1] == "lost") else "unavailable", source="none",
                evidence_id=None, occurred_at=None, command_block=None)


class SimulatorRuntime:
    def __init__(self, service, *, step_delay_ms=200, auto_passage=True, transport="TCP"):
        self.service, self.db, self.auto_passage = service, service.db, auto_passage
        self.adapter = SimulatedDeviceAdapter(service, step_delay_ms=step_delay_ms, transport=transport)

    def connect(self):
        self.adapter.open_sync()
        self.service.simulation_handler = self.apply_demo
        with self.db.transaction():
            self.publish()

    def publish(self):
        # Actual virtual acquisitions establish gateway/station progress.
        for _ in range(3):
            self.service.ingest_telemetry(self.adapter.sample())

    def apply_demo(self, connection, command, action):
        world, kind = self.adapter.world(connection), action["type"]
        if kind == "set-slot-sensor":
            world.occupied[action["slotId"] - 1] = action["occupied"]
        elif kind == "set-all-slot-sensors":
            world.occupied = [action["occupied"]] * 4
        elif kind == "set-node-online":
            world.online[action["nodeId"]] = action["online"]
        elif kind == "set-obstacle":
            world.barriers[action["barrierId"]].obstacle = action["active"]
        elif kind == "set-barrier-presence":
            world.barriers[action["barrierId"]].vehicle_present = action["present"]
        elif kind == "set-transport":
            world.transport = action["transport"]
        else:
            raise BusinessFault("VALIDATION_ERROR", "Acțiune de simulator necunoscută.")
        self.adapter.save(connection, world)
        if kind == "set-node-online" and not action["online"]:
            # Capture the loss at its linearization point, not at the end of
            # the batch: an immediate reconnect cannot undo an interrupted access.
            for pending in connection.execute("SELECT * FROM simulator_commands WHERE phase IN ('opening','open')").fetchall():
                if action["nodeId"] in ("G", pending["node_id"]):
                    self.abandon(connection, pending)
        self.publish()
        self.service._transition(connection, command, "done", "Starea simulatorului a fost actualizată.")

    def cycle(self, retry_after=None, should_stop=lambda: False):
        with self.db.transaction() as connection:
            self.publish()
            process_batch(self.service, retry_after, should_stop)
            if should_stop():
                return
            pending = connection.execute("""SELECT c.id FROM commands c JOIN device_commands d ON d.command_id=c.id
                WHERE c.status='executing' AND d.send_state='prepared' ORDER BY c.created_at,c.id""").fetchall()
            for row in pending:
                device = self.service.claim_dispatch(row[0])
                if device:
                    result = self.adapter.submit_sync(device, api_command_id=row[0])
                    self.service.record_device_result(row[0], result)
            self.advance(connection)
            self.publish()

    def advance(self, connection):
        rows = connection.execute("SELECT * FROM simulator_commands WHERE phase IN ('opening','open','closing')").fetchall()
        for row in rows:
            try:
                # Roll back one virtual access, not successful independent work.
                with self.db.transaction() as access:
                    self._advance_rows(access, [row])
            except Exception:
                logger.exception("Virtual access failed: %s/%s/%s", row["node_id"], row["boot_epoch"], row["device_id"])
                self.abandon(connection, row, reason="incoherent")

    def abandon(self, connection, row, *, reason="record-unavailable"):
        device = DeviceCommand.model_validate_json(row["command_json"])
        world = self.adapter.world(connection)
        key = (device.node_id, device.expected_boot_epoch, device.command_id)
        connection.execute("UPDATE simulator_commands SET phase='lost' WHERE node_id=? AND boot_epoch=? AND device_id=?", key)
        world.barriers[LANES[device.node_id]].state = "FAULT"
        previous = world.last_results.get(device.node_id)
        if previous and previous.command_block == device.registers():
            world.last_results[device.node_id] = self.adapter.unknown(device, reason)
        self.adapter.save(connection, world)
        if row["api_command_id"]:
            self.service.record_device_result(row["api_command_id"], self.adapter.unknown(device, reason))

    def _advance_rows(self, connection, rows):
        now = self.service.monotonic_ms()
        for row in rows:
            device = DeviceCommand.model_validate_json(row["command_json"])
            world, lane = self.adapter.world(connection), LANES[device.node_id]
            barrier = world.barriers[lane]
            key = (device.node_id, device.expected_boot_epoch, device.command_id)
            api = self.service._command(connection, row["api_command_id"]) if row["api_command_id"] else None
            if api and row["phase"] != "closing":
                try:
                    self.service._ensure_session_reconciled(connection, api["session_id"])
                except BusinessFault:
                    self.abandon(connection, row, reason="incoherent")
                    continue
            if not world.online["G"] or not world.online[device.node_id]:
                if row["phase"] != "closing" or api is None or api["status"] != "done":
                    self.abandon(connection, row)
                    continue
            if now < row["deadline_ms"] or barrier.obstacle:
                continue
            if row["phase"] == "opening":
                barrier.state, phase = "OPEN", "open"
            elif row["phase"] == "closing":
                barrier.state, phase = "CLOSED", "closed"
            else:
                if not self.auto_passage or api is None:
                    continue
                observed = self.adapter.read_command_sync(device)
                if observed.status not in ("accepted", "executing", "done"):
                    if api["status"] != "unknown":
                        self.service.record_device_result(api["id"], observed)
                    continue
                telemetry = self.service.get_telemetry()
                if telemetry is None or any(slot.quality != "valid" for slot in telemetry.slots):
                    continue
                session = self.service._session_row(connection, api["session_id"])
                if lane == "entry":
                    assigned = {r[0] for r in connection.execute("SELECT slot_id FROM sessions WHERE slot_id IS NOT NULL AND status NOT IN ('completed','cancelled')")}
                    slot = next((i + 1 for i, occupied in enumerate(world.occupied) if not occupied and i + 1 not in assigned), None)
                    if slot is None:
                        continue
                else:
                    slot = session["slot_id"]
                proof = PassageEvidence.from_internal(node_id=device.node_id, command_id=device.command_id,
                    boot_epoch=device.expected_boot_epoch, state="confirmed", source="simulation",
                    evidence_id=f"sim-{device.node_id}-{device.expected_boot_epoch}-{device.command_id}",
                    occurred_at=self.service.clock_ms(), command_block=device.registers())
                result = self.adapter.result(device, "done", 1)
                last = world.last_results.get(device.node_id)
                if last and last.command_block == device.registers():
                    world.last_results[device.node_id] = result
                barrier.state, barrier.vehicle_present = "CLOSING", False
                if slot is not None:
                    world.occupied[slot - 1] = lane == "entry"
                self.adapter.save(connection, world)
                self.service.record_device_result(api["id"], self.adapter.read_command_sync(device))
                self.service.consume_passage(api["id"], proof)
                if lane == "entry":
                    self.service.account_occupancy(session["id"], slot, self.adapter.sample(), evidence_id=f"park-{proof.evidence_id}")
                elif slot is not None:
                    self.service.account_departure(api["id"], slot, self.adapter.sample())
                connection.execute("UPDATE simulator_commands SET passage_json=? WHERE node_id=? AND boot_epoch=? AND device_id=?",
                                   (proof.model_dump_json(by_alias=True), *key))
                world = self.adapter.world(connection)  # sampling above advanced its sequence
                phase = "closing"
            self.adapter.save(connection, world)
            connection.execute("UPDATE simulator_commands SET phase=?,deadline_ms=? WHERE node_id=? AND boot_epoch=? AND device_id=?",
                               (phase, now + self.adapter.delay, *key))
