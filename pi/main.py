#!/usr/bin/env python3
"""Delulu Detector - Pi main loop (Round 1: Reflex Round).

Reads newline-delimited JSON from the Arduino, scores each result, logs it to
SQLite, and has the narrator deliver a verdict.

Examples:
    python pi/main.py --port /dev/ttyACM0 --player Saim
    python pi/main.py --mock --player Tester --rounds 3        # no hardware needed
    python pi/main.py --leaderboard
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Iterator, Optional

import config
from elevenlabs_client import deliver_verdict
from scoring import RoundResult, score_reflex_round
from session_log import SessionLog, new_session_id


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_line(line: str) -> Optional[dict]:
    """Return a result dict for scoreable lines, None for anything else.

    Accepts {"type":"result", "round_id", "claim", "actual", ...}. Status lines,
    boot garbage and half-lines are ignored (returned as None).
    """
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict):
        return None
    if msg.get("type", "result") != "result":
        return None
    if "claim" not in msg or "round_id" not in msg:
        return None
    try:
        msg["claim"] = float(msg["claim"])
        msg["round_id"] = int(msg["round_id"])
        if msg.get("actual") is not None:
            msg["actual"] = float(msg["actual"])
    except (TypeError, ValueError):
        return None
    msg["false_start"] = bool(msg.get("false_start", False))
    msg["timeout"] = bool(msg.get("timeout", False))
    return msg


# ---------------------------------------------------------------------------
# Input sources
# ---------------------------------------------------------------------------
def serial_lines(port: str, baud: int) -> Iterator[str]:
    import serial  # pyserial; imported lazily so --mock works without it

    while True:
        try:
            with serial.Serial(port, baud, timeout=1) as ser:
                print(f"Opened {port} @ {baud} baud; waiting {config.SERIAL_OPEN_SETTLE_S}s for the Uno to reset...")
                time.sleep(config.SERIAL_OPEN_SETTLE_S)
                ser.reset_input_buffer()
                print("Ready. Set the dial, press the button to lock your claim, wait for the cue.")
                while True:
                    raw = ser.readline()
                    if raw:
                        yield raw.decode("utf-8", errors="replace")
        except serial.SerialException as exc:
            print(f"Serial error on {port}: {exc}. Retrying in 2s (Ctrl+C to quit)...")
            time.sleep(2)


def mock_lines(rounds: int, seed: Optional[int], delay_s: float) -> Iterator[str]:
    """Emit Arduino-identical JSON lines. Simulates a player whose
    overconfidence shrinks round over round, with the odd false start."""
    rng = random.Random(seed)
    true_ms = rng.gauss(290, 30)                    # this player's "real" speed
    overconfidence = rng.uniform(35, 55)            # starts very delulu
    for seq in range(1, rounds + 1):
        yield json.dumps({"type": "status", "state": "locked"})
        ms = max(120, int(rng.gauss(true_ms, 40)))
        perf_guess = max(0, min(100, (config.REFLEX_SLOW_MS - true_ms) /
                                (config.REFLEX_SLOW_MS - config.REFLEX_FAST_MS) * 100))
        claim = int(max(0, min(100, perf_guess + overconfidence + rng.uniform(-5, 5))))
        overconfidence *= 0.55                      # feedback -> recalibration
        false_start = rng.random() < 0.15
        msg = {"type": "result", "round_id": 1, "seq": seq, "claim": claim,
               "actual": None if false_start else ms, "unit": "ms",
               "false_start": false_start, "timeout": False}
        time.sleep(delay_s)
        yield json.dumps(msg)
        yield json.dumps({"type": "status", "state": "ready"})


# ---------------------------------------------------------------------------
# Game logic glue
# ---------------------------------------------------------------------------
def handle_reading(reading: dict, player: str, session_id: str, log: SessionLog,
                   play_audio: bool = True) -> tuple[RoundResult, int]:
    result = score_reflex_round(
        claim=reading["claim"],
        actual_ms=reading.get("actual"),
        false_start=reading["false_start"],
        timeout=reading["timeout"],
        round_id=reading["round_id"],
    )
    round_number = log.log_round(session_id, player, result)

    if result.false_start:
        reality = "FALSE START (pressed before cue)"
    elif result.timeout:
        reality = "TIMEOUT (no press)"
    else:
        reality = f"{result.actual_ms:.0f} ms -> performance {result.performance:.0f}"
    print(f"\n== {player} | round {round_number} | Reflex ==")
    print(f"   claim {result.claim} | reality {reality}")
    if result.scored:
        print(f"   gap {result.gap:.0f} | score {result.score} | tier {result.tier} ({result.direction})")
    else:
        print("   round voided (not scored)")
    deliver_verdict(result, player, play=play_audio)
    return result, round_number


def print_leaderboard(log: SessionLog) -> None:
    rows = log.leaderboard()
    print("\n-- Leaderboard (best gap = most calibrated) --")
    if not rows:
        print("   (no rounds yet)")
        return
    print(f"   {'player':<16}{'best gap':>9}{'worst gap':>11}{'rounds':>8}{'avg score':>11}")
    for r in rows:
        best = "-" if r["best_gap"] is None else f"{r['best_gap']:.0f}"
        worst = "-" if r["worst_gap"] is None else f"{r['worst_gap']:.0f}"
        avg = "-" if r["avg_score"] is None else f"{r['avg_score']:.1f}"
        print(f"   {r['player']:<16}{best:>9}{worst:>11}{r['total_rounds']:>8}{avg:>11}")
    shame = log.most_delulu()
    if shame:
        print(f"   Most delulu ever: {shame['player']} (gap {shame['gap']:.0f}, claimed {shame['claim']})")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Delulu Detector Pi controller (Round 1: Reflex)")
    ap.add_argument("--port", default=config.SERIAL_PORT, help=f"serial port (default {config.SERIAL_PORT})")
    ap.add_argument("--baud", type=int, default=config.SERIAL_BAUD, help=f"baud rate (default {config.SERIAL_BAUD})")
    ap.add_argument("--player", default="player1", help="player name / id for the session log")
    ap.add_argument("--mock", action="store_true", help="simulate Arduino serial input (no hardware)")
    ap.add_argument("--rounds", type=int, default=3, help="rounds to simulate with --mock (default 3)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for --mock")
    ap.add_argument("--mock-delay", type=float, default=0.5, help="seconds between mock rounds")
    ap.add_argument("--no-audio", action="store_true", help="don't play audio (TTS/fallback still resolved)")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help=f"SQLite path (default {config.DB_PATH})")
    ap.add_argument("--leaderboard", action="store_true", help="print the leaderboard and exit")
    args = ap.parse_args(argv)

    log = SessionLog(args.db)
    if args.leaderboard:
        print_leaderboard(log)
        return 0

    session_id = new_session_id()
    key_state = "set" if config.ELEVENLABS_API_KEY else "NOT set -> fallback verdicts"
    print(f"Delulu Detector | session {session_id} | player {args.player} | db {args.db}")
    print(f"ElevenLabs key {key_state} | TTS timeout {config.ELEVENLABS_TIMEOUT_S}s")

    source = (mock_lines(args.rounds, args.seed, args.mock_delay) if args.mock
              else serial_lines(args.port, args.baud))
    try:
        for line in source:
            reading = parse_line(line)
            if reading is None:
                continue
            if reading["round_id"] != 1:
                print(f"   (ignoring round_id {reading['round_id']}: only Round 1 is implemented)")
                continue
            handle_reading(reading, args.player, session_id, log, play_audio=not args.no_audio)
            print_leaderboard(log)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        series = log.calibration_series(args.player, session_id)
        if series:
            print(f"\nCalibration series for {args.player} this session (round, gap): {series}")
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
