"""Direct-unit MODBUS v2.1. Network I/O never runs inside a SQLite transaction."""

import asyncio
import math
import time

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient

from .contracts.firmware import (
    NODE_IDS, NODE_ROLES, SCHEMA_VERSION, CommandObservation, DeviceCommandResult,
    DeviceTelemetry, PassageEvidence, SlotSample, result_for,
)
from .telemetry import unknown_telemetry
from .sequence import resume_candidate


def decode_frame(node, words):
    """Validate the entire latched FC04 response before publishing any field."""
    if len(words) != 37 or any(type(w) is not int or not 0 <= w <= 65535 for w in words):
        raise ValueError("Invalid register frame")
    if words[:3] != [SCHEMA_VERSION, NODE_ROLES[node], NODE_IDS[node]]:
        raise ValueError("Incompatible identity")
    count = {"G": 1, "S1": 4, "S2": 4, "S3": 4, "S4": 4, "S5": 0}[node]
    if words[11] != count or any(words[12 + count:20]) or words[27] or words[26] not in (0, 1):
        raise ValueError("Malformed payload or record")
    payload = words[12:12 + count]
    if node == "G" and (words[10] != 1 or payload[0] > 31):
        raise ValueError("Invalid gateway mask")
    if node in ("S1", "S2"):
        SlotSample.from_internal(header_valid_mask=words[10], payload_valid_mask=payload[2],
                                 occupancy_mask=payload[0], free_count=payload[1])
        if payload[3] > 15:
            raise ValueError("Invalid LED mask")
    if node in ("S3", "S4") and (words[10] != 15 or payload[0] > 4
                                      or payload[1] > 1 or payload[2] > 1 or payload[3] > 3):
        raise ValueError("Invalid barrier payload")
    if node == "S5" and words[10] != 0:
        raise ValueError("Invalid environment mask")
    record = None
    if words[26]:
        if node not in ("S3", "S4") or words[24] not in range(1, 7):
            raise ValueError("Unexpected command record")
        record = DeviceCommandResult.from_internal(
            node_id=node, boot_epoch=words[20] << 16 | words[21],
            command_id=words[22] << 16 | words[23],
            status={1: "accepted", 2: "executing", 3: "done", 4: "rejected", 5: "expired", 6: "failed"}[words[24]],
            result_code=words[25], command_block=words[28:37], evidence="coherent-record", reason="matched")
    elif any(words[20:26]) or any(words[28:]):
        raise ValueError("Absent record must be zero")
    return dict(boot=words[4] << 16 | words[5], sequence=words[6] << 16 | words[7],
                age=words[8] << 16 | words[9], flags=words[3], mask=words[10], payload=payload, record=record)


