"""Authentication and permission boundaries, including fail-closed hardware."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.settings import Settings

VIEWER = "test-viewer-credential-000000000000000000"
OPERATOR = "test-operator-credential-0000000000000000"
ADMIN = "test-admin-credential-0000000000000000000"


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "access.sqlite3"
        self.settings = Settings(database_path=self.path, worker_enabled=False, simulator_enabled=False,
            viewer_token=VIEWER, operator_token=OPERATOR, admin_token=ADMIN)
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app, raise_server_exceptions=False))

    def header(self, token):
        return {"Authorization": "Bearer " + token}

    def request(self, token, identifier="payment", action=None):
        return self.client.post("/api/v1/commands", headers=self.header(token), json={
            "commandId": identifier, "action": action or {"type": "pay", "sessionId": "missing"}})

    def test_public_health_but_protected_reads_and_commands(self):
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        for url in ("/api/v1/snapshot", "/api/v1/commands/missing", "/api/v1/sessions", "/api/v1/events"):
            result = self.client.get(url)
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json()["error"]["code"], "UNAUTHORIZED")
            self.assertEqual(result.headers["www-authenticate"], "Bearer")
        result = self.request("not-a-valid-token")
        self.assertEqual(result.status_code, 401)
        self.assertEqual(self.app.state.parking.pending_commands(), [])

    def test_viewer_can_read_but_not_reserve_a_command_id(self):
        self.assertEqual(self.client.get("/api/v1/snapshot", headers=self.header(VIEWER)).status_code, 200)
        self.assertEqual(self.request(VIEWER).status_code, 403)
        self.assertEqual(self.app.state.parking.pending_commands(), [])
        self.assertEqual(self.request(OPERATOR).status_code, 202)
        self.assertEqual(self.request(OPERATOR).status_code, 200)

    def test_operator_cannot_change_sensors_or_transport(self):
        for index, action in enumerate(({"type": "set-all-slot-sensors", "occupied": True},
            {"type": "set-node-online", "nodeId": "G", "online": False},
            {"type": "set-transport", "transport": "USB"})):
            identifier = f"demo-{index}"
            self.assertEqual(self.request(OPERATOR, identifier, action).status_code, 403)
            self.assertEqual(self.request(ADMIN, identifier, action).status_code, 202)

    def test_unconfigured_access_is_closed_in_both_modes(self):
        for mode in ("simulation", "hardware"):
            settings = Settings(database_path=Path(self.directory.name) / f"{mode}.sqlite3", mode=mode,
                worker_enabled=False, simulator_enabled=False)
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.get("/api/v1/health").status_code, 200)
                self.assertEqual(client.get("/api/v1/snapshot").status_code, 503)
                self.assertEqual(client.post("/api/v1/commands", json={"commandId": "blocked", "action": {
                    "type": "pay", "sessionId": "missing"}}).status_code, 503)
                self.assertEqual(client.app.state.parking.pending_commands(), [])

    def test_hardware_never_allows_anonymous_mode(self):
        with self.assertRaises(ValidationError):
            Settings(mode="hardware", allow_anonymous_simulation=True)

    def test_hardware_still_rejects_admin_simulation_actions(self):
        settings = Settings(database_path=Path(self.directory.name) / "hardware.sqlite3", mode="hardware",
            admin_token=ADMIN, worker_enabled=False)
        with TestClient(create_app(settings)) as client:
            result = client.post("/api/v1/commands", headers=self.header(ADMIN), json={"commandId": "demo", "action": {
                "type": "set-all-slot-sensors", "occupied": False}})
            self.assertEqual(result.status_code, 202)
            result = client.app.state.parking.process("demo")
            self.assertEqual(result.error.code, "SIMULATION_ONLY")

    def test_tokens_are_distinct_and_hidden_in_configuration_errors(self):
        for kwargs in ({"operator_token": "short"}, {"operator_token": OPERATOR, "admin_token": OPERATOR}):
            with self.assertRaises(ValidationError) as error:
                Settings(**kwargs)
            self.assertNotIn(OPERATOR, str(error.exception))

    def test_runtime_openapi_documents_auth_permissions(self):
        spec = self.client.get("/openapi.json").json()
        self.assertNotIn("security", spec["paths"]["/api/v1/health"]["get"])
        operation = spec["paths"]["/api/v1/commands"]["post"]
        self.assertEqual(operation["security"], [{"ParkingBearer": []}])
        self.assertTrue({"401", "403"} <= operation["responses"].keys())
