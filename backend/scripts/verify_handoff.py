"""Reproducible real-HTTP acceptance run, using temporary simulation databases.

No running server, shared database, credentials or physical adapter is used.
Run: python backend/scripts/verify_handoff.py [--report report.json]
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from app.contracts.api import CommandResult, ParkingSnapshot
from app.settings import Settings


class Acceptance:
    def __init__(self):
        self.admin, self.operator, self.viewer = (secrets.token_urlsafe(32) for _ in range(3))
        self.base = ""
        self.results = []

    def record(self, name, **evidence):
        self.results.append({"scenario": name, "passed": True, **evidence})
        print(f"PASS {name}", flush=True)

    @contextmanager
    def server(self, database, *, auto_passage=True):
        from app.main import create_app
        settings = Settings(database_path=database, mode="simulation", hardware_enabled=False,
            allow_anonymous_simulation=False, viewer_token=self.viewer, operator_token=self.operator,
            admin_token=self.admin, worker_enabled=True, simulator_enabled=True,
            simulator_auto_passage=auto_passage, simulator_step_delay_ms=50,
            worker_interval_seconds=0.05, hourly_rate_bani=500)
        app = create_app(settings)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        address, port = listener.getsockname()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        self.base = f"http://{address}:{port}/api/v1"
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Temporary API did not start")
                time.sleep(0.01)
            yield
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            if thread.is_alive():
                raise RuntimeError("Temporary API did not stop")

    def request(self, path, *, body=None, role="operator", expected=200):
        headers = {"Accept": "application/json"}
        if role:
            headers["Authorization"] = "Bearer " + getattr(self, role)
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            data = json.load(response)
            if response.status != expected:
                raise AssertionError(f"{path}: expected HTTP {expected}, got {response.status}")
        return data

    def snapshot(self):
        return ParkingSnapshot.model_validate(self.request("/snapshot"))

    def wait(self, read, predicate, *, timeout=10):
        deadline = time.monotonic() + timeout
        while True:
            value = read()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise TimeoutError("Acceptance condition was not reached")
            time.sleep(0.05)

    def submit(self, identifier, action, *, replay=False, role="operator"):
        result = self.request("/commands", body={"commandId": identifier, "action": action},
                              role=role, expected=200 if replay else 202)
        result = CommandResult.model_validate(result)
        if result.command_id != identifier:
            raise AssertionError("Uncorrelated admission")
        return result

    def command(self, identifier):
        return CommandResult.model_validate(self.request("/commands/" + identifier))

    def execute(self, identifier, action, *, role="operator"):
        self.submit(identifier, action, role=role)
        return self.wait(lambda: self.command(identifier), lambda value: value.status not in ("accepted", "executing"))

    def closed(self, lane):
        self.wait(self.snapshot, lambda value: next(b for b in value.barriers if b.id == lane).state == "CLOSED")

    @staticmethod
    def done(result):
        if result.status != "done":
            raise AssertionError(f"Expected done, got {result.status}")
        return result

    def settle_exit(self, session, prefix):
        self.done(self.execute(prefix + "-pay", {"type": "pay", "sessionId": session}))
        self.closed("exit")
        self.done(self.execute(prefix + "-exit", {"type": "exit", "sessionId": session}))
        self.closed("exit")

    def run(self, directory):
        database = directory / "parking.sqlite3"
        with self.server(database):
            assert self.request("/health", role=None)["status"] == "healthy"
            denied = {"commandId": "access-denied", "action": {"type": "pay", "sessionId": "missing"}}
            assert self.request("/commands", body=denied, role=None, expected=401)["error"]["code"] == "UNAUTHORIZED"
            assert self.request("/commands", body=denied, role="viewer", expected=403)["error"]["code"] == "FORBIDDEN"
            self.request("/commands/access-denied", expected=404)
            self.record("authentication-before-admission", anonymous=401, viewer_write=403, command_absent=True)
            self.wait(self.snapshot, lambda value: value.capacity.available == 4)

            entry = self.done(self.execute("entry", {"type": "enter", "plate": "B 101 DEM"}))
            session = entry.session_id
            unpaid = self.execute("exit-unpaid", {"type": "exit", "sessionId": session})
            assert unpaid.status == "rejected" and unpaid.error.code == "PAYMENT_REQUIRED"
            payment = {"type": "pay", "sessionId": session}
            self.done(self.execute("pay", payment))
            amount = self.request("/sessions/" + session)["paidBani"]
            self.done(self.submit("pay", payment, replay=True))
            self.done(self.execute("pay-again", payment))
            assert self.request("/sessions/" + session)["paidBani"] == amount
            assert self.submit("exit-unpaid", {"type": "exit", "sessionId": session}, replay=True).status == "rejected"
            self.closed("exit")
            self.done(self.execute("exit", {"type": "exit", "sessionId": session}))
            assert self.request("/sessions/" + session)["status"] == "completed"
            self.wait(self.snapshot, lambda value: value.capacity.available == 4)
            self.record("entry-payment-exit-and-replay", unpaid_exit="rejected", payment_replay=200,
                        repeated_payment_bani=amount, final_capacity=4)

            self.closed("entry")
            with ThreadPoolExecutor(max_workers=2) as executor:
                admitted = list(executor.map(lambda i: self.submit(f"parallel-{i}", {
                    "type": "enter", "plate": f"B 20{i} DEM"}), (1, 2)))
            results = [self.wait(lambda identifier=item.command_id: self.command(identifier),
                       lambda value: value.status not in ("accepted", "executing")) for item in admitted]
            assert all(item.status in ("done", "rejected") for item in results)
            snapshot = self.snapshot()
            assert snapshot.capacity.available is not None and 0 <= snapshot.capacity.available <= 4
            for index, item in enumerate(results):
                if item.status == "done":
                    self.settle_exit(item.session_id, f"parallel-cleanup-{index}")
            self.wait(self.snapshot, lambda value: value.capacity.available == 4)
            self.record("simultaneous-entries", results=[item.status for item in results], oversubscribed=False)

            self.done(self.execute("all-full", {"type": "set-all-slot-sensors", "occupied": True}, role="admin"))
            self.wait(self.snapshot, lambda value: value.capacity.available == 0)
            self.closed("entry")
            full = self.execute("entry-full", {"type": "enter", "plate": "B 999 DEM"})
            assert full.status == "rejected" and full.error.code == "PARKING_FULL"
            self.done(self.execute("all-free", {"type": "set-all-slot-sensors", "occupied": False}, role="admin"))
            self.record("full-parking", available=0, admission_result="PARKING_FULL")

            for node in ("S1", "G"):
                self.done(self.execute(f"{node}-offline", {"type": "set-node-online", "nodeId": node, "online": False}, role="admin"))
                snapshot = self.snapshot()
                assert snapshot.capacity.available is None
                assert all(slot.occupied is None for slot in snapshot.slots if node == "G" or slot.node_id == node)
                blocked = self.execute(f"{node}-blocked-entry", {"type": "enter", "plate": "B 505 DEM"})
                assert blocked.status == "rejected" and blocked.error.code == "DATA_UNAVAILABLE"
                self.done(self.execute(f"{node}-online", {"type": "set-node-online", "nodeId": node, "online": True}, role="admin"))
                self.wait(self.snapshot, lambda value: value.capacity.available == 4)
            self.record("unavailable-node-and-gateway", missing_data="null/UNKNOWN", capacity_unknown=True)

            self.closed("entry")
            saved = self.done(self.execute("restart-entry", {"type": "enter", "plate": "B 303 DEM"})).session_id
            self.done(self.execute("restart-payment", {"type": "pay", "sessionId": saved}))
            self.closed("entry")
            paid = self.request("/sessions/" + saved)["paidBani"]

        with self.server(database):
            self.wait(self.snapshot, lambda value: value.capacity.available == 3)
            restored = self.request("/sessions/" + saved)
            assert restored["status"] == "paid" and restored["paidBani"] == paid
            assert self.command("restart-entry").status == "done"
            self.done(self.submit("restart-payment", {"type": "pay", "sessionId": saved}, replay=True))
            self.settle_exit(saved, "restart-cleanup")
            self.record("restart-preserves-session-payment-and-replay", session_status="paid", paid_bani=paid)

        uncertain_database = directory / "uncertain.sqlite3"
        with self.server(uncertain_database, auto_passage=False):
            self.wait(self.snapshot, lambda value: value.capacity.available == 4)
            self.submit("uncertain-entry", {"type": "enter", "plate": "B 404 DEM"})
            self.wait(lambda: self.command("uncertain-entry"), lambda value: value.status == "executing")
            # A client deadline never authorizes a resend or an invented passage.
            time.sleep(0.3)
            assert self.command("uncertain-entry").status == "executing"
            assert self.snapshot().capacity.outstanding_claims == 1

        with self.server(uncertain_database, auto_passage=False):
            assert self.command("uncertain-entry").status == "unknown"
            snapshot = self.snapshot()
            assert snapshot.capacity.outstanding_claims == 1
            assert len(snapshot.sessions) == 1 and snapshot.sessions[0].status == "pending_entry"
            assert sum(item.command_id == "uncertain-entry" for item in snapshot.commands) == 1
            self.record("client-timeout-and-restart-without-resend", after_restart="unknown", held_claims=1,
                        same_command_id=True, fabricated_passage=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Optional JSON evidence file; contains no credentials")
    args = parser.parse_args()
    # This is a standalone acceptance process, not the user's configured API.
    # Do not inherit hardware/credential/database settings from its terminal.
    for name in list(os.environ):
        if name.startswith("PARKING_"):
            del os.environ[name]
    acceptance = Acceptance()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="parking-handoff-") as directory:
        acceptance.run(Path(directory))
    report = {"passed": True, "python": platform.python_version(), "platform": platform.system(),
              "duration_seconds": round(time.monotonic() - started, 2), "mode": "simulation",
              "physical_hardware_validated": False, "scenarios": acceptance.results}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PASS handoff: {len(acceptance.results)} scenarios, {report['duration_seconds']}s; no physical hardware")


if __name__ == "__main__":
    main()
