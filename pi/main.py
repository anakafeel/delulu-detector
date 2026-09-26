#!/usr/bin/env python3
"""Delulu Detector - Pi main loop (Round 1: Reflex, Round 2: Steady Hands).

Reads newline-delimited JSON from the Arduino, scores each result, logs it to
SQLite, and has the narrator deliver a verdict. The Pi picks the round type by
writing "R1\\n" or "R2\\n" to the Arduino when the port opens.

Examples:
    python pi/main.py --port /dev/ttyACM0 --player Saim               # Round 1 (default)
    python pi/main.py --port /dev/ttyACM0 --player Saim --round 2     # Steady Hands
    python pi/main.py --port /dev/ttyACM0 --round 2 --calibrate       # raw mg only, no scoring/logging
    python pi/main.py --mock --player Tester --rounds 3               # no hardware needed
    python pi/main.py --mock --round 2 --player Tester --rounds 3
    python pi/main.py --leaderboard
    python pi/main.py --port /dev/ttyACM0 --player Saim --ui          # + live browser UI on http://localhost:8765
    python pi/main.py --mock --player Tester --ui                     # UI with simulated rounds
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, Iterator, Optional

import config
import ui_server
from elevenlabs_client import deliver_verdict
from scoring import (ROUND_REFLEX, ROUND_STEADY, RoundResult, score_reading,
                     tremor_mg_to_performance)
from session_log import SessionLog, new_session_id

ROUND_INSTRUCTIONS = {
    ROUND_REFLEX: "Set the dial, press the button to lock your claim, wait for the cue.",
    ROUND_STEADY: ("Set the dial to how steady you are, press the button to lock it, "
                   "then hold the sensor still for 5 s while the matrix is lit."),
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _load_json_object(line: str) -> Optional[dict]:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    return msg if isinstance(msg, dict) else None


def parse_line(line: str) -> Optional[dict]:
    """Return a result dict for scoreable lines, None for anything else.

    Accepts {"type":"result", "round_id", "claim", "actual", ...}. Round 2 lines
    also carry "peak" (mg), "samples" and, on a sensor problem, "error". Status
    lines, boot garbage and half-lines are ignored (returned as None).
    """
    msg = _load_json_object(line)
    if msg is None:
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
    # NaN/inf would sail through clamp() and score 100: treat as a garbled line.
    if not math.isfinite(msg["claim"]) or (
            msg.get("actual") is not None and not math.isfinite(msg["actual"])):
        return None
    msg["false_start"] = bool(msg.get("false_start", False))
    msg["timeout"] = bool(msg.get("timeout", False))
    # Optional Round 2 extras: informational, so a bad value is dropped, not fatal.
    for key, cast in (("peak", float), ("samples", int)):
        if msg.get(key) is not None:
            try:
                msg[key] = cast(msg[key])
            except (TypeError, ValueError):
                msg[key] = None
    if msg.get("error") is not None:
        msg["error"] = str(msg["error"])
    return msg


def parse_dial(line: str) -> Optional[int]:
    """{"type":"dial","value":N} (the knob, while a claim is being set) -> N clamped to 0-100, else None.

    Only the browser UI uses it; everything else ignores these lines (parse_line and
    parse_status return None for them).
    """
    msg = _load_json_object(line)
    if msg is None or msg.get("type") != "dial":
        return None
    value = msg.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(max(0, min(100, round(value))))


def parse_status(line: str) -> Optional[dict]:
    """Return the dict for {"type":"status",...} lines, None for anything else."""
    msg = _load_json_object(line)
    if msg is None or msg.get("type") != "status":
        return None
    return msg


def is_sensor_error(reading: dict) -> bool:
    """A result where the Arduino couldn't measure anything (Round 2: no or failing accelerometer).

    Not the player's fault, so it is neither scored nor logged.
    """
    if reading.get("error"):
        return True
    return reading["round_id"] == ROUND_STEADY and reading.get("actual") is None


def is_resting(reading: dict) -> bool:
    """A Round 2 hold so still the sensor must have been set down, not held.

    Below config.STEADY_REST_MG no human hand is that steady (the table reads
    about 21 mg, a still hand about 68). Rejected in play so "claim 100 and put
    it on the table" can't take the best gap. --calibrate still shows these.
    """
    return (reading["round_id"] == ROUND_STEADY and reading.get("actual") is not None
            and not reading.get("error") and reading["actual"] < config.STEADY_REST_MG)


def report_resting(reading: dict) -> None:
    print(f"   [rejected] Round 2 tremor {reading['actual']:.1f} mg RMS is below "
          f"{config.STEADY_REST_MG:g} mg: the sensor was resting, not held. Pick it up and hold it "
          "in your hand, then press the button again. Not scored or logged.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Round selection (Pi -> Arduino)
# ---------------------------------------------------------------------------
def selection_line(round_id: int) -> bytes:
    """The line that switches the sketch to a round type: b"R1\\n" or b"R2\\n"."""
    if round_id not in config.ROUND_NAMES:
        raise ValueError(f"unsupported round {round_id}")
    return f"R{round_id}\n".encode("ascii")


class RoundSelector:
    """Decides when to (re)send the round selection line.

    - start(): the line to send right after the port opens.
    - on_line(line): feed every line from the Arduino. A matching
      {"state":"mode","round_id":N} ack stops the resends. A boot banner
      ({"state":"ready","accel":...}) means the board reset back to Round 1, so
      the selection is sent again straight away. A mode ack for another round
      is corrected.
    - on_idle(): no ack after config.SERIAL_ACK_TIMEOUT_S -> send again, at most
      config.SERIAL_SELECT_MAX_SENDS times per boot (the sketch only reads
      commands between rounds, and an old sketch never answers).
    Each method returns the bytes to write, or None.
    """

    def __init__(self, round_id: int, ack_timeout_s: Optional[float] = None,
                 max_sends: Optional[int] = None, clock: Callable[[], float] = time.monotonic):
        self.round_id = round_id
        self.line = selection_line(round_id)
        self.ack_timeout_s = config.SERIAL_ACK_TIMEOUT_S if ack_timeout_s is None else ack_timeout_s
        self.max_sends = config.SERIAL_SELECT_MAX_SENDS if max_sends is None else max_sends
        self.clock = clock
        self.acked = False
        self.sends = 0
        self.last_sent = 0.0
        self.gave_up = False

    def start(self) -> bytes:
        self.acked = False
        self.sends = 0
        self.gave_up = False
        return self._send()

    def _send(self) -> Optional[bytes]:
        if self.sends >= self.max_sends:
            if not self.gave_up:
                self.gave_up = True
                print(f"   [warn] the Arduino never acknowledged {self.line.decode().strip()!r} "
                      f"after {self.sends} tries. Is the sketch up to date? (An older, "
                      "Round-1-only sketch ignores the selection; Round 1 still works.)",
                      file=sys.stderr)
            return None
        self.sends += 1
        self.last_sent = self.clock()
        return self.line

    def on_line(self, line: str) -> Optional[bytes]:
        status = parse_status(line)
        if status is None:
            return None
        state = status.get("state")
        if state == "mode":
            if status.get("round_id") == self.round_id:
                self.acked = True
                return None
            self.acked = False
            return self._send()
        if state == "ready" and "accel" in status:     # boot banner: the board just reset
            self.acked = False
            self.sends = 0
            self.gave_up = False
            return self._send()
        return None

    def on_idle(self) -> Optional[bytes]:
        if self.acked or self.clock() - self.last_sent < self.ack_timeout_s:
            return None
        return self._send()


# ---------------------------------------------------------------------------
# Input sources
# ---------------------------------------------------------------------------
def serial_lines(port: str, baud: int, round_id: int = ROUND_REFLEX,
                 serial_module=None) -> Iterator[str]:
    if serial_module is None:
        import serial as serial_module  # pyserial; imported lazily so --mock works without it
    serial = serial_module

    while True:
        try:
            with serial.Serial(port, baud, timeout=1) as ser:
                print(f"Opened {port} @ {baud} baud; waiting {config.SERIAL_OPEN_SETTLE_S}s for the Uno to reset...")
                time.sleep(config.SERIAL_OPEN_SETTLE_S)
                ser.reset_input_buffer()
                selector = RoundSelector(round_id)
                ser.write(selector.start())
                print(f"Selected Round {round_id} ({config.ROUND_NAMES[round_id]}). "
                      f"Ready. {ROUND_INSTRUCTIONS[round_id]}")
                while True:
                    raw = ser.readline()
                    if raw:
                        line = raw.decode("utf-8", errors="replace")
                        out = selector.on_line(line)
                        if out:
                            ser.write(out)
                        yield line
                    out = selector.on_idle()
                    if out:
                        ser.write(out)
        except serial.SerialException as exc:
            print(f"Serial error on {port}: {exc}. Retrying in 2s (Ctrl+C to quit)...")
            time.sleep(2)


def mock_lines(rounds: int, seed: Optional[int], delay_s: float,
               round_id: int = ROUND_REFLEX, dial_step_s: Optional[float] = None) -> Iterator[str]:
    """Emit Arduino-identical JSON lines. Simulates a player whose
    overconfidence shrinks round over round, with the odd false start
    (Round 1) or accelerometer hiccup (Round 2).

    dial_step_s (used with --ui): also simulate the knob turning to each claim
    ({"type":"dial"} lines, dial_step_s apart) and put the claim on "locked", like
    the current sketch. None (the default) keeps the output exactly as before.
    """
    accel = "LIS3DH@0x19" if round_id == ROUND_STEADY else "none"
    yield json.dumps({"type": "status", "state": "mode", "round_id": round_id, "accel": accel})
    if round_id == ROUND_STEADY:
        yield from _mock_steady_lines(rounds, seed, delay_s, dial_step_s)
        return
    rng = random.Random(seed)
    true_ms = rng.gauss(290, 30)                    # this player's "real" speed
    overconfidence = rng.uniform(35, 55)            # starts very delulu
    dial = _MockDial(dial_step_s)
    for seq in range(1, rounds + 1):
        ms = max(120, int(rng.gauss(true_ms, 40)))
        perf_guess = max(0, min(100, (config.REFLEX_SLOW_MS - true_ms) /
                                (config.REFLEX_SLOW_MS - config.REFLEX_FAST_MS) * 100))
        claim = int(max(0, min(100, perf_guess + overconfidence + rng.uniform(-5, 5))))
        overconfidence *= 0.55                      # feedback -> recalibration
        false_start = rng.random() < 0.15
        yield from dial.turn_to(claim)
        yield dial.locked(claim)
        msg = {"type": "result", "round_id": 1, "seq": seq, "claim": claim,
               "actual": None if false_start else ms, "unit": "ms",
               "false_start": false_start, "timeout": False}
        time.sleep(delay_s)
        yield json.dumps(msg)
        yield json.dumps({"type": "status", "state": "ready"})


class _MockDial:
    """--mock --ui: the knob turning to each claim. Disabled (no lines) when step_s is None."""

    STEPS = 8

    def __init__(self, step_s: Optional[float], start: int = 50):
        self.step_s = step_s
        self.value = start

    def turn_to(self, target: int) -> Iterator[str]:
        if self.step_s is None:
            return
        start, last = self.value, None
        for i in range(1, self.STEPS + 1):
            v = round(start + (target - start) * i / self.STEPS)
            if v == last:
                continue
            last = v
            if self.step_s > 0:
                time.sleep(self.step_s)
            yield json.dumps({"type": "dial", "value": v})
        self.value = target

    def locked(self, claim: int) -> str:
        msg = {"type": "status", "state": "locked"}
        if self.step_s is not None:
            msg["claim"] = claim
        return json.dumps(msg)


def _mock_steady_lines(rounds: int, seed: Optional[int], delay_s: float,
                       dial_step_s: Optional[float] = None) -> Iterator[str]:
    rng = random.Random(seed)
    # A real hand measured about 68 mg RMS steady and far more when shaky (docs/calibration);
    # stay above STEADY_REST_MG so mock holds aren't rejected as 'set down on the table'.
    true_mg = rng.uniform(45, 250)                  # this player's real tremor, mg RMS
    overconfidence = rng.uniform(35, 55)
    full_window_samples = 500                       # 5 s at 100 Hz
    dial = _MockDial(dial_step_s)
    for seq in range(1, rounds + 1):
        mg = round(max(40.0, rng.gauss(true_mg, true_mg * 0.25)), 1)
        perf_guess = tremor_mg_to_performance(true_mg)
        claim = int(max(0, min(100, perf_guess + overconfidence + rng.uniform(-5, 5))))
        overconfidence *= 0.55
        hiccup = rng.random() < 0.1                 # I2C trouble -> error result, not scored
        yield from dial.turn_to(claim)
        yield dial.locked(claim)
        for state in ("countdown", "hold"):
            yield json.dumps({"type": "status", "state": state})
        msg = {"type": "result", "round_id": 2, "seq": seq, "claim": claim,
               "actual": None if hiccup else mg, "unit": "mg_rms",
               "peak": None if hiccup else round(mg * rng.uniform(2.5, 4.0), 1),
               "samples": rng.randint(100, 350) if hiccup else full_window_samples,
               "false_start": False, "timeout": False}
        if hiccup:
            msg["error"] = "accel_read"
        time.sleep(delay_s)
        yield json.dumps(msg)
        yield json.dumps({"type": "status", "state": "ready"})


# ---------------------------------------------------------------------------
# Game logic glue
# ---------------------------------------------------------------------------
def describe_reality(result: RoundResult) -> str:
    if result.false_start:
        return "FALSE START (pressed before cue)"
    if result.timeout:
        return "TIMEOUT (no press)"
    if result.round_id == ROUND_STEADY:
        peak = result.extra.get("peak")
        samples = result.extra.get("samples")
        details = []
        if peak is not None:
            details.append(f"peak {peak:.0f} mg")
        if samples is not None:
            details.append(f"{samples} samples")
        extra = f" ({', '.join(details)})" if details else ""
        return f"{result.actual:.1f} mg RMS tremor{extra} -> performance {result.performance:.0f}"
    return f"{result.actual:.0f} ms -> performance {result.performance:.0f}"


def handle_reading(reading: dict, player: str, session_id: str, log: SessionLog,
                   play_audio: bool = True,
                   ui: Optional[ui_server.GameState] = None) -> tuple[RoundResult, int]:
    result = score_reading(reading)
    round_number = log.log_round(session_id, player, result)
    if ui is not None:              # GameState methods never raise
        ui.round_result(result, player, session_id, round_number, log)

    name = config.ROUND_NAMES.get(result.round_id, f"Round {result.round_id}")
    print(f"\n== {player} | round {round_number} | {name} ==")
    print(f"   claim {result.claim} | reality {describe_reality(result)}")
    if result.scored:
        print(f"   gap {result.gap:.0f} | score {result.score} | tier {result.tier} ({result.direction})")
    else:
        print(f"   score {result.score} | tier {result.tier} (no gap; not counted for best/worst gap)")
    if ui is not None:              # show the line in the browser before the audio plays
        deliver_verdict(result, player, play=play_audio, on_text=ui.verdict_text)
    else:
        deliver_verdict(result, player, play=play_audio)
    return result, round_number


def process_reading(reading: dict, player: str, session_id: str, log: SessionLog,
                    play_audio: bool = True, ui: Optional[ui_server.GameState] = None) -> bool:
    """Score, log, narrate and show the leaderboard for one round.

    Any failure (SQLite, writing the mp3, audio playback, ...) is reported on
    stderr and swallowed so the main loop keeps listening for the next round.
    Returns True if the round was handled cleanly.
    """
    try:
        handle_reading(reading, player, session_id, log, play_audio=play_audio, ui=ui)
        print_leaderboard(log)
        return True
    except sqlite3.Error as exc:
        _report_round_error(f"session log (SQLite) error: {exc}. This round may not be saved")
    except OSError as exc:
        _report_round_error(f"file or audio error: {exc}")
    except Exception as exc:  # noqa: BLE001 - never let one bad round end the game
        _report_round_error(f"unexpected {type(exc).__name__}: {exc}", with_traceback=True)
    return False


def _report_round_error(message: str, with_traceback: bool = False) -> None:
    print(f"   [error] round failed: {message}. Still listening for the next round.",
          file=sys.stderr)
    if with_traceback:
        traceback.print_exc(file=sys.stderr)


_SENSOR_ERRORS = {
    "no_accel": "no accelerometer found on I2C. Check the Grove cable is in an I2C port "
                "(SDA/SCL), then press the button again",
    "accel_read": "accelerometer reads kept failing during the hold. Check the Grove I2C cable",
}


def report_sensor_error(reading: dict) -> None:
    code = reading.get("error") or "no_measurement"
    detail = _SENSOR_ERRORS.get(code, "the Arduino reported no measurement")
    samples = reading.get("samples")
    got = f" ({samples} samples)" if samples is not None else ""
    print(f"   [error] Round {reading['round_id']} sensor error '{code}'{got}: {detail}. "
          "Not scored or logged. Still listening.", file=sys.stderr)


def report_status(status: dict, selected_round: int) -> None:
    """Print the interesting Arduino status lines (boot, mode ack, errors)."""
    state = status.get("state")
    accel = status.get("accel")
    if state == "mode":
        rid = status.get("round_id")
        name = config.ROUND_NAMES.get(rid, f"Round {rid}")
        print(f"   Arduino: Round {rid} ({name}) active, accelerometer {accel}")
        if rid == ROUND_STEADY and accel == "none":
            print("   [warn] no accelerometer detected: Round 2 will report sensor errors "
                  "until one is plugged into a Grove I2C port.", file=sys.stderr)
    elif state == "ready" and accel is not None:
        print(f"   Arduino booted (accelerometer {accel}); re-sending the Round {selected_round} selection")
    elif state == "error":
        print(f"   [warn] Arduino reported an error: {status.get('error')}", file=sys.stderr)


class Calibrator:
    """--calibrate: collect raw Round 2 tremor values, no scoring, no logging."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def add(self, reading: dict) -> None:
        mg = reading["actual"]
        self.values.append(mg)
        peak = reading.get("peak")
        peak_s = "-" if peak is None else f"{peak:.1f}"
        print(f"   calib #{len(self.values)}: tremor {mg:.1f} mg RMS | peak {peak_s} mg | "
              f"samples {reading.get('samples', '-')} | (claim {reading['claim']:.0f} ignored)")
        print(f"      so far: min {min(self.values):.1f} | median {statistics.median(self.values):.1f} | "
              f"max {max(self.values):.1f} mg RMS over {len(self.values)} hold(s)")

    def summary(self) -> str:
        if not self.values:
            return "No Round 2 holds recorded."
        return (f"Calibration: {len(self.values)} hold(s), min {min(self.values):.1f}, "
                f"median {statistics.median(self.values):.1f}, max {max(self.values):.1f} mg RMS. "
                f"Current thresholds: STEADY_BEST_MG={config.STEADY_BEST_MG:g} (=100), "
                f"STEADY_WORST_MG={config.STEADY_WORST_MG:g} (=0) in pi/config.py. Put BEST just "
                "above your stillest honest holds and WORST around a clearly shaky hold.")


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
    ap = argparse.ArgumentParser(description="Delulu Detector Pi controller (Round 1: Reflex, Round 2: Steady Hands)")
    ap.add_argument("--port", default=config.SERIAL_PORT, help=f"serial port (default {config.SERIAL_PORT})")
    ap.add_argument("--baud", type=int, default=config.SERIAL_BAUD, help=f"baud rate (default {config.SERIAL_BAUD})")
    ap.add_argument("--player", default="player1", help="player name / id for the session log")
    ap.add_argument("--round", type=int, choices=sorted(config.ROUND_NAMES), default=None,
                    help="round type: 1 = Reflex, 2 = Steady Hands (default 1; 2 with --calibrate)")
    ap.add_argument("--calibrate", action="store_true",
                    help="Round 2 only: print each hold's raw mg values; no scoring, logging or voice")
    ap.add_argument("--mock", action="store_true", help="simulate Arduino serial input (no hardware)")
    ap.add_argument("--rounds", type=int, default=3, help="rounds to simulate with --mock (default 3)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for --mock")
    ap.add_argument("--mock-delay", type=float, default=0.5, help="seconds between mock rounds")
    ap.add_argument("--no-audio", action="store_true", help="don't play audio (TTS/fallback still resolved)")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help=f"SQLite path (default {config.DB_PATH})")
    ap.add_argument("--leaderboard", action="store_true", help="print the leaderboard and exit")
    ap.add_argument("--ui", action="store_true",
                    help="serve the live game state to the browser UI (frontend/) on --ui-port")
    ap.add_argument("--ui-port", type=int, default=config.UI_PORT,
                    help=f"port for --ui (default {config.UI_PORT})")
    ap.add_argument("--ui-host", default=config.UI_HOST,
                    help=f"interface for --ui (default {config.UI_HOST}; 0.0.0.0 = reachable from other devices)")
    args = ap.parse_args(argv)

    if args.calibrate:
        if args.round not in (None, ROUND_STEADY):
            ap.error("--calibrate is for Round 2 (Steady Hands); use --round 2 or leave --round out")
        args.round = ROUND_STEADY
    elif args.round is None:
        args.round = config.DEFAULT_ROUND

    if args.leaderboard:
        with SessionLog(args.db) as log:
            print_leaderboard(log)
        return 0

    # --mock --ui also simulates the knob turning (dial lines); plain --mock output is unchanged.
    mock_extra = {"dial_step_s": config.UI_MOCK_DIAL_STEP_S} if (args.ui and not args.calibrate) else {}
    source = (mock_lines(args.rounds, args.seed, args.mock_delay, args.round, **mock_extra) if args.mock
              else serial_lines(args.port, args.baud, args.round))

    if args.calibrate and args.ui:
        print("   (--ui is not used with --calibrate; ignored)")
    if args.calibrate:
        print(f"Delulu Detector | CALIBRATION (Round 2 raw mg, nothing scored or logged) | "
              f"thresholds best {config.STEADY_BEST_MG:g} / worst {config.STEADY_WORST_MG:g} mg RMS")
        return _run_calibration(source, args.round)

    log = SessionLog(args.db)
    if log.migration_backup is not None:
        print(f"Upgraded {args.db} to schema v2 (new columns only); copy of the old file: {log.migration_backup}")
    session_id = new_session_id()
    key_state = "set" if config.ELEVENLABS_API_KEY else "NOT set -> fallback verdicts"
    print(f"Delulu Detector | session {session_id} | player {args.player} | "
          f"Round {args.round} ({config.ROUND_NAMES[args.round]}) | db {args.db}")
    print(f"ElevenLabs key {key_state} | TTS timeout {config.ELEVENLABS_TIMEOUT_S}s")
    ui, ui_srv = start_ui(args, session_id, log)

    try:
        for line in source:
            dial = parse_dial(line)
            if dial is not None:                     # live knob: UI only, never printed
                if ui is not None:
                    ui.dial(dial)
                continue
            status = parse_status(line)
            if status is not None:
                report_status(status, args.round)
                if ui is not None:
                    ui.on_status(status)
                continue
            reading = parse_line(line)
            if reading is None:
                continue
            rid = reading["round_id"]
            if rid not in config.ROUND_NAMES:
                print(f"   (ignoring round_id {rid}: only rounds {sorted(config.ROUND_NAMES)} are implemented)")
                continue
            if rid != args.round:
                print(f"   (note: got a Round {rid} result while Round {args.round} is selected; "
                      f"the Arduino hasn't switched yet. Scoring it as Round {rid}.)")
            if is_sensor_error(reading):
                report_sensor_error(reading)
                if ui is not None:
                    ui.round_rejected(ui_sensor_error_message(reading))
                continue
            if is_resting(reading):
                report_resting(reading)
                if ui is not None:
                    ui.round_rejected("Sensor was resting on the table, not held. Pick it up and "
                                      "hold it, then press the button again. Not scored.")
                continue
            process_reading(reading, args.player, session_id, log, play_audio=not args.no_audio, ui=ui)
            if ui is not None and args.mock:
                time.sleep(config.UI_MOCK_PAUSE_S)      # let the reveal be seen between mock rounds
        if ui_srv is not None and args.mock:
            linger_for_ui(ui_srv)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        if ui_srv is not None:
            ui_srv.stop()
        try:
            series = log.calibration_series(args.player, session_id)
            if series:
                print(f"\nCalibration series for {args.player} this session (round, gap): {series}")
        except sqlite3.Error as exc:
            print(f"   [error] could not read the calibration series: {exc}", file=sys.stderr)
        log.close()
    return 0


