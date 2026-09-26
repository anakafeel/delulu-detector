import pytest

import config
from scoring import (clamp, compute_gap, compute_score, gap_tier,
                     reaction_ms_to_performance, score_reflex_round)


@pytest.mark.parametrize("ms,expected", [
    (100, 100.0),   # faster than the fast bound clamps to 100
    (150, 100.0),
    (375, 50.0),    # midpoint
    (600, 0.0),
    (900, 0.0),     # slower than the slow bound clamps to 0
])
def test_reaction_mapping_bounds_and_linearity(ms, expected):
    assert reaction_ms_to_performance(ms) == pytest.approx(expected)


def test_reaction_mapping_uses_config_defaults():
    assert config.REFLEX_FAST_MS == 150
    assert config.REFLEX_SLOW_MS == 600
    assert reaction_ms_to_performance(240) == pytest.approx(80.0)


def test_reaction_mapping_rejects_bad_bounds():
    with pytest.raises(ValueError):
        reaction_ms_to_performance(300, fast_ms=600, slow_ms=150)


def test_gap_is_symmetric_and_clamped():
    assert compute_gap(80, 30) == 50
    assert compute_gap(30, 80) == 50
    assert compute_gap(150, -20) == 100


def test_score_is_inverse_of_gap():
    assert compute_score(0) == 100
    assert compute_score(12.4) == 88
    assert compute_score(100) == 0
    assert compute_score(250) == 0
    assert compute_score(5) > compute_score(40)


@pytest.mark.parametrize("gap,tier", [
    (0, "validated"), (10, "validated"), (10.1, "mild"), (25, "mild"),
    (30, "spicy"), (45, "spicy"), (46, "delulu"), (100, "delulu"),
])
def test_gap_tiers(gap, tier):
    assert gap_tier(gap) == tier


def test_score_reflex_round_normal_overconfident():
    r = score_reflex_round(claim=90, actual_ms=375)
    assert r.performance == 50.0
    assert r.gap == 40.0
    assert r.score == 60
    assert r.tier == "spicy"
    assert r.direction == "over"
    assert r.scored


def test_score_reflex_round_validated_and_under():
    r = score_reflex_round(claim=75, actual_ms=240)  # perf 80
    assert r.gap == 5.0 and r.tier == "validated" and r.direction == "under"


def test_false_start_scores_zero_with_no_gap():
    r = score_reflex_round(claim=85, actual_ms=None, false_start=True)
    assert r.false_start and r.failed
    assert r.performance is None and r.gap is None
    assert r.score == 0
    assert r.tier == "false_start" and r.direction == "n/a"
    assert not r.scored


def test_missing_ms_is_timeout():
    r = score_reflex_round(claim=40, actual_ms=None)
    assert r.timeout and r.tier == "timeout"
    assert r.score == 0 and r.gap is None and r.performance is None


def test_claim_zero_with_timeout_is_not_a_perfect_score():
    # Regression: this used to be performance 0 -> gap 0 -> score 100.
    r = score_reflex_round(0, None, timeout=True)
    assert r.score == 0
    assert r.tier == "timeout"
    assert r.gap is None and r.performance is None
    assert not r.scored


def test_claim_zero_with_false_start_is_not_a_perfect_score():
    r = score_reflex_round(0, None, false_start=True)
    assert r.score == 0
    assert r.tier == "false_start"
    assert r.gap is None and r.performance is None
    assert not r.scored


def test_false_start_wins_over_timeout_flag():
    r = score_reflex_round(50, None, false_start=True, timeout=True)
    assert r.tier == "false_start" and r.score == 0


def test_claim_is_clamped():
    assert clamp(140) == 100 and clamp(-3) == 0
    assert score_reflex_round(claim=140, actual_ms=150).claim == 100
