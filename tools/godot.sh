# Sourced (from the repository root) by setup.sh, start.sh and tools/check_*.sh: the Godot
# binary for this host. Keep in sync with akadem_maps/runtime.py (godot_names, godot_url).
godot_version=4.6-stable
case "$(uname -s)" in
  Darwin)
    # The macOS zip holds Godot.app (universal: arm64 + x86_64); setup.sh unpacks it under a
    # versioned name so another Godot version in .tools cannot be picked up by mistake.
    godot_archive=Godot_v${godot_version}_macos.universal.zip
    godot_app=.tools/Godot_v${godot_version}_macos.app
    godot=$godot_app/Contents/MacOS/Godot ;;
  *)
    godot_archive=Godot_v${godot_version}_linux.x86_64.zip
    godot_app=
    godot=.tools/Godot_v${godot_version}_linux.x86_64 ;;
esac
godot_url=https://github.com/godotengine/godot/releases/download/$godot_version/$godot_archive