class ModbusDeviceAdapter:
    def __init__(self, client, *, monotonic=time.monotonic, wall=time.time, request_timeout=0.3, write_guard=None):
        self.client, self.monotonic, self.wall = client, monotonic, wall
        self.request_timeout, self.write_guard = request_timeout, write_guard
        self.lock = asyncio.Lock()
        self.history = {}
        self.candidates = {}
        self.boot_floors = {}
        self.boot_observer = None
        self.persisted_boots = {}

    def set_boot_observer(self, observer):
        self.boot_observer = observer
        self.persisted_boots.clear()

    def seed_boot_floors(self, floors):
        for node, boot in floors.items():
            self.boot_floors[node] = max(boot, self.boot_floors.get(node, 0))

    @classmethod
    def from_settings(cls, settings):
        guard = [0]
        def trace(sending, pdu):
            if sending and pdu.function_code in (6, 16):
                guard[0] += 1
                if guard[0] > 1:
                    raise ConnectionError("Automatic write replay blocked")
            return pdu
        common = dict(timeout=settings.modbus_timeout_seconds, retries=0, reconnect_delay=0, trace_pdu=trace)
        if settings.transport == "TCP":
            client = AsyncModbusTcpClient(settings.modbus_host, port=settings.modbus_port, **common)
        else:
            client = AsyncModbusSerialClient(settings.modbus_serial_port, baudrate=settings.modbus_baudrate,
                                            parity=settings.modbus_parity, stopbits=1, bytesize=8, **common)
        return cls(client, request_timeout=settings.modbus_timeout_seconds, write_guard=guard)

    async def connect(self):
        async with self.lock:
            if not await self.client.connect():
                raise ConnectionError("MODBUS connection unavailable")

    async def close(self):
        async with self.lock:
            self.client.close()
            self._interrupt("G")

    def _interrupt(self, node):
        if node == "G":
            affected = self.candidates.values()
        else:
            affected = [self.candidates.get(node)]
        for candidate in affected:
            if candidate:
                candidate["interrupted"] = True
        for identifier, history in self.history.items():
            if node == "G" or identifier == node:
                history.update(continuous=False, baseline=False)

    async def _call(self, method, *args, **kwargs):
        try:
            if self.write_guard is not None:
                self.write_guard[0] = 0
            async with asyncio.timeout(self.request_timeout * 2 + 0.2):
                if not self.client.connected and not await self.client.connect():
                    raise ConnectionError("MODBUS disconnected")
                response = await getattr(self.client, method)(*args, **kwargs)
            if response.isError():
                raise ConnectionError("MODBUS exception response")
            return response
        except Exception:
            # Discard a possibly late serial/TCP response before another request.
            self.client.close()
            node = next(n for n, unit in NODE_IDS.items() if unit == kwargs["device_id"])
            self._interrupt(node)
            raise

    async def _frame(self, node):
        start = self.monotonic()
        response = await self._call("read_input_registers", 768, count=37, device_id=NODE_IDS[node])
        try:
            frame = decode_frame(node, response.registers)
        except Exception:
            self._interrupt(node)
            raise
        now = self.monotonic()
        frame["received"] = now
        frame["age"] += math.ceil((now - start) * 1000)
        # Identity durability precedes every freshness decision and further I/O.
        # The observer commits separately, after FC04 has finished.
        self.boot_floors[node] = max(frame["boot"], self.boot_floors.get(node, 0))
        if self.boot_observer is not None and frame["boot"] > self.persisted_boots.get(node, -1):
            await self.boot_observer(node, frame["boot"])
            self.persisted_boots[node] = frame["boot"]
        return frame

    def _fresh(self, node, frame, now):
        if frame["boot"] < self.boot_floors.get(node, 0):
            self._interrupt(node)
            return False, frame["age"]
        self.boot_floors[node] = frame["boot"]
        old = self.history.get(node)
        key = (frame["boot"], frame["sequence"])
        payload = (frame["flags"], frame["mask"], frame["payload"])
        age = frame["age"] + math.ceil((now - frame["received"]) * 1000)
        valid = False
        if old and key == old["key"]:
            age = max(age, old["age"] + math.ceil((now - old["at"]) * 1000))
            valid = old["continuous"] and now - old["seen"] < 2 and payload == old["payload"]
            if payload != old["payload"]:
                self._interrupt(node)
            elif age < 2000 and frame["flags"] & 7 == 5:
                # Re-observation may establish a baseline, never prove progress.
                old["baseline"] = True
            if not valid:
                old["continuous"] = False
        else:
            if old:
                boot, sequence = old["key"]
                forward = frame["boot"] > boot or (frame["boot"] == boot and 0 < (frame["sequence"] - sequence) % 2**32 < 2**31)
                temporal = now - old["seen"] < 2 and old["age"] + math.ceil((now-old["at"])*1000) < 2000
                ambiguous_wrap = (forward and frame["boot"] == boot and frame["sequence"] < sequence
                                  and not (old["continuous"] and temporal))
                if ambiguous_wrap:
                    old.update(continuous=False, baseline=False)
                    if age >= 2000 or frame["flags"] & 7 != 5:
                        self._interrupt(node)
                        return False, age
                    candidate, proven = resume_candidate(self.candidates.get(node), boot=boot,
                        sequence=frame["sequence"], age=age, now=now*1000, runtime="adapter",
                        payload=payload, threshold=2000)
                    self.candidates[node] = candidate
                    if not proven:
                        return False, age
                    valid = True
                if not forward:
                    self._interrupt(node)
                    return False, age
                if not ambiguous_wrap:
                    valid = frame["boot"] == boot and old["baseline"] and temporal
            self.candidates.pop(node, None)
            self.history[node] = dict(key=key, age=age, at=now, seen=now, payload=payload,
                                      continuous=valid, baseline=True)
        self.history[node]["seen"] = now
        if age >= 2000 or frame["flags"] & 7 != 5:
            self._interrupt(node)
        return valid and age < 2000 and frame["flags"] & 7 == 5, age

    async def read_telemetry(self):
        async with self.lock:
            frames = {}
            for node in NODE_IDS:
                if node != "G" and ("G" not in frames or not frames["G"]["payload"][0] & (1 << (NODE_IDS[node]-1))):
                    self._interrupt(node)
                    continue
                try:
                    frames[node] = await self._frame(node)
                except Exception:
                    self._interrupt(node)
            data = unknown_telemetry().model_dump(by_alias=True)
            now, wall = self.monotonic(), int(self.wall() * 1000)
            valid = {}
            for station in data["stations"]:
                node = station["id"]
                frame = frames.get(node)
                if frame is None:
                    valid[node] = False
                    continue
                good, age = self._fresh(node, frame, now)
                if node != "G":
                    path = valid.get("G", False) and bool(frames["G"]["payload"][0] & (1 << (NODE_IDS[node] - 1)))
                    good = good and path
                    if not path:
                        self._interrupt(node)
                    age = max(age, data["stations"][0]["ageMs"] or 0)
                valid[node] = good
                if good:
                    station.update(quality="valid", online=True, schemaVersion=SCHEMA_VERSION,
                                   bootEpoch=frame["boot"], sampleSequence=frame["sequence"], ageMs=age, updatedAt=max(0, wall-age))
            stations = {s["id"]: s for s in data["stations"]}
            for slot in data["slots"]:
                node = slot["nodeId"]
                local = (slot["id"] - 1) % 2
                if valid.get(node) and frames[node]["mask"] & (1 << local):
                    slot.update(quality="valid", occupied=bool(frames[node]["payload"][0] & (1 << local)),
                                ageMs=stations[node]["ageMs"], updatedAt=stations[node]["updatedAt"])
            for barrier in data["barriers"]:
                node = barrier["nodeId"]
                if valid.get(node):
                    state, present, obstacle, feedback = frames[node]["payload"]
                    barrier.update(quality="valid", state=["CLOSED", "OPENING", "OPEN", "CLOSING", "FAULT"][state],
                                   vehiclePresent=bool(present), obstacle=bool(obstacle), feedback="estimated" if feedback == 0 else "measured",
                                   ageMs=stations[node]["ageMs"], updatedAt=stations[node]["updatedAt"])
            return DeviceTelemetry.model_validate(data)

    async def _result(self, command):
        try:
            gateway = await self._frame("G")
            gateway_valid, _ = self._fresh("G", gateway, self.monotonic())
            if not gateway_valid or not gateway["payload"][0] & (1 << (NODE_IDS[command.node_id]-1)):
                self._interrupt(command.node_id)
                return result_for(command, None)
            frame = await self._frame(command.node_id)
            now = self.monotonic()
            gateway_valid, _ = self._fresh("G", gateway, now)
            target_valid, _ = self._fresh(command.node_id, frame, now)
            if not gateway_valid or not gateway["payload"][0] & (1 << (NODE_IDS[command.node_id]-1)):
                self._interrupt(command.node_id)
                return result_for(command, None)
            if not target_valid:
                return result_for(command, None)
            return result_for(command, CommandObservation.from_internal(node_id=command.node_id,
                              boot_epoch=frame["boot"], record=frame["record"]))
        except Exception:
            return result_for(command, None)

    async def read_command(self, command):
        async with self.lock:
            return await self._result(command)

    async def submit(self, command):
        async with self.lock:
            try:
                # Revalidate gateway path and target identity immediately before writes.
                gateway = await self._frame("G")
                gateway_valid, _ = self._fresh("G", gateway, self.monotonic())
                if not gateway_valid or not gateway["payload"][0] & (1 << (NODE_IDS[command.node_id]-1)):
                    self._interrupt(command.node_id)
                    return result_for(command, None)
                target = await self._frame(command.node_id)
                now = self.monotonic()
                gateway_valid, _ = self._fresh("G", gateway, now)
                target_valid, _ = self._fresh(command.node_id, target, now)
                if not gateway_valid or not gateway["payload"][0] & (1 << (NODE_IDS[command.node_id]-1)):
                    self._interrupt(command.node_id)
                    return result_for(command, None)
                if (not gateway_valid or not target_valid or target["boot"] != command.expected_boot_epoch
                    or not gateway["payload"][0] & (1 << (NODE_IDS[command.node_id]-1))):
                    return result_for(command, None)
                lease = await self._call("write_register", 4, 1, device_id=NODE_IDS[command.node_id])
                if lease.address != 4 or lease.registers != [1]:
                    raise ValueError("Invalid lease acknowledgement")
                acknowledgement = await self._call("write_registers", 256, command.registers(), device_id=NODE_IDS[command.node_id])
                if acknowledgement.address != 256 or acknowledgement.count != 9:
                    raise ValueError("Invalid command acknowledgement")
            except Exception:
                # Never repeat FC16. A later read may reconcile the exact original block.
                return result_for(command, None)
            return await self._result(command)

    async def read_passage(self, node_id, command_id, boot_epoch):
        return PassageEvidence.from_internal(node_id=node_id, command_id=command_id, boot_epoch=boot_epoch,
            state="unavailable", source="none", evidence_id=None, occurred_at=None, command_block=None)
