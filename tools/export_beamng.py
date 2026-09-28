"""Compatibility entry point; implementation lives in akadem_maps."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    import runpy
    runpy.run_module("akadem_maps.adapters.beamng.export_beamng", run_name="__main__")
else:
    from akadem_maps.adapters.beamng import export_beamng as implementation
    sys.modules[__name__] = implementation
