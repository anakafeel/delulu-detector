"""Straight Face Under Pressure (The Tell's Round 3, internal id 6) on the Pi.

The Arduino only locks the claim (0-100 on the dial = 0-STRAIGHT_MAX_S seconds)
and prints
    {"type":"claim","round_id":6,"seq":N,"claim":40}
then shows its cue for up to STRAIGHT_MAX_S seconds. StraightRound.run() then:
  1. starts the rapid-fire interview questions (assets/questions/pressure_XX.mp3,
     shuffled, back to back in a background thread; silent if there are none or
     audio is off),
  2. watches the webcam (vision.measure_straight_face): a short neutral-face
     baseline, then the seconds until the face region differs from it by more
     than the threshold for a few frames in a row (or a smoothed smile),
  3. on a change: stops the questions and calls on_change (main.py sends "S" so
     the sketch ends its cue early), keeps the overlay up for STRAIGHT_TAIL_S,
  4. returns a result dict in main.parse_line()'s shape:
       {"type":"result","round_id":6,"seq":N,"claim":40.0,"actual":6.4,"unit":"s",
        "held_s":6.4,"max_s":20.0,"broke":true,"trigger":"expression","face_frac":0.98,
        "frames":105,"fps":14.8,"threshold":9.0,"peak_score":31.2,...,
        "false_start":false,"timeout":false}
     plus "error":"no_face" (no neutral baseline, or a face in fewer than
     POKER_MIN_FACE_FRAC of the frames) or "error":"camera_read". Errors are not
     scored, logged or spoken, exactly like Poker Face.
Frames never leave this process; with --ui they go to the same browser stream as
Poker Face (camera_feed kind "straight": timer, level bar, change marker).
"""
from __future__ import annotations

import random
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import config
import elevenlabs_client as ec
import vision
from poker_round import (FaceRound, LivePrompt, PresageError, _apply_presage, _open_presage,
                         _presage_failure, open_source, question_files, start_audio,
                         stop_audio, window_line)
from scoring import ROUND_STRAIGHT, claim_to_seconds


def straight_window_line(max_s: Optional[float] = None) -> bytes:
    """b"W20000\\n": the longest the sketch shows the Straight Face cue (the Pi ends it early with S)."""
    return window_line(config.STRAIGHT_MAX_S if max_s is None else max_s, name="STRAIGHT_MAX_S")


STOP_CUE_LINE = b"S\n"           # Pi -> sketch: the face changed, end the cue now


# ---------------------------------------------------------------------------
# Rapid-fire questions
# ---------------------------------------------------------------------------
class QuestionBarrage:
    """Plays clips back to back (reshuffled every pass) in a daemon thread until stop().

    stop() never blocks the caller for long: it flags the thread and kills the
    clip that is playing; join() waits for the thread (called after the window).
    """

    def __init__(self, files: list[Path], start_audio_fn: Callable[[Path], object] = start_audio,
                 stop_audio_fn: Callable[[object], None] = stop_audio,
                 gap_s: Optional[float] = None, rng: Optional[random.Random] = None,
                 poll_s: float = 0.05):
        self.files = list(files)
        self._start_audio = start_audio_fn
        self._stop_audio = stop_audio_fn
        self.gap_s = config.STRAIGHT_QUESTION_GAP_S if gap_s is None else float(gap_s)
        self.rng = rng or random.Random()
        self.poll_s = poll_s
        self.played: list[Path] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._proc = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "QuestionBarrage":
        if self.files and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="tell-questions", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                order = self.files[:]
                self.rng.shuffle(order)
                for path in order:
                    if self._stop.is_set():
                        return
                    proc = self._start_audio(path)
                    if proc is None:
                        return                     # no audio player: stay silent
                    with self._lock:
                        self._proc = proc
                    self.played.append(path)
                    poll = getattr(proc, "poll", None)
                    while poll is not None and poll() is None and not self._stop.is_set():
                        self._stop.wait(self.poll_s)
                    with self._lock:
                        self._proc = None
                    self._stop_audio(proc)
                    self._stop.wait(self.gap_s)
        except Exception as exc:  # noqa: BLE001 - the questions must never take the round down
            print(f"   [warn] question playback stopped ({type(exc).__name__}: {exc})", file=sys.stderr)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None:
            try:
                self._stop_audio(proc)
            except Exception:  # noqa: BLE001
                pass

    def join(self, timeout: float = 2.0) -> None:
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None


