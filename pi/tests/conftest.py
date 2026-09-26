import sys
from pathlib import Path

# Make pi/ importable no matter where pytest is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import config


@pytest.fixture(autouse=True)
def _fixed_steady_thresholds(monkeypatch):
    """Pin Round 2 thresholds so tests don't break when pi/config.py is re-calibrated."""
    monkeypatch.setattr(config, "STEADY_BEST_MG", 8.0)
    monkeypatch.setattr(config, "STEADY_WORST_MG", 80.0)
