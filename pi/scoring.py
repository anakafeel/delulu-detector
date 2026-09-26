"""Gap and score math. Pure functions, no I/O, easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import config

ROUND_REFLEX = 1
ROUND_STEADY = 2

# Unit string each round's "actual" value is reported in (matches the Arduino's "unit" field).
ROUND_UNITS = {ROUND_REFLEX: "ms", ROUND_STEADY: "mg_rms"}


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


def tremor_mg_to_performance(
    mg: float,
    best_mg: Optional[float] = None,
    worst_mg: Optional[float] = None,
) -> float:
    """Map tremor (mg RMS) to 0-100. best_mg or steadier = 100, worst_mg or shakier = 0.

    Bounds default to config.STEADY_BEST_MG / STEADY_WORST_MG, read at call time
    so calibrating them in config.py (or monkeypatching in tests) just works.
    """
    best_mg = config.STEADY_BEST_MG if best_mg is None else best_mg
    worst_mg = config.STEADY_WORST_MG if worst_mg is None else worst_mg
    if worst_mg <= best_mg:
        raise ValueError("worst_mg must be greater than best_mg")
    fraction = (worst_mg - mg) / (worst_mg - best_mg)
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
    actual: Optional[float]        # raw sensor value in `unit` (None for a false start / timeout)
    false_start: bool
    timeout: bool
    performance: Optional[float]   # None for a false start / timeout (nothing was measured)
    gap: Optional[float]           # None for a false start / timeout
    score: int                     # 0-100; always config.FAILED_ROUND_SCORE for a false start / timeout
    tier: str                      # "validated" | "mild" | "spicy" | "delulu" | "false_start" | "timeout"
    direction: str                 # "over" (claimed more than delivered), "under", "spot_on", or "n/a"
    unit: str = "ms"               # "ms" (Round 1) or "mg_rms" (Round 2)
    extra: dict = field(default_factory=dict)   # round-specific raw extras, e.g. {"peak": 61.2, "samples": 500}

    @property
    def actual_ms(self) -> Optional[float]:
        """The reaction time in ms for Round 1 results; None for other units."""
        return self.actual if self.unit == "ms" else None

    @property
    def scored(self) -> bool:
        """True if the round has a real gap (counts for best/worst gap and calibration)."""
        return self.gap is not None

    @property
    def failed(self) -> bool:
        """False start or timeout: fixed score, no gap."""
        return self.false_start or self.timeout


def _direction(claim: int, performance: float) -> str:
    if abs(claim - performance) < 0.5:
        return "spot_on"
    return "over" if claim > performance else "under"


def _scored_result(round_id: int, claim: int, actual: float, unit: str,
                   performance: float, extra: Optional[dict]) -> RoundResult:
    gap = compute_gap(claim, performance)
    return RoundResult(round_id, claim, actual, False, False,
                       round(performance, 1), round(gap, 1), compute_score(gap),
                       gap_tier(gap), _direction(claim, performance), unit, dict(extra or {}))


def score_reflex_round(
    claim: float,
    actual_ms: Optional[float],
    false_start: bool = False,
    timeout: bool = False,
    round_id: int = ROUND_REFLEX,
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
    return _scored_result(round_id, claim_i, actual_ms, "ms", performance, None)


def score_steady_round(
    claim: float,
    tremor_mg: float,
    peak_mg: Optional[float] = None,
    samples: Optional[int] = None,
) -> RoundResult:
    """Turn one raw Round-2 reading (tremor in mg RMS) into a scored RoundResult.

    Round 2 has no false start or timeout. A sensor error (no accelerometer,
    failed reads) has no measurement at all and must not be scored; the caller
    filters those out, and a missing value raises ValueError here.
    """
    if tremor_mg is None:
        raise ValueError("Round 2 needs a tremor value; sensor errors are not scored")
    claim_i = int(round(clamp(float(claim))))
    tremor = float(tremor_mg)
    performance = tremor_mg_to_performance(tremor)
    extra = {}
    if peak_mg is not None:
        extra["peak"] = float(peak_mg)
    if samples is not None:
        extra["samples"] = int(samples)
    return _scored_result(ROUND_STEADY, claim_i, tremor, "mg_rms", performance, extra)


def score_reading(reading: dict) -> RoundResult:
    """Score a parsed serial result (see main.parse_line) for any supported round."""
    round_id = reading["round_id"]
    if round_id == ROUND_REFLEX:
        return score_reflex_round(
            claim=reading["claim"],
            actual_ms=reading.get("actual"),
            false_start=reading.get("false_start", False),
            timeout=reading.get("timeout", False),
            round_id=round_id,
        )
    if round_id == ROUND_STEADY:
        return score_steady_round(
            claim=reading["claim"],
            tremor_mg=reading.get("actual"),
            peak_mg=reading.get("peak"),
            samples=reading.get("samples"),
        )
    raise ValueError(f"unsupported round_id {round_id}")
