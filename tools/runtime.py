"""Compatibility entry point; implementation lives in akadem_maps."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from akadem_maps import runtime as implementation
sys.modules[__name__] = implementation
