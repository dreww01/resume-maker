#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration defaults
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-8501}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-30}"

PYTHON_BIN="python3"
BACKEND_PID=""
FRONTEND_PID=""
CLEANING_UP=0

# Logging helpers (using printf for POSIX portability)
log_info() {
    printf "\033[0;32m[INFO]\033[0m %s\n" "$*"
}

log_warn() {
    printf "\033[0;33m[WARNING]\033[0m %s\n" "$*"
}

log_error() {
    printf "\033[0;31m[ERROR]\033[0m %s\n" "$*" >&2
}

# Signal cleanup handler
cleanup() {
    if [ "$CLEANING_UP" -eq 1 ]; then
        return
    fi
    CLEANING_UP=1

    echo ""
    log_info "Received shutdown signal. Stopping services..."

    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        log_info "Stopping Streamlit frontend (PID: $FRONTEND_PID)..."
        kill -TERM "$FRONTEND_PID" 2>/dev/null || true
    fi

    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        log_info "Stopping FastAPI backend (PID: $BACKEND_PID)..."
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
    fi

    # Graceful shutdown wait loop
    local wait_count=0
    local max_wait=10
    while [ "$wait_count" -lt "$max_wait" ]; do
        local still_running=0
        if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
            still_running=1
        fi
        if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
            still_running=1
        fi
        if [ "$still_running" -eq 0 ]; then
            break
        fi
        sleep 0.5
        wait_count=$((wait_count + 1))
    done

    # Force kill if still lingering
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        log_warn "Streamlit frontend did not stop gracefully; force killing (PID: $FRONTEND_PID)..."
        kill -KILL "$FRONTEND_PID" 2>/dev/null || true
    fi

    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        log_warn "FastAPI backend did not stop gracefully; force killing (PID: $BACKEND_PID)..."
        kill -KILL "$BACKEND_PID" 2>/dev/null || true
    fi

    log_info "All services stopped cleanly."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Environment & Dependency Safety Checks
init_environment() {
    # 1. Detect and activate virtual environment if present
    if [ -d "$SCRIPT_DIR/.venv" ] && [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
        if [ -z "$VIRTUAL_ENV" ] || [ "$VIRTUAL_ENV" != "$SCRIPT_DIR/.venv" ]; then
            log_info "Activating virtual environment (.venv)..."
            # shellcheck disable=SC1091
            source "$SCRIPT_DIR/.venv/bin/activate"
            hash -r 2>/dev/null || true
        fi
        if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
            PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
        elif [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
            PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
        fi
    else
        if command -v python3 >/dev/null 2>&1; then
            PYTHON_BIN="python3"
        elif command -v python >/dev/null 2>&1; then
            PYTHON_BIN="python"
        else
            log_error "Python executable not found in PATH."
            exit 1
        fi
    fi

    # 2. Check Python executable & version compatibility (>= 3.11)
    local py_check
    py_check=$("$PYTHON_BIN" -c '
import sys
if sys.version_info >= (3, 11):
    print("OK")
else:
    print(f"FAIL:{sys.version.split()[0]}")
' 2>/dev/null || echo "FAIL:unknown")

    if [ "$py_check" = "OK" ]; then
        : # Python version is compatible
    elif [[ "$py_check" =~ ^FAIL: ]]; then
        local detected_ver="${py_check#FAIL:}"
        log_error "Python 3.11+ is required. Detected Python version: $detected_ver"
        exit 1
    else
        log_error "Failed to verify Python version compatibility."
        exit 1
    fi

    # 3. Environment configuration (.env) check
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        if [ -f "$SCRIPT_DIR/.env.example" ]; then
            log_warn ".env file not found. Automatically initializing .env from .env.example..."
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            log_warn "Please update .env with your actual credentials (e.g., OPENAI_API_KEY)."
        else
            log_warn ".env file not found and .env.example is missing."
        fi
    fi

    # Export project directory to PYTHONPATH
    export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
}

# Check if a specific port is free
# Exits 0 if free, 1 if in use
is_port_free() {
    local port="$1"
    local host="${2:-0.0.0.0}"
    "$PYTHON_BIN" -c "
import socket, sys
port = int(sys.argv[1])
host = sys.argv[2] if len(sys.argv) > 2 else '0.0.0.0'
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.5)
if s.connect_ex(('127.0.0.1', port)) == 0:
    s.close()
    sys.exit(1)
s.close()
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
" "$port" "$host" 2>/dev/null
}

# Ensure port is free, exit on collision
ensure_port_available() {
    local port="$1"
    local service_name="$2"
    local host="${3:-0.0.0.0}"

    if ! is_port_free "$port" "$host"; then
        log_error "Port $port is already in use. Cannot start $service_name."
        log_error "Please terminate the process occupying port $port or configure an alternative port."
        exit 1
    fi
}

# Probe backend health (HTTP GET /)
probe_backend_health() {
    local host="${1:-127.0.0.1}"
    local port="${2:-8000}"
    "$PYTHON_BIN" -c "
import urllib.request, sys
host = sys.argv[1]
port = sys.argv[2]
url = f'http://{host}:{port}/'
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'run-sh-health-probe'})
    with urllib.request.urlopen(req, timeout=1.5) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
" "$host" "$port" 2>/dev/null
}

# Probe frontend health
probe_frontend_health() {
    local host="${1:-127.0.0.1}"
    local port="${2:-8501}"
    "$PYTHON_BIN" -c "
import urllib.request, socket, sys
host = sys.argv[1]
port = int(sys.argv[2])
for path in ['/_stcore/health', '/']:
    url = f'http://{host}:{port}{path}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'run-sh-health-probe'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                sys.exit(0)
    except Exception:
        pass
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1.0)
res = s.connect_ex((host, port))
s.close()
sys.exit(0 if res == 0 else 1)
" "$host" "$port" 2>/dev/null
}