# ---------------------------------------------------------------------------
# One round
# ---------------------------------------------------------------------------
class StraightRound(FaceRound):
    """Camera + detector + face signature + question barrage for a whole session."""

    round_id = ROUND_STRAIGHT
    feed_kind = "straight"

    def __init__(self, camera, detector, signature, max_s: Optional[float] = None,
                 clock: Callable[[], float] = time.monotonic, play_questions: bool = True,
                 questions_dir: Optional[Path] = None,
                 preview: Optional[vision.PreviewWindow] = None,
                 rng: Optional[random.Random] = None,
                 start_audio_fn: Callable[[Path], object] = start_audio,
                 stop_audio_fn: Callable[[object], None] = stop_audio,
                 tracker_factory: Optional[Callable[[], vision.ExpressionTracker]] = None,
                 on_change: Optional[Callable[[float, str], None]] = None):
        super().__init__(camera, detector, config.STRAIGHT_MAX_S if max_s is None else max_s,
                         clock=clock, preview=preview, rng=rng,
                         start_audio_fn=start_audio_fn, stop_audio_fn=stop_audio_fn)
        self.signature = signature
        self.play_questions = play_questions
        self.questions_dir = questions_dir
        self.tracker_factory = tracker_factory or (lambda: vision.ExpressionTracker(signature.distance))
        self.on_change = on_change            # main.py: send "S" to the sketch
        self.last_barrage: Optional[QuestionBarrage] = None

    @property
    def max_s(self) -> float:
        return self.window_s

    def question_files(self) -> list[Path]:
        return question_files("pressure", self.questions_dir)

    def _measure_locked(self) -> vision.StraightStats:
        barrage = None
        wants_preview = self.preview is not None and self.preview.enabled
        on_frame = self._on_frame if (wants_preview or self.feed is not None or self.presage is not None) else None
        if self.feed is not None:
            self.feed.begin("measuring", self.window_s, kind="straight")     # never raises
        try:
            self.camera.begin_window()
            if self.play_questions and self.questions_dir is None:
                barrage = LivePrompt(ec.PRESSURE_QUESTION_LINES, self.rng, self._start_audio,
                                     self._stop_audio, on_text=self.on_prompt, on_fail=self.on_prompt_fail,
                                     repeat=True).start()
                self.last_live = barrage
            elif self.play_questions:
                barrage = QuestionBarrage(self.question_files(), self._start_audio, self._stop_audio,
                                          rng=self.rng).start()
                self.last_barrage = barrage

            def changed(t: float, trigger: str) -> None:
                if barrage is not None:
                    barrage.stop()                # the gotcha: silence, then the verdict
                live = getattr(self, "last_live", None)
                if live is not None:
                    live.stop()
                if self.on_change is not None:
                    self.on_change(t, trigger)

            return vision.measure_straight_face(self.camera, self.detector, self.signature,
                                                self.window_s, clock=self.clock,
                                                tracker=self.tracker_factory(),
                                                on_frame=on_frame, on_change=changed)
        finally:
            if barrage is not None:
                barrage.join()
            live = getattr(self, "last_live", None)
            if live is not None and live is not barrage:
                live.join()
            if self.preview is not None:
                self.preview.close()
            if self.feed is not None:
                self.feed.end("measuring")

    def _on_frame(self, frame, obs, info: dict) -> None:
        if self.presage is not None:
            self.presage.push(frame)
            latest = self.presage.latest()
            if latest is not None:
                info = {**info, "composure": round(latest, 1)}
        if self.preview is not None and self.preview.enabled:
            self.preview.show(frame, obs, info.get("smiling", False), info.get("elapsed", 0.0),
                              self.window_s)      # never raises
        if self.feed is not None:
            self.feed.offer(frame, obs, info.get("smiling", False), info.get("elapsed", 0.0),
                            extra=info)           # never raises

    def run(self, claim_msg: dict) -> dict:
        try:
            stats = self.measure()
        except PresageError as exc:
            return _presage_failure(claim_msg, self.round_id, exc)
        reading = reading_from_straight(claim_msg, stats)
        return _apply_presage(self.presage, reading)


def reading_from_straight(claim_msg: dict, stats: vision.StraightStats,
                          min_face_frac: Optional[float] = None) -> dict:
    """Result dict (main.parse_line shape) for one Straight Face window."""
    min_face_frac = config.POKER_MIN_FACE_FRAC if min_face_frac is None else min_face_frac

    def r(v, nd=2):
        return None if v is None else round(float(v), nd)

    reading = {
        "type": "result", "round_id": ROUND_STRAIGHT, "seq": claim_msg.get("seq"),
        "claim": float(claim_msg["claim"]), "actual": None, "unit": "s",
        "held_s": None, "max_s": stats.max_s, "broke": stats.broke, "trigger": stats.trigger,
        "face_frac": round(stats.face_frac, 4), "frames": stats.frames, "fps": round(stats.fps, 1),
        "threshold": r(stats.threshold), "peak_score": r(stats.peak_score),
        "baseline_mean": r(stats.baseline_mean), "baseline_std": r(stats.baseline_std),
        "false_start": False, "timeout": False,
    }
    if stats.frames == 0:
        reading["error"] = "camera_read"
    elif not stats.baseline_ok or stats.face_frac < min_face_frac:
        reading["error"] = "no_face"
    elif not stats.completed:
        reading["error"] = "camera_read"          # the camera stopped delivering mid-window
    else:
        reading["held_s"] = reading["actual"] = round(stats.held_s, 2)
    return reading


