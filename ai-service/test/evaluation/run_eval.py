"""Backward-compatible wrapper for legacy path test/evaluation/run_eval.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.eval.evaluation.run_eval import run_evaluation


if __name__ == "__main__":
    run_evaluation(max_examples=10)