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

# --------------------------------------------------------------------------
# Round 1 (Reflex): reaction ms -> 0-100 performance. THE one place to tune it.
# --------------------------------------------------------------------------
REFLEX_FAST_MS = 150   # this fast or faster = 100
REFLEX_SLOW_MS = 600   # this slow or slower = 0 (linear in between, clamped)

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
# fallback_delulu.mp3.
FALLBACK_AUDIO = ASSETS_DIR / "fallback_verdict.mp3"
TTS_OUTPUT_DIR = REPO_ROOT / "data" / "tts"
# Command used to play mp3s. Empty = auto-detect mpg123 / ffplay / mpv / cvlc.
AUDIO_PLAYER = os.environ.get("DELULU_AUDIO_PLAYER", "").strip()
