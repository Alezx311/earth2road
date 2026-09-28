#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export XDG_DATA_HOME="$PWD/.cache/data"
export XDG_CONFIG_HOME="$PWD/.cache/config"
export XDG_CACHE_HOME="$PWD/.cache"
export PYTHONUTF8=1
mkdir -p logs "$XDG_DATA_HOME" "$XDG_CONFIG_HOME"
godot=.tools/Godot_v4.6-stable_linux.x86_64
# Godot resolves class_name types (the vehicle addon's Vehicle/Wheel) from game/.godot, which
# only an import creates. Without it main.gd fails to compile and the car never spawns.
if [[ ! -f game/.godot/global_script_class_cache.cfg ]]; then
  echo 'First run: importing the Godot project (once)...'
  "$godot" --headless --path game --import || true
  [[ -f game/.godot/global_script_class_cache.cfg ]] || { echo "Godot import failed; run: $godot --headless --path game --import"; exit 1; }
fi
# ./start.sh [--map ID] [godot args...]: which prepared map to run (default: the last one
# built by tools/prepare.py, see game/data/active_map).
if [[ "${1:-}" == "--map" ]]; then export AKADEM_MAP="$2"; shift 2; fi
# ./start.sh --generate LAT LON [--size KM] [--name NAME]: build a new map around a point
# first (tools/generate_map.py; the same as "New map" in the game's map menu, M).
if [[ "${1:-}" == "--generate" ]]; then
  gen_args=(--lat "$2" --lon "$3"); shift 3
  while [[ "${1:-}" == --size || "${1:-}" == --name ]]; do
    if [[ "$1" == --size ]]; then gen_args+=(--size-km "$2"); else gen_args+=(--name "$2"); fi
    shift 2
  done
  .venv/bin/python tools/generate_map.py "${gen_args[@]}"
  # generate_map installs with --activate: active_map now names the new map.
  export AKADEM_MAP="$(cat game/data/active_map)"
fi
# ./start.sh [--map ID] [--scenario NAME] [godot args...]: options before the Godot args
# go to the traffic bridge (tools/traffic.py), which until now got none at all.
bridge_args=()
while [[ "${1:-}" == --scenario || "${1:-}" == --density || "${1:-}" == --threads || "${1:-}" == --near || "${1:-}" == --teleport ]]; do
  bridge_args+=("$1" "$2"); shift 2
done
# No --map: the game opens its map menu first (M switches maps later as well).
if [[ -z "${AKADEM_MAP:-}" ]]; then export AKADEM_MAP_MENU=1; fi
map="${AKADEM_MAP:-$(cat game/data/active_map 2>/dev/null || echo akadem)}"
export AKADEM_MAP="$map"
if [[ ! -f "game/data/$map/index.json" ]]; then
  echo "Map '$map' is not built. Run ./setup.sh or .venv/bin/python tools/prepare.py --config config/$map.json --install"; exit 1
fi
.venv/bin/python tools/traffic.py "${bridge_args[@]}" > logs/bridge.log 2>&1 &
traffic_pid=$!
cleanup() { kill "$traffic_pid" 2>/dev/null || true; wait "$traffic_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
# Wait until the bridge listens (loading the world and SUMO takes a few seconds); a
# bridge that dies (e.g. the port is still held by a previous run) stops the launch.
for _ in $(seq 1 120); do
  grep -q 'Traffic bridge ready' logs/bridge.log 2>/dev/null && break
  if ! kill -0 "$traffic_pid" 2>/dev/null; then grep -v '^Warning' logs/bridge.log | tail -20; exit 1; fi
  sleep 0.5
done
"$godot" --path game "$@"
