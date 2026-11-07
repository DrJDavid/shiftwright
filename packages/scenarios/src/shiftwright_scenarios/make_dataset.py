"""CLI: uv run python -m shiftwright_scenarios.make_dataset --sector ... --out <dir> (see dataset.py)."""
import sys

from .dataset import main

if __name__ == "__main__":
    main(sys.argv[1:])
