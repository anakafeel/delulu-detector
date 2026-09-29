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
# with `python pi/main.py --round 2 --calibrate`. One session, one player:
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

# --------------------------------------------------------------------------
# Round 5 (Poker Face): webcam on the Pi, OpenCV Haar cascades, fully local.
# The Arduino only locks the claim; the Pi watches the player's face for
# POKER_WINDOW_S while a joke plays and measures
#     smile_frac = frames with a (smoothed) smile / frames with a face.
# !! STARTING GUESSES, TO BE CALIBRATED ON HARDWARE !! Run
#    python pi/main.py --round 5 --calibrate
# with a few honest stone-face windows and a few where you let yourself laugh,
# then set these from the numbers (the smile cascade has a false-positive floor
# that depends on the camera, the light and the person).
# --------------------------------------------------------------------------
POKER_BEST_FRAC = 0.03    # smiling this little or less = 100 (perfect poker face)
POKER_WORST_FRAC = 0.40   # smiling this much or more = 0 (cracked completely)
POKER_WINDOW_S = 6.0      # measurement window; also sent to the sketch as "W6000" (1-30 s)
POKER_MIN_FACE_FRAC = 0.5 # a face in fewer than half the frames = "no_face" error (not scored)

# Webcam + detector. Frames are processed in memory only: never saved, never sent anywhere.
# Webcam for cv2.VideoCapture(index). 0 = usually the built-in camera; an external USB
# webcam gets the next free index (on our laptop the Logitech Brio 101 is 2, /dev/video2).
# Override per run with --camera N, or with DELULU_CAMERA_INDEX in .env.
POKER_CAMERA_INDEX = int(_env_float("DELULU_CAMERA_INDEX", 0))
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
# Where the Haar cascade XMLs live. Empty = cv2.data.haarcascades (pip opencv-python).
# Set it for builds without cv2.data, e.g. /usr/share/opencv4/haarcascades.
CASCADE_DIR = os.environ.get("DELULU_CASCADE_DIR", "").strip()
FACE_CASCADE = "haarcascade_frontalface_default.xml"
SMILE_CASCADE = "haarcascade_smile.xml"
# Face search runs on a copy downscaled to this width (speed: the Pi 4 needs ~10-15 fps).
VISION_DETECT_WIDTH = 320
FACE_SCALE_FACTOR = 1.1
FACE_MIN_NEIGHBORS = 5
FACE_MIN_SIZE_FRAC = 0.10         # smallest face, as a fraction of the downscaled frame width (32 px at 320)
# Smile search runs on the lower half of the largest face, cut from the FULL-resolution
# frame and resized to SMILE_ROI_WIDTH px wide, so the parameters below behave the same
# whatever the distance to the camera. Few, strict detections: high minNeighbors.
# Offline check (2026-09-26, opencv 4.14, a smiling and a neutral test photo at 45
# sizes / angles / exposures): 160 / 1.7 / 20 found the smile in 86% of face frames
# with 0% false smiles on the neutral face, and stayed that way for minNeighbors
# 10-30. Wider ROIs or smaller scale factors raised the false smiles. Still: verify
# on the real camera and faces with --calibrate / --preview.
SMILE_ROI_WIDTH = 160
SMILE_SCALE_FACTOR = 1.7
SMILE_MIN_NEIGHBORS = 20
SMILE_MIN_W_FRAC = 0.20           # smallest smile box, as a fraction of the face width
SMILE_MIN_H_FRAC = 0.10           # (the cascade's own window is 36x18 px, i.e. 0.225 x 0.11 at 160)
# Per-frame smoothing: a frame only counts as smiling if the raw detector saw a
# smile in at least SMILE_SMOOTH_HITS of the last SMILE_SMOOTH_FRAMES face frames.
SMILE_SMOOTH_FRAMES = 3
SMILE_SMOOTH_HITS = 2

