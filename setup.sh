#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mkdir -p .tools .cache logs
# Pinned packages have 64-bit wheels for CPython 3.11-3.14 only (libsumo/pyproj/shapely: no 3.15 yet).
pycheck='import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) and sys.maxsize > 2**32 else 1)'
if ! { [[ -x .venv/bin/python ]] && .venv/bin/python -c "$pycheck" 2>/dev/null; }; then
  py=''
  for cand in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null && "$cand" -c "$pycheck" 2>/dev/null; then py=$cand; break; fi
  done
  [[ -n "$py" ]] || { echo '64-bit Python 3.11-3.14 is required (3.14 is the pinned, validated version).'; exit 1; }
  rm -rf .venv
  "$py" -m venv .venv
fi
# Editable: the CLI must run this checkout, not a copy frozen at setup time.
.venv/bin/python -m pip install --cache-dir .cache/pip -c requirements.lock -e ".[generator,traffic]"
source tools/godot.sh
if [[ ! -x "$godot" ]]; then
  curl -fL --retry 2 "$godot_url" -o .tools/godot.zip
  if [[ -n "$godot_app" ]]; then
    rm -rf .tools/Godot.app "$godot_app"
    unzip -q -o .tools/godot.zip -d .tools
    mv .tools/Godot.app "$godot_app"
  else
    unzip -o .tools/godot.zip -d .tools
  fi
fi
.venv/bin/python tools/fetch_assets.py
.venv/bin/python tools/fetch_textures.py || echo 'Textures not downloaded — the game will use flat materials.'
.venv/bin/python tools/fetch_visual_assets.py || echo 'CC0 visual pack not downloaded — benches and lamps stay procedural.'
# Builds game/.godot (class_name cache for the vehicle addon); start.sh repeats it if missing.
XDG_DATA_HOME="$PWD/.cache/data" XDG_CONFIG_HOME="$PWD/.cache/config" "$godot" --headless --path game --import || echo 'Godot import failed; start.sh will retry.'
# As in setup.ps1: configured maps are not rebuilt here.
# A fresh checkout has no maps (game/data/ is not in Git): install the offline example so
# start.sh works right away. Skipped when any map is already installed.
if [[ ! -f game/data/active_map ]]; then
  stamp=$(date +%Y%m%d-%H%M%S)
  .venv/bin/earth2road build --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output "out/tiny-world-$stamp"
  .venv/bin/earth2road export --target godot --world "out/tiny-world-$stamp" --output "out/tiny-godot-$stamp" --offline
  .venv/bin/earth2road install --target godot --export "out/tiny-godot-$stamp" --root . --activate
fi
echo "Earth2Road setup complete. Run ./start.sh (the offline example map 'tiny' is installed if no other map was)."
echo 'BeamNG ZIP of a map: .venv/bin/earth2road export --target beamng --world out/generated/<id> --output out/<id>_beamng'
echo 'Rebuild a map: .venv/bin/python tools/prepare.py --config config/<id>.json --install [--replace] [--activate]'
echo 'New map anywhere: ./start.sh --generate LAT LON [--size KM] [--name NAME], or M → New map in the game.'
