"""Single place for every tunable number on the Pi side.

Values that are secrets or differ per machine come from the environment
(.env at the repo root is loaded automatically); everything else is a plain
constant you can edit here.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional at import time (tests still work)
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --------------------------------------------------------------------------
# Serial link (must match SERIAL_BAUD in arduino/delulu_gauntlet/delulu_gauntlet.ino)
# --------------------------------------------------------------------------
SERIAL_PORT = os.environ.get("DELULU_SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = 115200
# Opening the port resets an Uno; give the bootloader time before listening.
SERIAL_OPEN_SETTLE_S = 2.0
# After sending the round selection line (R1 / R2), wait this long for the
# Arduino's {"type":"status","state":"mode",...} ack before sending it again.
# The sketch only reads commands between rounds, so a round in progress delays it.
SERIAL_ACK_TIMEOUT_S = 3.0
SERIAL_SELECT_MAX_SENDS = 4

# --------------------------------------------------------------------------
# Round 1 (Reflex): reaction ms -> 0-100 performance. THE one place to tune it.
# --------------------------------------------------------------------------
REFLEX_FAST_MS = 150   # this fast or faster = 100
REFLEX_SLOW_MS = 600   # this slow or slower = 0 (linear in between, clamped)

# --------------------------------------------------------------------------
# Round 2 (Steady Hands): tremor (mg RMS) -> 0-100 performance.
# The Arduino reports the RMS of each accelerometer sample's deviation from the
# 5 s window's mean vector, in mg (gravity and orientation drop out).
# Calibrated on hardware 2026-09-26 (Grove LIS3DHTR at 0x19, +-2 g high-res, 100 Hz)
# with `python pi/main.py --round 2 --calibrate`; raw output is in
# docs/calibration/round2-2026-09-26.md. One session, one player:
#    sensor lying on the table (incl. the button press)  ~21 mg RMS
#    held as still as possible in the hand               ~68 mg RMS
#    shaken hard                                        ~1494 mg RMS
# A hand always has some physiological tremor, so anything below STEADY_REST_MG
# means the sensor was set down, not held: that hold is rejected (not scored,
# logged or spoken), so "claim 100 and put it on the table" can't win.
# BEST sits just above REST, so a genuinely steady hand scores in the 90s.
# Re-run --calibrate with more players before a demo and adjust all three.
# (Another part, e.g. ADXL345 or MPU-6050, has a different noise floor: recalibrate.)
# --------------------------------------------------------------------------
STEADY_REST_MG = 30.0    # below this (mg RMS) = sensor resting, not held -> rejected
STEADY_BEST_MG = 35.0    # this steady or steadier (mg RMS) = 100
STEADY_WORST_MG = 500.0  # this shaky or shakier (mg RMS) = 0

# Round types the Pi can score, and their display names.
ROUND_NAMES = {1: "Reflex", 2: "Steady Hands"}
DEFAULT_ROUND = 1

# A false start (pressed before the cue) or a timeout (never pressed) always
# scores this, whatever the claim. There is no measured performance, so the
# round gets no performance and no gap (both NULL in the log). Its tier stays
# "false_start" or "timeout". It still counts toward rounds played and toward
# the average score (as this value), but it is left out of best gap, worst gap,
# "most delulu" and the calibration series.
# (Scoring these as performance 0 used to let a claim of 0 plus a false start
# or timeout earn gap 0, a perfect 100, and the best gap on the leaderboard.)
FAILED_ROUND_SCORE = 0

# --------------------------------------------------------------------------
# Verdict tiers: (max_gap_inclusive, tier_name). Checked in order.
# --------------------------------------------------------------------------
GAP_TIERS = [
    (10.0, "validated"),
    (25.0, "mild"),
    (45.0, "spicy"),
    (100.0, "delulu"),
]

# --------------------------------------------------------------------------
# ElevenLabs
# --------------------------------------------------------------------------
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
# Default: "George", a premade ElevenLabs voice used in their API docs.
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip()
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5").strip()
ELEVENLABS_BASE_URL = os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
# If the TTS call takes longer than this, give up and use the fallback line.
ELEVENLABS_TIMEOUT_S = _env_float("ELEVENLABS_TIMEOUT_S", 3.0)

# --------------------------------------------------------------------------
# Paths / audio
# --------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("DELULU_DB_PATH", REPO_ROOT / "data" / "sessions.db"))
ASSETS_DIR = REPO_ROOT / "assets"
# Generic pre-recorded fallback. Optional per-tier files are also picked up if
# present: assets/fallback_validated.mp3, fallback_mild.mp3, fallback_spicy.mp3,
# fallback_delulu.mp3. Round-specific files win over those if present:
# assets/fallback_round2_<tier>.mp3 (for example fallback_round2_delulu.mp3).
FALLBACK_AUDIO = ASSETS_DIR / "fallback_verdict.mp3"
TTS_OUTPUT_DIR = REPO_ROOT / "data" / "tts"
# Command used to play mp3s. Empty = auto-detect mpg123 / ffplay / mpv / cvlc.
AUDIO_PLAYER = os.environ.get("DELULU_AUDIO_PLAYER", "").strip()

# --------------------------------------------------------------------------
# Browser UI (python pi/main.py --ui): live game state for frontend/
# --------------------------------------------------------------------------
UI_HOST = os.environ.get("DELULU_UI_HOST", "127.0.0.1")   # 0.0.0.0 to show it on another device
UI_PORT = int(_env_float("DELULU_UI_PORT", 8765))
UI_STATIC_DIR = REPO_ROOT / "frontend" / "dist"            # `npm run build` output; served at /
UI_REVEAL_HOLD_S = 15.0    # keep the result on screen this long (unless the next round starts sooner)
UI_REVEAL_MIN_S = 4.0      # ...but turning the dial after this long goes straight to the next claim
UI_IDLE_AFTER_S = 90.0     # no activity for this long while armed -> back to the idle/attract screen
UI_HISTORY_LIMIT = 300     # most recent logged rounds sent to the browser (leaderboard + curve)
UI_MOCK_PAUSE_S = 5.0      # --mock --ui: pause after each result so the reveal can be seen
UI_MOCK_DIAL_STEP_S = 0.15  # --mock --ui: simulated knob turn, seconds between dial lines
