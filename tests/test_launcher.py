import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import pytest

SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "run.sh"))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_free_port() -> int:
    """Find an available ephemeral TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is currently listening for connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def test_help_flag_displays_usage_and_exits_zero():
    """Test ./run.sh --help, -h, and help display command list and exit 0."""
    for flag in ["--help", "-h", "help"]:
        result = subprocess.run(
            [SCRIPT_PATH, flag],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Expected 0 exit code for {flag}, got {result.returncode}"
        assert "Usage:" in result.stdout
        assert "backend" in result.stdout
        assert "frontend" in result.stdout
        assert "test" in result.stdout
        assert "health" in result.stdout


def test_invalid_command_exits_nonzero():
    """Test ./run.sh with unknown command prints error and exits non-zero."""
    result = subprocess.run(
        [SCRIPT_PATH, "unknown-subcommand-xyz"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Unknown command" in result.stderr or "Unknown command" in result.stdout


def test_run_test_invokes_pytest():
    """Test ./run.sh test forwards execution to pytest and exits 0 on passing test."""
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY", "test-key")

    result = subprocess.run(
        [SCRIPT_PATH, "test", "tests/test_database.py", "-k", "test_get_nonexistent_resume"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "passed" in result.stdout.lower() or "pytest" in result.stdout.lower()


def test_env_auto_initialization(tmp_path):
    """Test that missing .env file is automatically initialized from .env.example."""
    # Create a minimal mock project structure in tmp_path
    mock_run_sh = tmp_path / "run.sh"
    mock_run_sh.write_text(open(SCRIPT_PATH).read())
    mock_run_sh.chmod(0o755)

    example_env = tmp_path / ".env.example"
    example_env.write_text("OPENAI_API_KEY=mock-key-123\n")

    # Run health check mode (which runs init_environment)
    result = subprocess.run(
        [str(mock_run_sh), "health"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    # .env should have been created
    created_env = tmp_path / ".env"
    assert created_env.exists(), ".env was not created from .env.example"
    assert "mock-key-123" in created_env.read_text()
    assert ".env file not found" in result.stdout or ".env file not found" in result.stderr


def test_port_collision_detection():
    """Test that starting a service fails cleanly if the target port is already occupied."""
    backend_port = get_free_port()

    # Occupy the port with a dummy socket server
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", backend_port))
    server_sock.listen(1)

    try:
        env = os.environ.copy()
        env["BACKEND_PORT"] = str(backend_port)
        env["BACKEND_HOST"] = "127.0.0.1"

        result = subprocess.run(
            [SCRIPT_PATH, "backend"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode != 0
        assert f"Port {backend_port} is already in use" in result.stderr or f"Port {backend_port} is already in use" in result.stdout
    finally:
        server_sock.close()


def test_health_check_reporting():
    """Test ./run.sh health reporting for down services."""
    backend_port = get_free_port()
    frontend_port = get_free_port()

    env = os.environ.copy()
    env["BACKEND_PORT"] = str(backend_port)
    env["FRONTEND_PORT"] = str(frontend_port)

    result = subprocess.run(
        [SCRIPT_PATH, "health"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    # Both services are down, so exit code should be 1
    assert result.returncode == 1
    assert "DOWN" in result.stdout or "Unreachable" in result.stdout


def test_full_launch_lifecycle_and_sigint_trapping():
    """Test ./run.sh launches backend and frontend, and traps SIGINT gracefully."""
    backend_port = get_free_port()
    frontend_port = get_free_port()

    env = os.environ.copy()
    env["BACKEND_PORT"] = str(backend_port)
    env["FRONTEND_PORT"] = str(frontend_port)
    env["BACKEND_HOST"] = "127.0.0.1"
    env["FRONTEND_HOST"] = "127.0.0.1"
    env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY", "test-key")

    proc = subprocess.Popen(
        [SCRIPT_PATH],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )

    try:
        # Poll backend health endpoint until live
        backend_url = f"http://127.0.0.1:{backend_port}/"
        backend_healthy = False
        start_time = time.time()

        while time.time() - start_time < 20:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                pytest.fail(f"run.sh terminated prematurely with exit {proc.returncode}.\nStdout:\n{stdout}\nStderr:\n{stderr}")

            try:
                with urllib.request.urlopen(backend_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        backend_healthy = True
                        break
            except Exception:
                time.sleep(0.5)

        assert backend_healthy, f"Backend failed to become healthy at {backend_url}"

        # Send SIGINT to the process group
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)

        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0, f"Expected 0 returncode on SIGINT, got {proc.returncode}.\nStdout: {stdout}\nStderr: {stderr}"
        assert "Received shutdown signal" in stdout or "Stopping" in stdout

        # Verify child ports are freed
        time.sleep(1)
        assert not is_port_in_use(backend_port), f"Backend port {backend_port} was not released"
        assert not is_port_in_use(frontend_port), f"Frontend port {frontend_port} was not released"

    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


def test_python_version_check_rejection(tmp_path):
    """Test that run.sh rejects Python versions below 3.11."""
    mock_run_sh = tmp_path / "run.sh"
    mock_run_sh.write_text(open(SCRIPT_PATH).read())
    mock_run_sh.chmod(0o755)

    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    fake_python = fake_bin_dir / "python3"
    fake_python.write_text("""#!/bin/sh
