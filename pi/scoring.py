"""Gap and score math. Pure functions, no I/O, easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import config

ROUND_REFLEX = 1
ROUND_STEADY = 2
ROUND_POKER = 5
ROUND_STRAIGHT = 6     # What the Hill's Round 3: Straight Face Under Pressure

# Unit string each round's "actual" value is reported in (matches the Arduino's "unit" field;
# Rounds 5 and 6 are measured on the Pi: smile_frac as a percent / seconds held).
ROUND_UNITS = {ROUND_REFLEX: "ms", ROUND_STEADY: "mg_rms", ROUND_POKER: "smile_pct",
               ROUND_STRAIGHT: "s"}


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


def smile_frac_to_performance(
    smile_frac: float,
    best_frac: Optional[float] = None,
    worst_frac: Optional[float] = None,
) -> float:
    """Map Round 5 smile_frac (0-1) to 0-100. best_frac or less = 100, worst_frac or more = 0.

    Bounds default to config.POKER_BEST_FRAC / POKER_WORST_FRAC, read at call time
    (to be calibrated on hardware, and pinned by the tests).
    """
    best_frac = config.POKER_BEST_FRAC if best_frac is None else best_frac
    worst_frac = config.POKER_WORST_FRAC if worst_frac is None else worst_frac
    if worst_frac <= best_frac:
        raise ValueError("worst_frac must be greater than best_frac")
    fraction = (worst_frac - smile_frac) / (worst_frac - best_frac)
    return clamp(fraction * 100.0)


def held_s_to_performance(held_s: float, max_s: Optional[float] = None) -> float:
    """Straight Face: seconds held -> 0-100 on the same scale as the claim (0 s = 0, max_s = 100)."""
    max_s = config.STRAIGHT_MAX_S if max_s is None else max_s
    if max_s <= 0:
        raise ValueError("max_s must be positive")
    return clamp(float(held_s) / max_s * 100.0)


def claim_to_seconds(claim: float, max_s: Optional[float] = None) -> float:
    """Straight Face: the dial's 0-100 claim as seconds (0-STRAIGHT_MAX_S)."""
    max_s = config.STRAIGHT_MAX_S if max_s is None else max_s
    return clamp(float(claim)) / 100.0 * max_s


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
    unit: str = "ms"               # "ms" (1), "mg_rms" (2), "smile_pct" (5) or "s" (6, seconds held)
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


def score_composure_round(
    round_id: int,
    claim: float,
    composure: float,
    extra: Optional[dict] = None,
) -> RoundResult:
    """Score a face round from Presage's neutral-expression confidence (0-100).

    The claim is already 0-100. Performance is that confidence, unchanged.
    A missing or non-finite composure is not a score: the caller must not
    substitute one, and this function raises instead.
    """
    if composure is None:
        raise ValueError("face round needs a Presage composure value")
    value = float(composure)
    if value < 0.0 or value > 100.0:
        raise ValueError("Presage composure must be between 0 and 100")
    claim_i = int(round(clamp(float(claim))))
    performance = value
    return _scored_result(round_id, claim_i, round(value, 1), "composure", performance, extra)


def score_poker_round(
    claim: float,
    smile_frac: float,
    face_frac: Optional[float] = None,
    frames: Optional[int] = None,
    fps: Optional[float] = None,
    first_smile_ms: Optional[int] = None,
) -> RoundResult:
    """Turn one Round-5 window (smile_frac = smiling face frames / face frames) into a RoundResult.

    actual = smile_frac * 100 (unit "smile_pct"); the other readings go to extra.
    A window without enough face ("no_face") or without frames is not scored: the
    caller filters it out, and a missing smile_frac raises ValueError here.
    """
    if smile_frac is None:
        raise ValueError("Round 5 needs a smile_frac; no_face / camera errors are not scored")
    claim_i = int(round(clamp(float(claim))))
    frac = max(0.0, min(1.0, float(smile_frac)))
    performance = smile_frac_to_performance(frac)
    extra: dict = {"smile_frac": round(frac, 4)}
    if face_frac is not None:
        extra["face_frac"] = round(float(face_frac), 4)
    if frames is not None:
        extra["frames"] = int(frames)
    if fps is not None:
        extra["fps"] = round(float(fps), 1)
    extra["first_smile_ms"] = None if first_smile_ms is None else int(first_smile_ms)
    return _scored_result(ROUND_POKER, claim_i, round(frac * 100.0, 2), "smile_pct", performance, extra)


def score_straight_round(
    claim: float,
    held_s: float,
    broke: Optional[bool] = None,
    trigger: Optional[str] = None,
    face_frac: Optional[float] = None,
    frames: Optional[int] = None,
    fps: Optional[float] = None,
    max_s: Optional[float] = None,
) -> RoundResult:
    """Straight Face (id 6): seconds held until the face changed -> RoundResult.

    The claim (0-100) stands for 0-max_s seconds, and so does the performance, so
    gap = |claim - held / max_s * 100| (claim 50 = 10 s with the default 20 s).
    actual = seconds held (unit "s"). no_face / camera errors are not scored: the
    caller filters them out, and a missing held_s raises ValueError here.
    """
    if held_s is None:
        raise ValueError("Straight Face needs held_s; no_face / camera errors are not scored")
    max_s = config.STRAIGHT_MAX_S if max_s is None else float(max_s)
    claim_i = int(round(clamp(float(claim))))
    held = max(0.0, min(max_s, float(held_s)))
    performance = held_s_to_performance(held, max_s)
    extra: dict = {"held_s": round(held, 2), "max_s": max_s,
                   "claim_s": round(claim_to_seconds(claim_i, max_s), 1)}
    if broke is not None:
        extra["broke"] = bool(broke)
    if trigger is not None:
        extra["trigger"] = str(trigger)
    if face_frac is not None:
        extra["face_frac"] = round(float(face_frac), 4)
    if frames is not None:
        extra["frames"] = int(frames)
    if fps is not None:
        extra["fps"] = round(float(fps), 1)
    return _scored_result(ROUND_STRAIGHT, claim_i, round(held, 2), "s", performance, extra)


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
    if round_id in (ROUND_POKER, ROUND_STRAIGHT) and reading.get("composure") is not None:
        extra = {k: reading[k] for k in ("smile_frac", "face_frac", "frames", "fps",
                                          "held_s", "first_smile_ms", "presage_samples") if k in reading}
        return score_composure_round(round_id, reading["claim"], reading["composure"], extra)
    if round_id == ROUND_POKER:
        frac = reading.get("smile_frac")
        if frac is None and reading.get("actual") is not None:
            frac = float(reading["actual"]) / 100.0
        return score_poker_round(
            claim=reading["claim"],
            smile_frac=frac,
            face_frac=reading.get("face_frac"),
            frames=reading.get("frames"),
            fps=reading.get("fps"),
            first_smile_ms=reading.get("first_smile_ms"),
        )
    if round_id == ROUND_STRAIGHT:
        held = reading.get("held_s", reading.get("actual"))
        return score_straight_round(
            claim=reading["claim"],
            held_s=held,
            broke=reading.get("broke"),
            trigger=reading.get("trigger"),
            face_frac=reading.get("face_frac"),
            frames=reading.get("frames"),
            fps=reading.get("fps"),
            max_s=reading.get("max_s"),
        )
    raise ValueError(f"unsupported round_id {round_id}")
