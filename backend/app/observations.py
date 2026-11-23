"""Durable identity bounds, independent of sensor freshness or continuity."""

PREFIX = "device_boot_floor:"


def boot_floors(connection):
    floors = {row["node_id"]: row["boot_epoch"] for row in connection.execute(
        "SELECT node_id,boot_epoch FROM telemetry_history")}
    for row in connection.execute("SELECT key,value FROM metadata WHERE key LIKE 'device_boot_floor:%'"):
        node = row["key"][len(PREFIX):]
        floors[node] = max(floors.get(node, 0), int(row["value"]))
    return floors


def remember_boot(connection, node, boot):
    key = PREFIX + node
    old = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    if old is None or int(old["value"]) < boot:
        connection.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, str(boot)))
