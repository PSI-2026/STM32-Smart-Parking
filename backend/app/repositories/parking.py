"""Named SQLite operations; caller owns connection, savepoints and atomic commit."""

class ParkingRepository:
    def hardware_profile(self, connection):
        return connection.execute("SELECT value FROM metadata WHERE key='hardware_profile'").fetchone()

    def bind_hardware_profile(self, connection, profile):
        connection.execute("INSERT OR IGNORE INTO metadata VALUES ('hardware_profile',?)", (profile,))

    def has_parking_state(self, connection):
        return bool(connection.execute("SELECT EXISTS(SELECT 1 FROM commands) OR EXISTS(SELECT 1 FROM sessions) OR EXISTS(SELECT 1 FROM telemetry)").fetchone()[0])

    def mode(self, connection, parameters=()):
        return connection.execute("SELECT value FROM metadata WHERE key='mode'", parameters)

    def ensure_mode(self, connection, parameters=()):
        return connection.execute("INSERT OR IGNORE INTO metadata VALUES ('mode',?)", parameters)

    def command(self, connection, parameters=()):
        return connection.execute('SELECT * FROM commands WHERE id=?', parameters)

    def insert_event(self, connection, parameters=()):
        return connection.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)', parameters)

    def transition_command(self, connection, parameters=()):
        return connection.execute('UPDATE commands SET status=?,message=?,updated_at=?,error_json=? WHERE id=?', parameters)

    def insert_command(self, connection, parameters=()):
        return connection.execute("INSERT INTO commands (id,action_json,mode,status,created_at,updated_at,message) VALUES (?,?,?,'accepted',?,?,?)", parameters)

    def device_block(self, connection, parameters=()):
        return connection.execute('SELECT block_json FROM device_commands WHERE command_id=?', parameters)

    def recent_commands(self, connection, parameters=()):
        return connection.execute('SELECT * FROM commands ORDER BY created_at DESC,id DESC LIMIT ?', parameters)

    def cached_telemetry(self, connection, parameters=()):
        return connection.execute('SELECT * FROM telemetry WHERE id=1', parameters)

    def store_telemetry(self, connection, parameters=()):
        return connection.execute('INSERT OR REPLACE INTO telemetry VALUES (1,?,?,?)', parameters)

    def held_claim_count(self, connection, parameters=()):
        return connection.execute("SELECT COUNT(*) FROM claims WHERE state='held'", parameters)

    def require_reconciliation(self, connection, parameters=()):
        return connection.execute("UPDATE metadata SET value='1' WHERE key='reconciliation_required'", parameters)

    def reconciliation_required(self, connection, parameters=()):
        return connection.execute("SELECT value FROM metadata WHERE key='reconciliation_required'", parameters)

    def session(self, connection, parameters=()):
        return connection.execute('SELECT * FROM sessions WHERE id=?', parameters)

    def paid_total(self, connection, parameters=()):
        return connection.execute('SELECT COALESCE(SUM(amount_bani),0) FROM payments WHERE session_id=?', parameters)

    def open_sessions(self, connection, parameters=()):
        return connection.execute("SELECT * FROM sessions WHERE status NOT IN ('completed','cancelled') ORDER BY created_at DESC,id DESC", parameters)

    def insert_payment(self, connection, parameters=()):
        return connection.execute('INSERT INTO payments VALUES (?,?,?,?,?)', parameters)

    def mark_session_paid(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET paid_at=?,status='paid' WHERE id=?", parameters)

    def bind_command_session(self, connection, parameters=()):
        return connection.execute('UPDATE commands SET session_id=? WHERE id=?', parameters)

    def session_contradiction(self, connection, parameters=()):
        return connection.execute('SELECT 1 FROM device_commands d JOIN commands c ON c.id=d.command_id WHERE c.session_id=? AND d.contradiction=1', parameters)

    def barrier_busy(self, connection, parameters=()):
        return connection.execute("SELECT 1 FROM device_commands d JOIN commands c ON c.id=d.command_id WHERE d.node_id=? AND c.status IN ('executing','unknown')", parameters)

    def open_plate(self, connection, parameters=()):
        return connection.execute("SELECT 1 FROM sessions WHERE plate=? AND status NOT IN ('completed','cancelled')", parameters)

    def insert_session(self, connection, parameters=()):
        return connection.execute("INSERT INTO sessions (id,plate,created_at,status,hourly_rate_bani) VALUES (?,?,?,'pending_entry',?)", parameters)

    def insert_claim(self, connection, parameters=()):
        return connection.execute("INSERT INTO claims VALUES (?,?,'held',?)", parameters)

    def prepare_exit(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='pending_exit' WHERE id=?", parameters)

    def device_counter(self, connection, parameters=()):
        return connection.execute('SELECT last_id FROM device_counters WHERE node_id=? AND boot_epoch=?', parameters)

    def save_device_counter(self, connection, parameters=()):
        return connection.execute('INSERT OR REPLACE INTO device_counters VALUES (?,?,?)', parameters)

    def prepare_device_command(self, connection, parameters=()):
        return connection.execute("INSERT INTO device_commands (command_id,node_id,boot_epoch,device_id,block_json,send_state) VALUES (?,?,?,?,?,'prepared')", parameters)

    def device_binding(self, connection, parameters=()):
        return connection.execute('SELECT * FROM device_commands WHERE command_id=?', parameters)

    def mark_device_sent(self, connection, parameters=()):
        return connection.execute("UPDATE device_commands SET send_state='sent',sent_at=? WHERE command_id=?", parameters)

    def update_device_flags(self, connection, parameters=()):
        return connection.execute('UPDATE device_commands SET progress_seen=MAX(progress_seen,?), refusal_seen=MAX(refusal_seen,?),contradiction=MAX(contradiction,?) WHERE command_id=?', parameters)

    def save_device_result(self, connection, parameters=()):
        return connection.execute('UPDATE device_commands SET result_json=? WHERE command_id=?', parameters)

    def cancel_session(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='cancelled' WHERE id=?", parameters)

    def release_claim(self, connection, parameters=()):
        return connection.execute("UPDATE claims SET state='released',updated_at=? WHERE session_id=?", parameters)

    def restore_paid(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='paid' WHERE id=?", parameters)

    def evidence(self, connection, parameters=()):
        return connection.execute('SELECT payload_json FROM evidence WHERE id=?', parameters)

    def insert_passage(self, connection, parameters=()):
        return connection.execute("INSERT INTO evidence VALUES (?,'passage',?,?,?,?)", parameters)

    def activate_session(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='active',entered_at=? WHERE id=?", parameters)

    def complete_session(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='completed',exited_at=? WHERE id=?", parameters)

    def release_held_claim(self, connection, parameters=()):
        return connection.execute("UPDATE claims SET state='released',updated_at=? WHERE session_id=? AND state='held'", parameters)

    def session_claim(self, connection, parameters=()):
        return connection.execute('SELECT * FROM claims WHERE session_id=?', parameters)

    def device_contradiction(self, connection, parameters=()):
        return connection.execute('SELECT contradiction FROM device_commands WHERE command_id=?', parameters)

    def assigned_slot(self, connection, parameters=()):
        return connection.execute("SELECT 1 FROM sessions WHERE slot_id=? AND status NOT IN ('completed','cancelled')", parameters)

    def insert_occupancy(self, connection, parameters=()):
        return connection.execute("INSERT INTO evidence VALUES (?,'occupancy',?,?,?,?)", parameters)

    def account_claim(self, connection, parameters=()):
        return connection.execute("UPDATE claims SET state='accounted',updated_at=? WHERE session_id=?", parameters)

    def assign_slot(self, connection, parameters=()):
        return connection.execute('UPDATE sessions SET slot_id=? WHERE id=?', parameters)

    def prepared_commands(self, connection, parameters=()):
        return connection.execute("SELECT c.* FROM commands c JOIN device_commands d ON d.command_id=c.id WHERE d.send_state='prepared' AND c.status IN ('executing','unknown')", parameters)

    def cancel_pending_entry(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='cancelled' WHERE id=? AND status='pending_entry'", parameters)

    def restore_pending_exit(self, connection, parameters=()):
        return connection.execute("UPDATE sessions SET status='paid' WHERE id=? AND status='pending_exit'", parameters)

    def executing_commands(self, connection, parameters=()):
        return connection.execute("SELECT * FROM commands WHERE status='executing'", parameters)

    def clear_telemetry(self, connection, parameters=()):
        return connection.execute('DELETE FROM telemetry', parameters)

    def interrupt_telemetry_history(self, connection, parameters=()):
        return connection.execute('UPDATE telemetry_history SET continuity=0', parameters)

    def has_passage(self, connection, parameters=()):
        return connection.execute("SELECT 1 FROM evidence WHERE command_id=? AND kind='passage'", parameters)

    def departure_accounted(self, connection, parameters=()):
        return connection.execute("SELECT 1 FROM events WHERE command_id=? AND code='DEPARTURE_ACCOUNTED'", parameters)

    def pending_commands(self, connection, parameters=()):
        return connection.execute("SELECT id FROM commands WHERE status='accepted' ORDER BY created_at,id", parameters)

    def accepted_command(self, connection, parameters=()):
        return connection.execute("SELECT id,action_json FROM commands WHERE id=? AND status='accepted'", parameters)

    def accepted_commands(self, connection, parameters=()):
        return connection.execute("SELECT id,action_json FROM commands WHERE status='accepted' ORDER BY created_at,id", parameters)

    def simulation_transport(self, connection, parameters=()):
        return connection.execute("SELECT value FROM metadata WHERE key='simulation_transport'", parameters)

    def recent_events(self, connection, parameters=()):
        return connection.execute('SELECT * FROM events ORDER BY at DESC,id DESC LIMIT 50', parameters)

    def latest_commands(self, connection, parameters=()):
        return connection.execute('SELECT * FROM commands ORDER BY created_at DESC,id DESC LIMIT 50', parameters)

    def page_rows(self, connection, table, time_column, anchor, limit):
        if (table, time_column) not in (("sessions", "created_at"), ("events", "at")):
            raise ValueError("Unsupported page source")
        where = f"WHERE ({time_column},id) < (?,?)" if anchor else ""
        return connection.execute(f"SELECT * FROM {table} {where} ORDER BY {time_column} DESC,id DESC LIMIT ?",
            (*anchor, limit + 1) if anchor else (limit + 1,)).fetchall()
