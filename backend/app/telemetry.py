"""Monotonic per-node history survives unavailable public snapshots.

continuity: 0 interrupted, 1 baseline awaiting forward progress, 2 observed
progress with no ambiguous gap. Never use a public snapshot as this history.
"""

import json

from .contracts.firmware import DeviceTelemetry


def unknown_telemetry():
    observation = dict(quality="unknown", updatedAt=None, ageMs=None)
    return DeviceTelemetry.model_validate({
        "stations": [dict(id=node, role=role, online=False, schemaVersion=None, bootEpoch=None,
                          sampleSequence=None, **observation)
                     for node, role in zip(["G", "S1", "S2", "S3", "S4", "S5"],
                                          ["gateway", "slots", "slots", "entry", "exit", "environment"])],
        "slots": [dict(id=i, nodeId="S1" if i <= 2 else "S2", occupied=None, **observation) for i in range(1, 5)],
        "barriers": [dict(id=lane, nodeId=node, state="UNKNOWN", obstacle=None, vehiclePresent=None,
                          feedback="unknown", **observation) for lane, node in [("entry", "S3"), ("exit", "S4")]],
    })


def age_telemetry(data, elapsed):
    threshold = data["staleAfterMs"]
    for item in [*data["stations"], *data["slots"], *data["barriers"]]:
        if item["ageMs"] is not None:
            item["ageMs"] += elapsed
        if item["quality"] == "valid" and item["ageMs"] >= threshold:
            item["quality"] = "stale"
    stations = {station["id"]: station for station in data["stations"]}
    gateway_valid = stations["G"]["quality"] == "valid"
    for station in data["stations"]:
        if station["id"] != "G" and not gateway_valid and station["quality"] == "valid":
            station["quality"], station["online"] = "unavailable", False
    for item in [*data["slots"], *data["barriers"]]:
        if not gateway_valid or stations[item["nodeId"]]["quality"] != "valid":
            if item["quality"] == "valid":
                item["quality"] = "unavailable"
        if item["quality"] != "valid":
            if "occupied" in item:
                item["occupied"] = None
            else:
                item.update(state="UNKNOWN", obstacle=None, vehiclePresent=None, feedback="unknown")
    return DeviceTelemetry.model_validate(data)


def normalize_telemetry(connection, telemetry, *, runtime_id, now_ms):
    """Normalize candidate AND persist its history in the caller's transaction."""
    data = telemetry.model_dump(by_alias=True)
    threshold = data["staleAfterMs"]
    for station in data["stations"]:
        node = station["id"]
        old = connection.execute("SELECT * FROM telemetry_history WHERE node_id=?", (node,)).fetchone()
        if station["quality"] != "valid":
            if old:
                connection.execute("UPDATE telemetry_history SET continuity=0 WHERE node_id=?", (node,))
            continue
        # Only physical fields: timestamps/age/connection metadata may change.
        payload = []
        for item in sorted([*data["slots"], *data["barriers"]], key=lambda x: str(x["id"])):
            if item["nodeId"] == node:
                fields = ("occupied", "quality") if "occupied" in item else ("state", "obstacle", "vehiclePresent", "feedback", "quality")
                payload.append({key: item[key] for key in fields})
        signature = json.dumps(payload, sort_keys=True)
        boot, sequence = station["bootEpoch"], station["sampleSequence"]
        age, continuity = station["ageMs"], 1
        reject = False
        if old:
            same_runtime = old["runtime_id"] == runtime_id
            elapsed = now_ms - old["anchor_mono_ms"] if same_runtime else None
            old_age = old["age_at_anchor"] + max(0, elapsed or 0)
            continuous = same_runtime and elapsed >= 0 and old["continuity"] == 2 and old_age < threshold
            if boot < old["boot_epoch"]:
                reject = True  # boot epochs do not automatically wrap
            elif boot == old["boot_epoch"]:
                delta = (sequence - old["sequence"]) & 0xFFFFFFFF
                if delta >= 0x80000000 or (sequence < old["sequence"] and not continuous):
                    reject = True
                elif delta == 0:
                    reject = signature != old["payload_json"]
                    age = max(age, old_age)
                    continuity = 2 if continuous else 1
                else:
                    # An interruption needs a baseline, then a further advance.
                    proven_baseline = (same_runtime and elapsed >= 0 and old["continuity"] == 1
                                       and old_age < threshold)
                    continuity = 2 if continuous or proven_baseline else 1
        if reject:
            connection.execute("UPDATE telemetry_history SET continuity=0 WHERE node_id=?", (node,))
            station["quality"] = "unknown"
            continue  # preserve highest accepted identity and its age anchor
        connection.execute("INSERT OR REPLACE INTO telemetry_history VALUES (?,?,?,?,?,?,?,?)", (
            node, boot, sequence, age, now_ms, runtime_id, continuity, signature))
        station["ageMs"] = age
        if age >= threshold:
            station["quality"] = "stale"
        elif continuity != 2:
            station["quality"] = "unknown"
    stations = {station["id"]: station for station in data["stations"]}
    if stations["G"]["quality"] != "valid":
        connection.execute("UPDATE telemetry_history SET continuity=0 WHERE node_id!='G'")
    for item in [*data["slots"], *data["barriers"]]:
        if item["ageMs"] is not None:
            for source in (stations[item["nodeId"]], stations["G"]):
                if source["ageMs"] is not None:
                    item["ageMs"] = max(item["ageMs"], source["ageMs"])
    return age_telemetry(data, 0)
