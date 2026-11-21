#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Start the full stack.
#   ./run.sh            backend (uvicorn --reload) + frontend (vite dev server)
#   ./run.sh prod       build the frontend and serve it with `vite preview`
#   ./run.sh backend    backend only        ./run.sh frontend   frontend only
#   ./run.sh stop       stop a running instance of this project (frees the ports)
#   ./run.sh test       run the pytest suite
#   ./run.sh bench      run the algorithm benchmarks (CSV + Markdown in results/)
#
# If a port is busy because an earlier run of THIS project is still alive (closed
# terminal, crashed shell …) it is stopped automatically. If another program owns
# the port, the script stops with a clear message instead of failing with
# "Address already in use".
# ---------------------------------------------------------------------------
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
MODE="${1:-dev}"

[ -f .env ] || { echo "No .env found – run ./set-up.sh first"; exit 1; }
[ -x backend/.venv/bin/python ] || { echo "Backend not installed – run ./set-up.sh first"; exit 1; }
set -a; . ./.env; set +a
for v in RANDOM_SEED ORDER_COUNT VEHICLE_COUNT VITE_API_URL VITE_WS_URL CARTO_API_KEY VITE_CARTO_API_KEY MAP_TILE_URL CITY_SOURCE; do [ -z "${!v:-}" ] && unset "$v"; done
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"; BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"; FRONTEND_PORT="${FRONTEND_PORT:-5173}"

PY="$ROOT/backend/.venv/bin/python"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

port_in_use() {  # host port
  "$PY" - "$1" "$2" <<'PY'
import socket, sys
s = socket.socket(); s.settimeout(0.5)
sys.exit(0 if s.connect_ex((sys.argv[1] if sys.argv[1] not in ("0.0.0.0", "") else "127.0.0.1", int(sys.argv[2]))) == 0 else 1)
PY
}

port_pids() {    # port -> pids listening on it (lsof, fuser or ss, whichever exists)
  local port="$1"
  if command -v lsof >/dev/null; then lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null; then fuser "$port"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true
  elif command -v ss >/dev/null; then ss -ltnpH "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
  fi
}

ours() {         # pid belongs to this project? (working dir or command line inside $ROOT)
  local pid="$1" cwd cmd
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  cmd="$( (tr '\0' ' ' < "/proc/$pid/cmdline") 2>/dev/null || ps -o args= -p "$pid" 2>/dev/null || true)"
  [[ "$cwd" == "$ROOT"* || "$cmd" == *"$ROOT"* ]]
}

stop_pid() {
  local pid="$1"
  pkill -TERM -P "$pid" 2>/dev/null || true
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || return 0; sleep 0.25; done
  pkill -KILL -P "$pid" 2>/dev/null || true; kill -KILL "$pid" 2>/dev/null || true
}

free_port() {    # host port label env-var
  local host="$1" port="$2" label="$3" var="$4" pids pid foreign=()
  port_in_use "$host" "$port" || return 0
  pids="$(port_pids "$port")"
  if [ -z "$pids" ]; then
    echo "✗ Port $port ($label) is in use, but its process could not be identified."
    echo "  Free it (e.g. 'sudo lsof -i :$port') or set $var to another port in .env."; exit 1
  fi
  for pid in $pids; do
    kill -0 "$pid" 2>/dev/null || continue          # already gone (e.g. worker of a stopped reloader)
    if ours "$pid"; then
      echo "• Port $port held by a previous $label of this project (pid $pid) – stopping it"
      stop_pid "$pid"
    else
      foreign+=("$pid")
    fi
  done
  if [ "${#foreign[@]}" -gt 0 ]; then
    echo "✗ Port $port ($label) is used by another program:"
    for pid in "${foreign[@]}"; do echo "    pid $pid: $(ps -o args= -p "$pid" 2>/dev/null | cut -c1-120)"; done
    echo "  Stop it, or set $var to a free port in .env, then run ./run.sh again."; exit 1
  fi
  for _ in $(seq 1 20); do port_in_use "$host" "$port" || return 0; sleep 0.25; done
  echo "✗ Port $port is still busy after stopping the old process – try again in a few seconds."; exit 1
}

start_backend() {
  local reload=()
  { [ "$MODE" = "dev" ] || [ "$MODE" = "backend" ]; } && reload=(--reload --reload-dir "$ROOT/backend/app")
  free_port "$BACKEND_HOST" "$BACKEND_PORT" "backend" BACKEND_PORT
  echo "▶ backend   http://${BACKEND_HOST}:${BACKEND_PORT}  (API docs: /docs)"
  (cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --timeout-graceful-shutdown 3 "${reload[@]}") &
  PIDS+=($!)
}

wait_backend() {
  for _ in $(seq 1 240); do
    if "$PY" -c "import urllib.request; urllib.request.urlopen('http://${BACKEND_HOST}:${BACKEND_PORT}/api/health', timeout=1)" 2>/dev/null; then return 0; fi
    kill -0 "${PIDS[0]}" 2>/dev/null || { echo "✗ backend exited during start-up (see the log above)"; exit 1; }
    sleep 0.5
  done
  echo "✗ backend did not become healthy within 2 minutes"; exit 1
}

start_frontend() {
  free_port "$FRONTEND_HOST" "$FRONTEND_PORT" "frontend" FRONTEND_PORT
  echo "▶ frontend  http://${FRONTEND_HOST}:${FRONTEND_PORT}"
  if [ "$MODE" = "prod" ]; then
    (cd "$ROOT/frontend" && npx vite build --logLevel warn && exec npx vite preview --strictPort) &
  else
    (cd "$ROOT/frontend" && exec npx vite --strictPort) &
  fi
  PIDS+=($!)
}

case "$MODE" in
  dev|prod) start_backend; wait_backend; start_frontend; wait ;;
  backend)  start_backend; wait ;;
  frontend) start_frontend; wait ;;
  stop)     free_port "$BACKEND_HOST" "$BACKEND_PORT" "backend" BACKEND_PORT
            free_port "$FRONTEND_HOST" "$FRONTEND_PORT" "frontend" FRONTEND_PORT
            echo "✓ stopped"; trap - EXIT ;;
  test)     cd backend && CITY_SOURCE=synthetic exec "$PY" -m pytest -q ;;
  bench)    shift || true; cd backend && exec "$PY" scripts/run_benchmarks.py "$@" ;;
  *) echo "usage: ./run.sh [dev|prod|backend|frontend|stop|test|bench]"; exit 1 ;;
esac
