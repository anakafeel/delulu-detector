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
    performance: Optional[float]   # None = voided round
    gap: Optional[float]
    score: Optional[int]
    tier: str                      # "validated" | "mild" | "spicy" | "delulu" | "false_start" | "timeout" | "void"
    direction: str                 # "over" (claimed more than delivered), "under", "spot_on", or "n/a"

    @property
    def scored(self) -> bool:
        return self.gap is not None


def score_reflex_round(
    claim: float,
    actual_ms: Optional[float],
    false_start: bool = False,
    timeout: bool = False,
    round_id: int = 1,
) -> RoundResult:
    """Turn one raw Round-1 reading into a scored RoundResult."""
    claim_i = int(round(clamp(float(claim))))

    if false_start:
        performance = config.FALSE_START_PERFORMANCE
        special = "false_start"
    elif timeout or actual_ms is None:
        timeout = True
        performance = config.TIMEOUT_PERFORMANCE
        special = "timeout"
    else:
        performance = reaction_ms_to_performance(float(actual_ms))
        special = None

    if performance is None:
        return RoundResult(round_id, claim_i, actual_ms, false_start, timeout,
                           None, None, None, "void", "n/a")

    gap = compute_gap(claim_i, performance)
    score = compute_score(gap)
    tier = special or gap_tier(gap)
    if abs(claim_i - performance) < 0.5:
        direction = "spot_on"
    elif claim_i > performance:
        direction = "over"
    else:
        direction = "under"
    return RoundResult(round_id, claim_i, actual_ms, false_start, timeout,
                       round(performance, 1), round(gap, 1), score, tier, direction)
