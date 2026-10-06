#!/usr/bin/env python3
"""Prints run-time estimate coefficients as JSON for the game (akadem_maps/estimates.py).

    .venv/Scripts/python.exe tools/estimate.py
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from akadem_maps.estimates import read_history, table

TIMINGS = ROOT/'logs/timings.jsonl'


def main():
    print(json.dumps(table(read_history(TIMINGS))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
