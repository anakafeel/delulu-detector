"""Gap and score math. Pure functions, no I/O, easy to test."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import config


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def reaction_ms_to_performance(
    ms: float,
    fast_ms: float = config.REFLEX_FAST_MS,
    slow_ms: float = config.REFLEX_SLOW_MS,
) -> float:
    """Map a reaction time to 0-100. fast_ms or faster = 100, slow_ms or slower = 0."""
    if slow_ms <= fast_ms:
        raise ValueError("slow_ms must be greater than fast_ms")
    fraction = (slow_ms - ms) / (slow_ms - fast_ms)
    return clamp(fraction * 100.0)


def compute_gap(claim: float, performance: float) -> float:
    """gap = |claimed_confidence_normalized - actual_performance_normalized| on a 0-100 scale."""
    return abs(clamp(claim) - clamp(performance))


def compute_score(gap: float) -> int:
    """Smaller gap = higher score. 0 gap -> 100 points, 100 gap -> 0 points."""
    return int(round(100.0 - clamp(gap)))


def gap_tier(gap: float, tiers=None) -> str:
    tiers = tiers if tiers is not None else config.GAP_TIERS
    for max_gap, name in tiers:
        if gap <= max_gap:
            return name
    return tiers[-1][1]


@dataclass
class RoundResult:
    round_id: int
    claim: int
    actual_ms: Optional[float]
    false_start: bool
    timeout: bool
    performance: Optional[float]   # None for a false start / timeout (nothing was measured)
    gap: Optional[float]           # None for a false start / timeout
    score: int                     # 0-100; always config.FAILED_ROUND_SCORE for a false start / timeout
    tier: str                      # "validated" | "mild" | "spicy" | "delulu" | "false_start" | "timeout"
    direction: str                 # "over" (claimed more than delivered), "under", "spot_on", or "n/a"

    @property
    def scored(self) -> bool:
        """True if the round has a real gap (counts for best/worst gap and calibration)."""
        return self.gap is not None

    @property
    def failed(self) -> bool:
        """False start or timeout: fixed score, no gap."""
        return self.false_start or self.timeout


def score_reflex_round(
    claim: float,
    actual_ms: Optional[float],
    false_start: bool = False,
    timeout: bool = False,
    round_id: int = 1,
) -> RoundResult:
    """Turn one raw Round-1 reading into a scored RoundResult.

    A false start or timeout always scores config.FAILED_ROUND_SCORE (0) and has
    no performance or gap, so claiming 0 and never pressing can't earn a perfect
    score or a best gap.
    """
    claim_i = int(round(clamp(float(claim))))

    if false_start:
        return RoundResult(round_id, claim_i, actual_ms, True, False,
                           None, None, config.FAILED_ROUND_SCORE, "false_start", "n/a")
    if timeout or actual_ms is None:
        return RoundResult(round_id, claim_i, actual_ms, False, True,
                           None, None, config.FAILED_ROUND_SCORE, "timeout", "n/a")

    performance = reaction_ms_to_performance(float(actual_ms))
    gap = compute_gap(claim_i, performance)
    score = compute_score(gap)
    tier = gap_tier(gap)
    if abs(claim_i - performance) < 0.5:
        direction = "spot_on"
    elif claim_i > performance:
        direction = "over"
    else:
        direction = "under"
    return RoundResult(round_id, claim_i, actual_ms, False, False,
                       round(performance, 1), round(gap, 1), score, tier, direction)
