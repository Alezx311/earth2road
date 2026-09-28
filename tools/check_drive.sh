#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export XDG_DATA_HOME="$PWD/.cache/data"
export XDG_CONFIG_HOME="$PWD/.cache/config"
export XDG_CACHE_HOME="$PWD/.cache"
export AKADEM_MAP="${AKADEM_MAP:-$(cat game/data/active_map 2>/dev/null || echo akadem)}"
.tools/Godot_v4.6-stable_linux.x86_64 --headless --path game --script res://scripts/validate_drive.gd