def start_ui(args, session_id: str, log: SessionLog):
    """--ui: create the live state and start the HTTP server. (None, None) without --ui.

    If the server can't start (port taken, ...) the state is still returned so the
    game runs exactly the same; nothing about the UI can stop a round.
    """
    if not getattr(args, "ui", False):
        return None, None
    state = ui_server.GameState()
    state.session_started(args.player, args.round, session_id, mock=args.mock)
    state.refresh_from_log(log)
    srv = ui_server.UIServer(state, host=args.ui_host, port=args.ui_port)
    if not srv.start():
        return state, None
    if srv.serving_frontend:
        print(f"UI: open {srv.url} in a browser (live state at {srv.url}/api/state)")
    else:
        print(f"UI: state at {srv.url}/api/state; no frontend/dist yet, so run the dev server: "
              "cd frontend && npm run dev (or npm run build once to serve it from here)")
    return state, srv


def linger_for_ui(srv) -> None:
    """--mock --ui: the simulated rounds are done; keep serving the UI until Ctrl+C."""
    print(f"Mock rounds finished. The UI stays up at {srv.url} (Ctrl+C to quit).")
    while True:
        time.sleep(3600)


def ui_sensor_error_message(reading: dict) -> str:
    code = reading.get("error") or "no_measurement"
    detail = _SENSOR_ERRORS.get(code, "the Arduino reported no measurement")
    return f"Sensor error ({code}): {detail}. Not scored."


def _run_calibration(source: Iterator[str], selected_round: int) -> int:
    calibrator = Calibrator()
    try:
        for line in source:
            status = parse_status(line)
            if status is not None:
                report_status(status, selected_round)
                continue
            reading = parse_line(line)
            if reading is None:
                continue
            if reading["round_id"] != ROUND_STEADY:
                print(f"   (calibrate: ignoring a Round {reading['round_id']} result; "
                      "the Arduino hasn't switched to Round 2 yet)")
                continue
            if is_sensor_error(reading):
                report_sensor_error(reading)
                continue
            calibrator.add(reading)
    except KeyboardInterrupt:
        print("\nStopping.")
    print(f"\n{calibrator.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
