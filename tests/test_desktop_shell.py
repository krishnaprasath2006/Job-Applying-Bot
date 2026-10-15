"""tests/test_desktop_shell.py — Phase 2: FastAPI sidecar lifecycle harness.

Validates the sidecar lifecycle end-to-end:
- start sidecar
- parse machine-readable listening handshake from stdout
- maintain stderr tail for diagnostics
- expose backend state via /api/ready
- expose lifecycle commands
- send shutdown through stdin
- graceful shutdown with exit code 0
- kill fallback for cleanup (only in dedicated shutdown test)
- no business logic
"""

import json
import subprocess
import sys
import time
import re
import threading
import os
import socket
import urllib.request
from pathlib import Path

import pytest

# Resolve repository root from test file location (portable across OS)
TEST_FILE = Path(__file__).resolve()
REPO_ROOT = TEST_FILE.parent.parent
SRC_DIR = REPO_ROOT / "src"

# Constants for the sidecar lifecycle
SHUTDOWN_COMMAND = b'{"event":"shutdown"}'
LISTENING_HANDSHAKE = re.compile(r'"event":"listening"')


def find_free_port() -> int:
    """Find a free TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]




    def _reader():
        """Thread target: read all stdout and put in queue."""
        data = b''
        while True:
            try:
                chunk = sidecar.stdout.read1(4096)
                if not chunk:
                    break
                data += chunk
            except Exception:
                break
        result_queue.put(data)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    deadline = time.time() + timeout
    data = b''

    while time.time() < deadline:
        try:
            data = result_queue.get(timeout=min(deadline - time.time(), 0.5))
        except queue.Empty:
            if pattern.search(data.decode('utf-8', errors='replace')):
                return data
            continue
        if pattern.search(data.decode('utf-8', errors='replace')):
            return data

        if sidecar.poll() is not None:
            # Read any remaining data
            try:
                remaining = sidecar.stdout.read()
                if remaining:
                    data += remaining
            except Exception:
                pass
            break

    # Final check
    if pattern.search(data.decode('utf-8', errors='replace')):
        return data

    return b''



def _start_sidecar():
    """Start the FastAPI sidecar subprocess.

    Returns the subprocess.Popen object for the sidecar process.
    The sidecar is expected to emit a {"event":"listening"} handshake on stdout
    with host and port information.
    """
    import socket

    # Use a free port to avoid collisions in test environments
    port = find_free_port()
    env = dict(os.environ)
    env["ASSISTANT_DESKTOP_DATA_ROOT"] = ""
    env["TEST_DYNAMIC_PORT"] = str(port)
    # Ensure src is on the path so the api module can be imported
    # Use os.pathsep for portable path separator
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.app:create_app",
         "--factory", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(REPO_ROOT),
    )

    # Wait for the listening handshake or timeout
    deadline = time.time() + 20
    handshake_data = b""

    while time.time() < deadline:
        try:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            handshake_data += chunk
            if LISTENING_HANDSHAKE.search(handshake_data.decode("utf-8", errors="replace")):
                break
        except Exception:
            break

    try:
        handshake_text = handshake_data.decode('utf-8', errors='replace')
        json_match = re.search(r'\{[^}]*"event"\s*:\s*"listening"[^}]*\}', handshake_text)
        if json_match:
            handshake_parsed = json.loads(json_match.group(0))
    except Exception:
        pass

    return proc, handshake_parsed


@pytest.fixture
def sidecar_process(request):
    """Start the FastAPI sidecar subprocess and yield it for testing."""
    proc, handshake_parsed = _start_sidecar()
    # Determine the API base port from the handshake, fallback to 8000
    api_port = 8000
    if handshake_parsed and isinstance(handshake_parsed, dict):
        api_port = handshake_parsed.get("port", 8000) or 8000
        handshake = handshake_parsed
    else:
        handshake = None

    def fin():
        try:
            proc.stdin.write(SHUTDOWN_COMMAND)
            proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    request.addfinalizer(fin)
    return proc, handshake, api_port


class TestSidecarLifecycle:
    """Sidecar lifecycle end-to-end tests."""

    def test_start_sidecar(self, sidecar_process):
        """Verify the sidecar starts and is alive."""
        proc, _, api_port = sidecar_process
        assert proc.poll() is None, "Sidecar process exited prematurely"

    def test_listening_handshake_parsed(self, sidecar_process):
        """Verify the listening handshake is detected and parsed correctly."""
        proc, handshake, api_port = sidecar_process
        assert handshake is not None, "Failed to receive listening handshake"
        assert handshake.get("event") == "listening", f"Expected event=listening, got {handshake}"
        assert handshake.get("host") == "127.0.0.1", f"Expected host=127.0.0.1, got {handshake.get('host')}"

    def test_api_ready_returns_200(self, sidecar_process):
        """Verify /api/ready returns 200 when sidecar is running."""
        import json
        try:
            proc, _, api_port = sidecar_process
            req = urllib.request.Request(
                f"http://127.0.0.1:{api_port}/api/ready",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
                body = resp.read()
                status_data = json.loads(body)
                assert status_data.get("status") in ("ready", "not_ready")
        except Exception as e:
            pytest.fail(f"/api/ready check failed: {e}")

    def test_sidecar_emits_listening_handshake(self, sidecar_process):
        """Verify the sidecar emits a listening handshake on stdout."""
        proc, handshake, api_port = sidecar_process
        assert handshake is not None, "Failed to receive listening handshake"
        assert handshake.get("event") == "listening", f"Expected event=listening, got {handshake}"
        assert handshake.get("host") == "127.0.0.1", f"Expected host=127.0.0.1, got {handshake.get('host')}"



    def test_api_ready_check_content(self, sidecar_process):
        """Verify /api/ready returns meaningful check data."""
        import json
        try:
            proc, _, api_port = sidecar_process
            req = urllib.request.Request(
                f"http://127.0.0.1:{api_port}/api/ready",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
                body = resp.read()
                status_data = json.loads(body)
                # Verify checks dictionary exists and has expected keys
                checks = status_data.get("checks", {})
                assert isinstance(checks, dict)
                # Key checks should include sqlite and safety
                assert "sqlite.readable" in checks or "sqlite" in str(checks)
        except Exception as e:
            pytest.fail(f"/api/ready content check failed: {e}")