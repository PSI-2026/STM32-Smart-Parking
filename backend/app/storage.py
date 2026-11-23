"""SQLite unit of work: one short connection and explicit transaction per call."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


SCHEMA = [
    """CREATE TABLE commands (
        id TEXT PRIMARY KEY, action_json TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('simulation','hardware')),
        status TEXT NOT NULL CHECK(status IN ('accepted','executing','done','rejected','unknown','expired','failed')),
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, message TEXT NOT NULL,
        session_id TEXT REFERENCES sessions(id), error_json TEXT)""",
    """CREATE TABLE sessions (
        id TEXT PRIMARY KEY, plate TEXT NOT NULL, created_at INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending_entry','active','paid','pending_exit','completed','cancelled')),
        slot_id INTEGER CHECK(slot_id BETWEEN 1 AND 4), entered_at INTEGER, exited_at INTEGER, paid_at INTEGER,
        hourly_rate_bani INTEGER NOT NULL CHECK(hourly_rate_bani >= 0))""",
    "CREATE UNIQUE INDEX open_plate ON sessions(plate) WHERE status NOT IN ('completed','cancelled')",
    "CREATE UNIQUE INDEX open_slot ON sessions(slot_id) WHERE status NOT IN ('completed','cancelled')",
    """CREATE TABLE claims (
        session_id TEXT PRIMARY KEY REFERENCES sessions(id), command_id TEXT NOT NULL UNIQUE REFERENCES commands(id),
        state TEXT NOT NULL CHECK(state IN ('held','accounted','released')), updated_at INTEGER NOT NULL)""",
    """CREATE TABLE payments (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
        command_id TEXT NOT NULL UNIQUE REFERENCES commands(id), amount_bani INTEGER NOT NULL CHECK(amount_bani >= 0),
        at INTEGER NOT NULL)""",
    """CREATE TABLE device_commands (
        command_id TEXT PRIMARY KEY REFERENCES commands(id), node_id TEXT NOT NULL, boot_epoch INTEGER NOT NULL,
        device_id INTEGER NOT NULL CHECK(device_id BETWEEN 1 AND 4294967295), block_json TEXT NOT NULL,
        send_state TEXT NOT NULL CHECK(send_state IN ('prepared','sent')), sent_at INTEGER,
        result_json TEXT, progress_seen INTEGER NOT NULL DEFAULT 0 CHECK(progress_seen IN (0,1)),
        UNIQUE(node_id,boot_epoch,device_id))""",
    """CREATE TABLE device_counters (
        node_id TEXT NOT NULL, boot_epoch INTEGER NOT NULL, last_id INTEGER NOT NULL,
        PRIMARY KEY(node_id,boot_epoch))""",
    """CREATE TABLE evidence (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('passage','occupancy')),
        command_id TEXT NOT NULL REFERENCES commands(id), session_id TEXT NOT NULL REFERENCES sessions(id),
        payload_json TEXT NOT NULL, at INTEGER NOT NULL, UNIQUE(kind,command_id))""",
    """CREATE TABLE events (
        id TEXT PRIMARY KEY, at INTEGER NOT NULL, level TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL,
        node_id TEXT, session_id TEXT REFERENCES sessions(id), command_id TEXT REFERENCES commands(id))""",
    "CREATE INDEX events_order ON events(at DESC,id DESC)",
    "CREATE INDEX sessions_order ON sessions(created_at DESC,id DESC)",
    """CREATE TABLE telemetry (
        id INTEGER PRIMARY KEY CHECK(id=1), payload_json TEXT NOT NULL,
        runtime_id TEXT NOT NULL, received_mono_ms INTEGER NOT NULL)""",
    """CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    "INSERT INTO metadata VALUES ('reconciliation_required','0')",
]

MIGRATION_2 = [
    "ALTER TABLE device_commands ADD COLUMN contradiction INTEGER NOT NULL DEFAULT 0 CHECK(contradiction IN (0,1))",
    "ALTER TABLE device_commands ADD COLUMN refusal_seen INTEGER NOT NULL DEFAULT 0 CHECK(refusal_seen IN (0,1))",
    """CREATE TABLE telemetry_history (
        node_id TEXT PRIMARY KEY, boot_epoch INTEGER NOT NULL, sequence INTEGER NOT NULL,
        age_at_anchor INTEGER NOT NULL, anchor_mono_ms INTEGER NOT NULL, runtime_id TEXT NOT NULL,
        continuity INTEGER NOT NULL CHECK(continuity IN (0,1,2)), payload_json TEXT NOT NULL)""",
]


class Database:
    def __init__(self, path: str | Path):
        if str(path) == ":memory:":
            raise ValueError("Use a temporary file: transactions use independent connections")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_id = uuid4().hex
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        finally:
            connection.close()
        with self.transaction() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=1")
                version = 1
            if version == 1:
                for statement in MIGRATION_2:
                    connection.execute(statement)
                for row in connection.execute("SELECT * FROM device_commands").fetchall():
                    result = json.loads(row["result_json"]) if row["result_json"] else None
                    if result and result["status"] == "rejected":
                        connection.execute("UPDATE device_commands SET refusal_seen=1,contradiction=? WHERE command_id=?",
                                           (row["progress_seen"], row["command_id"]))
                        if row["progress_seen"]:
                            connection.execute("UPDATE metadata SET value='1' WHERE key='reconciliation_required'")
                connection.execute("PRAGMA user_version=2")
            elif version != 2:
                raise RuntimeError(f"Unsupported database schema {version}; expected 2")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def transaction(self, *, write: bool = True):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