# Poll backend health endpoint until live
wait_for_backend() {
    local probe_host="127.0.0.1"
    if [ "$BACKEND_HOST" != "0.0.0.0" ] && [ "$BACKEND_HOST" != "localhost" ]; then
        probe_host="$BACKEND_HOST"
    fi

    log_info "Waiting for FastAPI backend to become ready on http://${probe_host}:${BACKEND_PORT}/..."
    local elapsed=0
    while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
        if [ -n "$BACKEND_PID" ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
            log_error "FastAPI backend process terminated unexpectedly during startup."
            cleanup
            exit 1
        fi

        if probe_backend_health "$probe_host" "$BACKEND_PORT"; then
            log_info "FastAPI backend is live and healthy (HTTP 200)!"
            return 0
        fi

        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "Timed out waiting for FastAPI backend to respond after ${HEALTH_TIMEOUT}s."
    cleanup
    exit 1
}

# Start backend service
start_backend() {
    local in_background="${1:-false}"
    ensure_port_available "$BACKEND_PORT" "FastAPI backend" "$BACKEND_HOST"

    log_info "Starting FastAPI backend on ${BACKEND_HOST}:${BACKEND_PORT}..."
    if [ "$in_background" = "true" ]; then
        "$PYTHON_BIN" -m uvicorn src.api:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
        BACKEND_PID=$!
        log_info "FastAPI backend started (PID: $BACKEND_PID)."
    else
        "$PYTHON_BIN" -m uvicorn src.api:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
        BACKEND_PID=$!
        log_info "FastAPI backend running in foreground (PID: $BACKEND_PID). Press Ctrl+C to terminate."
        wait "$BACKEND_PID" 2>/dev/null || true
        cleanup
    fi
}

# Start frontend service
start_frontend() {
    local in_background="${1:-false}"
    ensure_port_available "$FRONTEND_PORT" "Streamlit frontend" "$FRONTEND_HOST"

    log_info "Starting Streamlit frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}..."
    if [ "$in_background" = "true" ]; then
        "$PYTHON_BIN" -m streamlit run src/frontend.py --server.port "$FRONTEND_PORT" --server.address "$FRONTEND_HOST" --server.headless true &
        FRONTEND_PID=$!
        log_info "Streamlit frontend started (PID: $FRONTEND_PID)."
    else
        "$PYTHON_BIN" -m streamlit run src/frontend.py --server.port "$FRONTEND_PORT" --server.address "$FRONTEND_HOST" --server.headless true &
        FRONTEND_PID=$!
        log_info "Streamlit frontend running in foreground (PID: $FRONTEND_PID). Press Ctrl+C to terminate."
        wait "$FRONTEND_PID" 2>/dev/null || true
        cleanup
    fi
}

# Start both services
run_all() {
    ensure_port_available "$BACKEND_PORT" "FastAPI backend" "$BACKEND_HOST"
    ensure_port_available "$FRONTEND_PORT" "Streamlit frontend" "$FRONTEND_HOST"

    start_backend true
    wait_for_backend
    start_frontend true

    echo ""
    log_info "=================================================="
    log_info "Resume Tailor is fully operational!"
    log_info "  - Backend API: http://${BACKEND_HOST}:${BACKEND_PORT} (Docs: http://${BACKEND_HOST}:${BACKEND_PORT}/docs)"
    log_info "  - Frontend UI: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
    log_info "Press Ctrl+C to terminate both services."
    log_info "=================================================="

    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    cleanup
}

# Run pytest test suite
run_tests() {
    log_info "Running test suite with pytest..."
    if [ -x "$SCRIPT_DIR/.venv/bin/pytest" ]; then
        "$SCRIPT_DIR/.venv/bin/pytest" "$@"
    elif command -v pytest >/dev/null 2>&1; then
        pytest "$@"
    else
        "$PYTHON_BIN" -m pytest "$@"
    fi
}

# Check health of running services
run_health() {
    local probe_backend_host="127.0.0.1"
    if [ "$BACKEND_HOST" != "0.0.0.0" ] && [ "$BACKEND_HOST" != "localhost" ]; then
        probe_backend_host="$BACKEND_HOST"
    fi

    local probe_frontend_host="127.0.0.1"
    if [ "$FRONTEND_HOST" != "0.0.0.0" ] && [ "$FRONTEND_HOST" != "localhost" ]; then
        probe_frontend_host="$FRONTEND_HOST"
    fi

    log_info "Probing service health..."
    local exit_code=0

    if probe_backend_health "$probe_backend_host" "$BACKEND_PORT"; then
        printf "\033[0;32m[INFO]\033[0m Backend (port %s): \033[0;32mUP (Healthy - HTTP 200)\033[0m\n" "$BACKEND_PORT"
    else
        printf "\033[0;33m[WARNING]\033[0m Backend (port %s): \033[0;31mDOWN (Unreachable)\033[0m\n" "$BACKEND_PORT"
        exit_code=1
    fi

    if probe_frontend_health "$probe_frontend_host" "$FRONTEND_PORT"; then
        printf "\033[0;32m[INFO]\033[0m Frontend (port %s): \033[0;32mUP (Healthy)\033[0m\n" "$FRONTEND_PORT"
    else
        printf "\033[0;33m[WARNING]\033[0m Frontend (port %s): \033[0;31mDOWN (Unreachable)\033[0m\n" "$FRONTEND_PORT"
        exit_code=1
    fi

    return $exit_code
}

# Display usage instructions
show_help() {
    local exit_val="${1:-0}"
    cat << 'EOF'
Resume Tailor Service Launcher (run.sh)

Usage:
  ./run.sh [command] [options]

Commands:
  (no command) | all   Start both FastAPI backend (:8000) and Streamlit frontend (:8501)
  backend              Start only the FastAPI backend service (:8000)
  frontend             Start only the Streamlit frontend service (:8501)
  test [pytest_args]   Run test suite with pytest (forwards optional pytest arguments)
  health               Probe active backend and frontend ports and report service health
  help | -h | --help   Display this help message and exit

Environment Variables:
  BACKEND_HOST         Host interface for FastAPI backend (default: 127.0.0.1)
  BACKEND_PORT         Port for FastAPI backend (default: 8000)
  FRONTEND_HOST        Host interface for Streamlit frontend (default: 0.0.0.0)
  FRONTEND_PORT        Port for Streamlit frontend (default: 8501)
  HEALTH_TIMEOUT       Timeout in seconds waiting for backend readiness (default: 30)

Examples:
  ./run.sh                 # Start full application (backend + frontend)
  ./run.sh backend         # Start FastAPI backend only
  ./run.sh frontend        # Start Streamlit UI only
  ./run.sh test -v         # Run pytest test suite verbosely
  ./run.sh health          # Check health of running services
EOF
    exit "$exit_val"
}

# Main command dispatcher
COMMAND="${1:-all}"
case "$COMMAND" in
    help|-h|--help)
        show_help 0
        ;;
    all)
        init_environment
        run_all
        ;;
    backend)
        init_environment
        start_backend false
        ;;
    frontend)
        init_environment
        start_frontend false
        ;;
    test)
        init_environment
        shift || true
        run_tests "$@"
        ;;
    health)
        init_environment
        run_health
        ;;
    *)
        log_error "Unknown command: '$COMMAND'"
        echo ""
        show_help 1 >&2
        ;;
esac