# --------------------------------------------------------------------------
# Round 3 in the game (internal round id 6): Straight Face Under Pressure.
# Webcam on the Pi, frame differencing, fully local. The dial claims how many
# seconds the player can keep a neutral face while rapid-fire interview questions
# play: dial 0-100 maps linearly to 0-STRAIGHT_MAX_S seconds. The Pi measures
# the seconds until the face visibly changes:
#   1. baseline: the first STRAIGHT_BASELINE_S of face frames define the player's
#      neutral face (a small grayscale crop of the face box, resized to
#      STRAIGHT_SIG_SIZE px so it's normalized by face size, brightness removed);
#   2. every later face frame is compared with that neutral face (mean absolute
#      difference over the whole face and over the mouth region, the larger wins);
#   3. an expression change = STRAIGHT_HOLD_FRAMES frames in a row above
#      max(STRAIGHT_MIN_DIFF, baseline mean + STRAIGHT_K * baseline std);
#      a smoothed Haar smile also counts (STRAIGHT_SMILE_BREAKS).
# held = seconds from the start of the window to the change (STRAIGHT_MAX_S if none).
# !! STARTING GUESSES, TO BE CALIBRATED ON HARDWARE !! Run
#    python pi/main.py --round 6 --calibrate [--camera 2]     (or --video clip.mp4)
# and compare the printed peak scores of calm windows with ones where you reacted.
# --------------------------------------------------------------------------
STRAIGHT_MAX_S = 20.0         # dial 100 = this many seconds; also the longest window (sketch: 1-30 s)
STRAIGHT_BASELINE_S = 1.0     # neutral-face baseline at the start of each window
STRAIGHT_MIN_BASELINE_FRAMES = 5   # fewer face frames than this in the baseline = "no_face"
STRAIGHT_BASELINE_TIMEOUT_S = 4.0  # ...searched for at most this long
STRAIGHT_K = 4.0              # threshold = baseline mean + K * baseline std ...
STRAIGHT_MIN_DIFF = 9.0       # ... but never below this (0-255 gray levels, mean abs diff)
STRAIGHT_HOLD_FRAMES = 3      # consecutive frames over the threshold = a change (ignores one-frame blips)
STRAIGHT_SMILE_BREAKS = True  # a smoothed Haar smile also ends the hold
STRAIGHT_SIG_SIZE = 48        # face crop is resized to this many px square
STRAIGHT_MOUTH_FROM = 0.55    # mouth region = the face crop's rows from this fraction down
STRAIGHT_TAIL_S = 0.6         # keep the camera stream going this long after a change (the marker)
STRAIGHT_QUESTION_GAP_S = 0.3 # pause between the rapid-fire question clips

# Round types the Pi can score, and their display names (internal ids; the ids
# are stored in the session log, so they never change).
ROUND_NAMES = {1: "Reflex", 2: "Steady Hands", 5: "Poker Face", 6: "Straight Face"}
# What the Hill's game: these rounds, labelled 1 / 2 / 3 on screen and in the terminal.
GAME_ROUNDS = (1, 5, 6)
ROUND_LABELS = {1: 1, 5: 2, 6: 3}
# Cut from the game in the pivot (they don't read the face). Still in the code and
# the sketch, runnable with --legacy-rounds (e.g. --legacy-rounds --round 2).
LEGACY_ROUNDS = (2,)
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
# Speaking rate sent as voice_settings.speed (ElevenLabs accepts 0.7-1.2; 1.0 = the voice's own
# pace, and then no voice_settings are sent at all). George at 1.0 pauses long at every period;
# 1.15 measured about 9% shorter on the same line with no change in response time.
ELEVENLABS_SPEED = min(1.2, max(0.7, _env_float("ELEVENLABS_SPEED", 1.15)))

