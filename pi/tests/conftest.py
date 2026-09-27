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
    # Off by default so tests with small mg values still score; test it explicitly.
    monkeypatch.setattr(config, "STEADY_REST_MG", 0.0)


@pytest.fixture(autouse=True)
def _fixed_poker_thresholds(monkeypatch):
    """Pin Round 5 thresholds so tests don't break when pi/config.py is re-calibrated."""
    monkeypatch.setattr(config, "POKER_BEST_FRAC", 0.05)
    monkeypatch.setattr(config, "POKER_WORST_FRAC", 0.45)


@pytest.fixture(autouse=True)
def _fixed_straight_thresholds(monkeypatch):
    """Pin Straight Face (id 6) tuning so tests don't break when pi/config.py is re-calibrated."""
    monkeypatch.setattr(config, "STRAIGHT_MAX_S", 20.0)
    monkeypatch.setattr(config, "STRAIGHT_BASELINE_S", 1.0)
    monkeypatch.setattr(config, "STRAIGHT_MIN_BASELINE_FRAMES", 5)
    monkeypatch.setattr(config, "STRAIGHT_BASELINE_TIMEOUT_S", 4.0)
    monkeypatch.setattr(config, "STRAIGHT_K", 4.0)
    monkeypatch.setattr(config, "STRAIGHT_MIN_DIFF", 9.0)
    monkeypatch.setattr(config, "STRAIGHT_HOLD_FRAMES", 3)
    monkeypatch.setattr(config, "STRAIGHT_SMILE_BREAKS", True)
    monkeypatch.setattr(config, "STRAIGHT_TAIL_S", 0.6)


@pytest.fixture(autouse=True)
def _isolated_clip_folders(monkeypatch, tmp_path):
    """Question / joke clips never come from (or go to) the real assets/ during tests."""
    monkeypatch.setattr(config, "QUESTIONS_DIR", tmp_path / "questions")
    monkeypatch.setattr(config, "JOKES_DIR", tmp_path / "jokes")


@pytest.fixture(autouse=True)
def _no_real_tiger_data(monkeypatch):
    # .env may hold the booth's real TIGER_DATA_URL: tests must never write mock rounds to it.
    # (The live test in test_tiger_store.py uses TIGER_TEST_URL explicitly.)
    monkeypatch.setattr(config, "TIGER_DATA_URL", "")