if [ "$1" = "-c" ]; then
    echo "FAIL:3.10.8"
    exit 0
fi
exec python3 "$@"
""")
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin_dir}:{env.get('PATH', '')}"
    env["VIRTUAL_ENV"] = ""

    result = subprocess.run(
        [str(mock_run_sh), "health"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "Python 3.11+ is required" in result.stderr or "Python 3.11+ is required" in result.stdout


def test_health_check_reporting_when_backend_running():
    """Test ./run.sh health correctly detects and reports healthy backend."""
    backend_port = get_free_port()
    frontend_port = get_free_port()

    env = os.environ.copy()
    env["BACKEND_PORT"] = str(backend_port)
    env["FRONTEND_PORT"] = str(frontend_port)
    env["BACKEND_HOST"] = "127.0.0.1"
    env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY", "test-key")

    proc = subprocess.Popen(
        [SCRIPT_PATH, "backend"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )

    try:
        backend_url = f"http://127.0.0.1:{backend_port}/"
        backend_ready = False
        start_time = time.time()
        while time.time() - start_time < 15:
            try:
                with urllib.request.urlopen(backend_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        backend_ready = True
                        break
            except Exception:
                time.sleep(0.5)

        assert backend_ready, "Backend failed to start"

        # Probe health with run.sh
        health_res = subprocess.run(
            [SCRIPT_PATH, "health"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        assert f"Backend (port {backend_port}):" in health_res.stdout
        assert "UP" in health_res.stdout or "Healthy" in health_res.stdout
    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.communicate(timeout=5)
            except Exception:
                pass


def test_backend_sigterm_trapping():
    """Test ./run.sh backend traps SIGTERM and cleans up child PID."""
    backend_port = get_free_port()

    env = os.environ.copy()
    env["BACKEND_PORT"] = str(backend_port)
    env["BACKEND_HOST"] = "127.0.0.1"
    env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY", "test-key")

    proc = subprocess.Popen(
        [SCRIPT_PATH, "backend"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )

    try:
        backend_url = f"http://127.0.0.1:{backend_port}/"
        backend_healthy = False
        start_time = time.time()

        while time.time() - start_time < 15:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                pytest.fail(f"run.sh backend terminated prematurely.\nStdout:\n{stdout}\nStderr:\n{stderr}")

            try:
                with urllib.request.urlopen(backend_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        backend_healthy = True
                        break
            except Exception:
                time.sleep(0.5)

        assert backend_healthy, "Backend failed to become healthy"

        # Send SIGTERM to process group
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0
        time.sleep(0.5)
        assert not is_port_in_use(backend_port), f"Port {backend_port} was still in use after SIGTERM"

    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


def test_frontend_sigterm_trapping():
    """Test ./run.sh frontend traps SIGTERM and cleans up process."""
    frontend_port = get_free_port()

    env = os.environ.copy()
    env["FRONTEND_PORT"] = str(frontend_port)
    env["FRONTEND_HOST"] = "127.0.0.1"

    proc = subprocess.Popen(
        [SCRIPT_PATH, "frontend"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )

    try:
        # Wait until process is active
        time.sleep(2)
        assert proc.poll() is None, f"Frontend process died prematurely"

        # Send SIGTERM
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0
        time.sleep(0.5)
        assert not is_port_in_use(frontend_port), f"Port {frontend_port} was still in use after SIGTERM"
    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass

