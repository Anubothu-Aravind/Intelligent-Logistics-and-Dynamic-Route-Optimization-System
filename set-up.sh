#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-time project setup: Python venv + backend deps, Node deps, .env, database.
# Usage:  ./set-up.sh            (idempotent – safe to re-run)
#         ./set-up.sh --reseed   (also regenerate the demo scenario)
# ---------------------------------------------------------------------------
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

PYTHON_BIN="${PYTHON_BIN:-python3}"
MIN_PY_MINOR=10
MIN_NODE_MAJOR=18

bold "1/6  Checking prerequisites"
command -v "$PYTHON_BIN" >/dev/null || fail "python3 not found – install Python 3.${MIN_PY_MINOR}+"
PY_MINOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')
[ "$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')" = 3 ] && [ "$PY_MINOR" -ge "$MIN_PY_MINOR" ] \
  || fail "Python 3.${MIN_PY_MINOR}+ required (found $("$PYTHON_BIN" --version))"
command -v node >/dev/null || fail "Node.js not found – install Node ${MIN_NODE_MAJOR}+ (https://nodejs.org)"
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJOR" -ge "$MIN_NODE_MAJOR" ] || fail "Node ${MIN_NODE_MAJOR}+ required (found $(node --version))"
command -v npm >/dev/null || fail "npm not found"
"$PYTHON_BIN" -c 'import venv' 2>/dev/null || fail "python3-venv missing (Debian/Ubuntu: sudo apt install python3-venv)"
echo "   python $("$PYTHON_BIN" --version | cut -d' ' -f2) · node $(node --version)"

bold "2/6  Environment file"
if [ ! -f .env ]; then cp .env.example .env; echo "   created .env from .env.example"; else echo "   .env exists – kept"; fi

bold "3/6  Backend (Python virtualenv + requirements)"
if [ ! -d backend/.venv ]; then "$PYTHON_BIN" -m venv backend/.venv; fi
backend/.venv/bin/python -m pip install --upgrade pip --quiet
backend/.venv/bin/pip install -r backend/requirements.txt --quiet
echo "   installed $(backend/.venv/bin/pip list 2>/dev/null | wc -l) packages"

bold "4/6  Frontend (npm packages)"
(cd frontend && if [ -f package-lock.json ]; then npm ci --no-audit --no-fund --loglevel=error; else npm install --no-audit --no-fund --loglevel=error; fi)

bold "5/6  City map: Vijayawada road network (one-time download from OpenStreetMap)"
set -a; . ./.env; set +a
for v in RANDOM_SEED ORDER_COUNT VEHICLE_COUNT VITE_API_URL VITE_WS_URL CARTO_API_KEY VITE_CARTO_API_KEY MAP_TILE_URL CITY_SOURCE; do [ -z "${!v:-}" ] && unset "$v"; done
backend/.venv/bin/python - <<'PY' || fail "Could not download the Vijayawada road network. Check your internet connection (or proxy) and run ./set-up.sh again."
import sys, time
sys.path.insert(0, "backend")
from app.core.config import DATA_DIR, get_scenario
from app.services.city_generator import MapUnavailable, load_network
cfg = get_scenario().section("city")
t = time.perf_counter()
try:
    net, meta = load_network(cfg, int(get_scenario().get("random_seed")), DATA_DIR, force_download=True)
except MapUnavailable as exc:
    print("   ✗", exc)
    sys.exit(1)
how = "cached copy" if meta.get("origin") == "cache" else f"downloaded from {meta.get('origin')}"
print(f"   {cfg.get('name')}: {len(net.nodes)} intersections, {len(net.edges)} road segments "
      f"({meta.get('osm_ways')} OSM ways, radius {meta.get('radius_m')} m) – {how} in {time.perf_counter() - t:.1f} s")
PY

bold "6/6  Database + demo scenario"
RESEED=False; [ "${1:-}" = "--reseed" ] && RESEED=True
(cd "$ROOT" && backend/.venv/bin/python -c "
import sys; sys.path.insert(0, 'backend')
from app.services.engine import ENGINE
ENGINE.bootstrap(reseed=$RESEED)
if ENGINE.boot_error:
    print('   ✗', ENGINE.boot_error); sys.exit(1)
print(f'   fleet: {len(ENGINE.vehicles)} vehicles · orders: {len(ENGINE.orders)} · hubs: {len(ENGINE.depots)}')
") || fail "Database setup failed"

bold "✓ Setup complete. Start the app with ./run.sh"
