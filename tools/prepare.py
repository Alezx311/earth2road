"""Compatibility entry point; implementation lives in akadem_maps."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from akadem_maps.legacy import prepare_main
if __name__ == "__main__":
    prepare_main()
else:
    from akadem_maps.core import prepare as implementation
    sys.modules[__name__] = implementation
