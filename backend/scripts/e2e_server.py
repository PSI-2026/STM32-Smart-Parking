"""Disposable real API process for browser tests; never opens a physical adapter."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from app.main import create_app
from app.settings import Settings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--mode", choices=("simulation", "hardware"), default="simulation")
    args = parser.parse_args()
    token = os.environ["PARKING_E2E_TOKEN"]
    with tempfile.TemporaryDirectory(prefix="parking-browser-") as directory:
        settings = Settings(database_path=Path(directory) / "parking.sqlite3", mode=args.mode,
            admin_token=token, hardware_enabled=False, allow_anonymous_simulation=False,
            worker_interval_seconds=0.05, simulator_step_delay_ms=50)
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