# ---------------------------------------------------------------------------
# Factory used by main.py
# ---------------------------------------------------------------------------
def build(mock: bool, camera_index: Optional[int] = None, preview: bool = False,
          play_questions: bool = True, seed: Optional[int] = None,
          max_s: Optional[float] = None, video: Optional[str] = None,
          require_presage: bool = True) -> StraightRound:
    """Real webcam (or video=path) + Haar detector + FaceSignature, or (mock=True, no
    video) scripted frames on a virtual clock. Raises vision.VisionUnavailable."""
    max_s = config.STRAIGHT_MAX_S if max_s is None else float(max_s)
    straight_window_line(max_s)                    # must fit the sketch: 1-30 s (raises ValueError)
    rng = random.Random(seed)
    if mock and not video:
        cam = vision.MockStraightCamera(seed, max_s)
        return StraightRound(cam, vision.FakeDetector(), vision.FakeSignature(), max_s,
                             clock=cam.now, play_questions=play_questions, rng=rng)
    camera, detector, clock = open_source(camera_index, video)
    session = _open_presage(camera, require_presage)
    game = StraightRound(camera, detector, vision.FaceSignature(), max_s, clock=clock,
                         play_questions=play_questions,
                         preview=vision.PreviewWindow(True) if preview else None, rng=rng)
    game.presage = session
    return game


# ---------------------------------------------------------------------------
# --calibrate --round 6
# ---------------------------------------------------------------------------
class StraightCalibrator:
    """Per-window raw numbers for tuning STRAIGHT_MIN_DIFF / STRAIGHT_K. No scoring, logging, voice."""

    def __init__(self) -> None:
        self.windows = 0
        self.calm_peaks: list[float] = []         # windows that held to the end: the noise ceiling
        self.change_peaks: list[float] = []       # windows that ended on an expression change
        self.noise: list[float] = []              # baseline mean + std
        self.fps: list[float] = []

    def add(self, reading: dict) -> None:
        self.windows += 1
        err = reading.get("error")
        base = ("-" if reading.get("baseline_mean") is None
                else f"{reading['baseline_mean']:.1f}+/-{reading['baseline_std']:.1f}")
        thr = "-" if reading.get("threshold") is None else f"{reading['threshold']:.1f}"
        if err:
            what = f"[{err}: would not be scored, left out of the stats]"
        elif reading.get("broke"):
            what = f"changed at {reading['held_s']:.2f} s ({reading.get('trigger')})"
        else:
            what = f"held the full {reading['max_s']:g} s"
        claim_s = claim_to_seconds(reading["claim"], reading.get("max_s"))
        print(f"   calib #{self.windows}: {what} | baseline {base} | threshold {thr} | "
              f"peak {reading.get('peak_score') or 0:.1f} | face_frac {reading['face_frac']:.2f} | "
              f"fps {reading['fps']:.1f} ({reading['frames']} frames) | "
              f"(claim {reading['claim']:.0f} = {claim_s:.1f} s ignored)")
        if err:
            if err == "no_face":
                print("      face the camera (good light, nothing over your face) and try again",
                      file=sys.stderr)
            return
        peak = reading.get("peak_score") or 0.0
        if reading.get("broke") and reading.get("trigger") == "expression":
            self.change_peaks.append(peak)
        elif not reading.get("broke"):
            self.calm_peaks.append(peak)
        if reading.get("baseline_mean") is not None:
            self.noise.append(reading["baseline_mean"] + reading["baseline_std"])
        self.fps.append(reading["fps"])
        if reading["fps"] < 8:
            print("      [warn] under 8 fps: lower VISION_DETECT_WIDTH in pi/config.py", file=sys.stderr)

    def summary(self) -> str:
        if not (self.calm_peaks or self.change_peaks):
            return "No usable Straight Face windows recorded."
        parts = [f"Calibration: {len(self.calm_peaks) + len(self.change_peaks)} window(s)"]
        if self.calm_peaks:
            parts.append(f"held-to-the-end peak scores max {max(self.calm_peaks):.1f} "
                         f"(median {statistics.median(self.calm_peaks):.1f})")
        if self.change_peaks:
            parts.append(f"expression-change peaks min {min(self.change_peaks):.1f} "
                         f"(median {statistics.median(self.change_peaks):.1f})")
        if self.noise:
            parts.append(f"baseline noise (mean+std) median {statistics.median(self.noise):.1f}")
        if self.fps:
            parts.append(f"fps median {statistics.median(self.fps):.1f}")
        return ("; ".join(parts) + f". Current: STRAIGHT_MIN_DIFF={config.STRAIGHT_MIN_DIFF:g}, "
                f"STRAIGHT_K={config.STRAIGHT_K:g}, STRAIGHT_HOLD_FRAMES={config.STRAIGHT_HOLD_FRAMES} "
                "in pi/config.py. Put MIN_DIFF above the calm windows' peaks (you kept a straight "
                "face but it still fired? raise it) and below the peaks of windows where you "
                "really reacted.")