# Presage SmartSpectra. The key only authorizes the on-device SDK.
# Official name is SMARTSPECTRA_API_KEY. PRESAGE_API_KEY is accepted too.
PRESAGE_API_KEY = (os.environ.get("SMARTSPECTRA_API_KEY")
                   or os.environ.get("PRESAGE_API_KEY") or "").strip()
if PRESAGE_API_KEY:
    os.environ["SMARTSPECTRA_API_KEY"] = PRESAGE_API_KEY
PRESAGE_READY_TIMEOUT_S = _env_float("PRESAGE_READY_TIMEOUT_S", 20.0)

# --------------------------------------------------------------------------
# Paths / audio
# --------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("DELULU_DB_PATH", REPO_ROOT / "data" / "sessions.db"))
# Optional Tiger Data (Timescale) copy of every scored round: calibration curve + leaderboard from
# a continuous aggregate (pi/tiger_store.py). Empty = off; SQLite above is always the game's log.
TIGER_DATA_URL = os.environ.get("TIGER_DATA_URL", "").strip()
ASSETS_DIR = REPO_ROOT / "assets"
# Generic pre-recorded fallback. Optional per-tier files are also picked up if
# present: assets/fallback_validated.mp3, fallback_mild.mp3, fallback_spicy.mp3,
# fallback_delulu.mp3. Round-specific files win over those if present:
# assets/fallback_round2_<tier>.mp3 / fallback_round5_<tier>.mp3 (for example fallback_round2_delulu.mp3).
FALLBACK_AUDIO = ASSETS_DIR / "fallback_verdict.mp3"
# Interview-question clips, if present. A missing clip means that round's prompt is silent.
#   assets/questions/poker_XX.mp3     one random tough question at the start of each
#                                     Poker Face window (non-blocking)
#   assets/questions/pressure_XX.mp3  Straight Face: played back to back, rapid fire
# Missing clips = silence, the rounds still run.
QUESTIONS_DIR = ASSETS_DIR / "questions"
# Before the pivot Poker Face played jokes from here; still used if there are no
# poker_XX.mp3 clips yet, so an older machine keeps working until it regenerates.
JOKES_DIR = ASSETS_DIR / "jokes"
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
# Poker Face with --ui: the player types their name on the booth screen before dialing
# (POST /api/player). Until someone does, and again after UI_IDLE_AFTER_S with no activity,
# rounds are logged under this name. Without --ui, --player is used as before.
UI_DEFAULT_PLAYER = "Guest"
UI_PLAYER_NAME_MAX = 16    # characters kept from a typed name (it has to fit the leaderboard)
# Opt-in leaderboard photo (Poker Face with --ui): a player who presses Y after typing their name gets
# one webcam frame from this far into the question, shown when their name is clicked. Memory only:
# never written to disk, SQLite or Tiger Data, and gone when the game stops.
PHOTO_AT_S = 3.0
UI_PHOTO_MAX = 200         # photos kept (oldest dropped first)

# Live camera in the browser for the face rounds (--ui with a real camera or --video):
# GET /api/camera.mjpg. The stream reuses the frames the measurement already reads (the camera is
# never opened twice). Frames stay in memory, one at a time; nothing is ever written to disk.
UI_CAMERA_FPS = 12.0          # stream rate per browser (the measurement itself runs at camera speed)
UI_CAMERA_MAX_WIDTH = 640     # frames wider than this are scaled down before JPEG encoding
UI_CAMERA_JPEG_QUALITY = 70   # 0-100
UI_CAMERA_MIRROR = True       # flip horizontally like a selfie (boxes and text stay readable)
UI_CAMERA_IDLE_PREVIEW = os.environ.get("DELULU_CAMERA_PREVIEW", "1") != "0"
#   ^ also show the camera while the claim is being set (only while a browser is watching, never
#     during a measurement window), so the player can frame their face before locking.
#     DELULU_CAMERA_PREVIEW=0 in .env: frames only during the measured window.
UI_CAMERA_IDLE_FPS = 10.0     # camera reads + face detection per second for that preview
