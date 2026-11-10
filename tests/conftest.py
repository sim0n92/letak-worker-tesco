"""Shared fixtures: run the worker as a subprocess against the saved (offline) Tesco fixture."""
from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAIN = next(p for p in (ROOT / "src" / "main.py", ROOT / "main.py") if p.is_file())  # repo or container layout
FIXTURES = ROOT / "tests" / "fixtures"

HM_KEY = "HM|2026-07-01|2026-07-07"
SM_KEY = "SM|2026-07-01|2026-07-07"
UNREACHABLE = "http://127.0.0.1:9/nope"


@dataclass(frozen=True)
class Run:
    """The outcome of one worker invocation: exit code and the parsed stdout JSON lines."""

    returncode: int
    lines: list[dict[str, Any]]
    stdout: str

    @property
    def result(self) -> dict[str, Any]:
        results = [m for m in self.lines if m.get("type") == "result"]
        assert results, f"no result line in {self.stdout!r}"
        return results[-1]["data"]

    @property
    def error(self) -> dict[str, Any]:
        errors = [m for m in self.lines if m.get("type") == "error"]
        assert errors, f"no error line in {self.stdout!r}"
        return errors[-1]


@pytest.fixture
def fixture_config() -> dict[str, str]:
    """Offline override: the leaflet page points at the saved fixture."""
    return {"pageUrl": (FIXTURES / "tesco.html").as_uri()}


@pytest.fixture
def run_action(tmp_path: Path):
    """Run the worker with `_action` + params; returns a Run. Logs go to tmp_path."""

    def _run(action: str, **params: Any) -> Run:
        env = {**os.environ, "LOG_DIR": str(tmp_path / "logs"), "PYTHONIOENCODING": "utf-8"}
        payload = json.dumps({"_action": action, **params}, ensure_ascii=False)
        proc = subprocess.run(
            [sys.executable, str(MAIN)], input=payload.encode("utf-8"),
            capture_output=True, env=env, check=False)
        stdout = proc.stdout.decode("utf-8")
        lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        return Run(proc.returncode, lines, stdout)

    return _run


@pytest.fixture
def empty_page(tmp_path: Path) -> str:
    """A listing page without any leaflet tile (the site layout changed)."""
    page = tmp_path / "empty.html"
    page.write_text("<html><body>redesigned page</body></html>", encoding="utf-8")
    return page.as_uri()


@pytest.fixture
def empty_api(tmp_path: Path) -> str:
    """A saved GraphQL response without any leaflet (the API or the page changed)."""
    file = tmp_path / "empty.json"
    file.write_text(json.dumps({"data": {"leaflets": {"items": [], "totalItems": 0}}}), encoding="utf-8")
    return file.as_uri()


@pytest.fixture
def empty_page(tmp_path: Path) -> str:
    """A page whose catalogue holds no leaflet (the site changed)."""
    file = tmp_path / "empty.html"
    file.write_text('<html><script id="__NEXT_DATA__" type="application/json">'
                    '{"props":{"pageProps":{"__APOLLO_STATE__":{}}}}</script></html>', encoding="utf-8")
    return file.as_uri()


@pytest.fixture
def broken_page(tmp_path: Path) -> str:
    """A page without __NEXT_DATA__ (the markup changed)."""
    file = tmp_path / "broken.html"
    file.write_text("<html><body>redesigned</body></html>", encoding="utf-8")
    return file.as_uri()


@pytest.fixture
def status_server():
    """Starts a local HTTP server answering every GET with the given status; returns its URL."""
    servers: list[http.server.HTTPServer] = []

    def start(status: int) -> str:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}/"

    yield start
    for server in servers:
        server.shutdown()
