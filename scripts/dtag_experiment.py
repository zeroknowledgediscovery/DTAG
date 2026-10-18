#!/usr/bin/env python3
"""Run web-app experiments from a source checkout: ``python scripts/dtag_experiment.py --help``.

Same as the installed ``dtag-experiment`` command (see webapp/backend/dtag_web/experiment_cli.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp" / "backend"))

from dtag_web.experiment_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
