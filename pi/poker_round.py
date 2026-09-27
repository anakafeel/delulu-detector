"""Poker Face (Hill's Kitchen's Round 2, internal id 5) on the Pi: claim line in, reading out.

Also home of FaceRound, the camera plumbing shared with Straight Face
(straight_round.py): camera lock, browser feed, claim-setting preview, clips.

The Arduino only locks the claim and prints
    {"type":"claim","round_id":5,"seq":N,"claim":72}
PokerRound.run() then:
  1. starts one random tough interview question (assets/questions/poker_XX.mp3,
     non-blocking; older machines fall back to assets/jokes/; skipped if there
     is none or audio is off),
  2. watches the webcam for config.POKER_WINDOW_S seconds (vision.measure_window),
  3. stops the question clip if it is still playing, and
  4. returns a result dict in the same shape main.parse_line() gives for the
     Arduino rounds:
       {"type":"result","round_id":5,"seq":N,"claim":72.0,"actual":12.5,"unit":"smile_pct",
        "smile_frac":0.125,"face_frac":0.97,"frames":88,"fps":14.7,"first_smile_ms":2310,
        "false_start":false,"timeout":false}
     plus "error":"no_face" when a face was in fewer than POKER_MIN_FACE_FRAC of
     the frames, or "error":"camera_read" when no frame could be read. Errors are
     not scored, logged or spoken (main.is_sensor_error).
Frames never leave this process: only these numbers are stored. With --ui and a
real camera (or --video), the newest frame is also handed to camera_feed.CameraFeed so the
browser can show it live (GET /api/camera.mjpg; memory only, never written to disk).

Camera access is exclusive (_cam_lock): the measured window and the optional
claim-setting preview (attach_feed(..., idle_preview=True), only while a browser
is watching) never read the camera at the same time, and the window always wins.
"""
from __future__ import annotations

import json
import random
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import camera_feed
import config
import elevenlabs_client as ec
import vision
from presage_client import PresageError, PresageSession
from scoring import ROUND_POKER


def _open_presage(camera, require: bool) -> Optional[PresageSession]:
    """Start Presage on a real camera. Calibration passes require=False."""
    if not require:
        return None
    session = PresageSession()
    try:
        session.start()
    except Exception:
        close = getattr(camera, "close", None)
        if close is not None:
            close()
        raise
    return session


def _presage_failure(claim_msg: dict, round_id: int, exc: PresageError) -> dict:
    return {
        "type": "result", "round_id": round_id, "seq": claim_msg.get("seq"),
        "claim": float(claim_msg["claim"]), "actual": None, "unit": "composure",
        "false_start": False, "timeout": False,
        "error": "presage", "presage_error": str(exc),
    }


def _apply_presage(session: Optional[PresageSession], reading: dict) -> dict:
    """Replace the scored actual with Presage composure. Leave an existing sensor error alone."""
    if session is None or reading.get("error"):
        return reading
    try:
        value = round(session.finish(), 1)
    except PresageError as exc:
        reading["error"] = "presage"
        reading["presage_error"] = str(exc)
        reading["actual"] = None
        reading["composure"] = None
        return reading
    reading["composure"] = value
    reading["presage_samples"] = getattr(session, "last_sample_count", None)   # shown on the reveal
    reading["actual"] = value
    reading["unit"] = "composure"
    return reading


def parse_claim(line: str) -> Optional[dict]:
    """{"type":"claim","round_id":5,"seq":N,"claim":72} -> dict (claim float, round_id int), else None."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict) or msg.get("type") != "claim":
        return None
    if "claim" not in msg or "round_id" not in msg:
        return None
    try:
        msg["claim"] = float(msg["claim"])
        msg["round_id"] = int(msg["round_id"])
        if msg.get("seq") is not None:
            msg["seq"] = int(msg["seq"])
    except (TypeError, ValueError):
        return None
    return msg


def window_line(window_s: Optional[float] = None, name: str = "POKER_WINDOW_S") -> bytes:
    """b"W6000\\n": tells the sketch how long to show the face-round cue (1000-30000 ms)."""
    window_s = config.POKER_WINDOW_S if window_s is None else window_s
    ms = int(round(window_s * 1000))
    if not 1000 <= ms <= 30000:
        raise ValueError(f"{name} must be 1-30 s, got {window_s}")
    return f"W{ms}\n".encode("ascii")


# ---------------------------------------------------------------------------
# Question clips (the stimulus)
# ---------------------------------------------------------------------------
def _mp3s(folder: Path, pattern: str = "*.mp3") -> list[Path]:
    try:
        return sorted(p for p in Path(folder).glob(pattern) if p.is_file())
    except OSError:
        return []


def question_files(kind: str, questions_dir: Optional[Path] = None) -> list[Path]:
    """assets/questions/<kind>_XX.mp3 ("poker" or "pressure"), sorted; [] if none."""
    folder = config.QUESTIONS_DIR if questions_dir is None else questions_dir
    return _mp3s(folder, f"{kind}_*.mp3")


def joke_files(jokes_dir: Optional[Path] = None) -> list[Path]:
    """Poker Face prompt clips: every mp3 in jokes_dir if given; by default the tough
    interview questions (assets/questions/poker_XX.mp3), or the pre-pivot jokes in
    assets/jokes/ on a machine that hasn't regenerated its clips yet."""
    if jokes_dir is not None:
        return _mp3s(jokes_dir)
    return question_files("poker") or _mp3s(config.JOKES_DIR)


class LivePrompt:
    """Speak interview lines through a live ElevenLabs call. No stand-in mp3.

    One question when repeat is false (Poker Face). Back to back when repeat
    is true (Straight Face). A failed call is printed and reported; nothing
    else is played.
    """

    def __init__(self, lines: list[str], rng: random.Random,
                 start_audio_fn: Optional[Callable[[Path], object]] = None,
                 stop_audio_fn: Optional[Callable[[object], None]] = None,
                 on_text: Optional[Callable[[str], None]] = None,
                 on_fail: Optional[Callable[[], None]] = None,
                 repeat: bool = False,
                 synthesize_fn: Optional[Callable[[str, Path], Path]] = None):
        self.lines = list(lines)
        self.rng = rng
        self._start_audio = start_audio if start_audio_fn is None else start_audio_fn
        self._stop_audio = stop_audio if stop_audio_fn is None else stop_audio_fn
        self.on_text = on_text
        self.on_fail = on_fail
        self.repeat = repeat
        self._synthesize = synthesize_fn or _synthesize_question
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._proc = None
        self._thread: Optional[threading.Thread] = None
        self.spoken: list[str] = []
        self.failures: list[str] = []

    def start(self) -> "LivePrompt":
        if self.lines and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="hk-live-question", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        last = None
        while not self._stop.is_set():
            choices = [line for line in self.lines if line != last] or self.lines
            text = self.rng.choice(choices)
            last = text
            print(f'   QUESTION: "{text}"')
            if self.on_text is not None:
                try:
                    self.on_text(text)
                except Exception as exc:  # noqa: BLE001
                    print(f"   [warn] question text hook failed: {exc}", file=sys.stderr)
            out = config.TTS_OUTPUT_DIR / f"question_{time.time_ns()}.mp3"
            try:
                path = self._synthesize(text, out)
            except ec.TTSError as exc:
                self.failures.append(str(exc))
                print(f"   [error] question unavailable ({exc})", file=sys.stderr)
                if self.on_fail is not None:
                    try:
                        self.on_fail()
                    except Exception as hook_exc:  # noqa: BLE001
                        print(f"   [warn] question fail hook failed: {hook_exc}", file=sys.stderr)
                if not self.repeat:
                    return
                continue
            if self._stop.is_set():
                return
            proc = self._start_audio(path)
            with self._lock:
                self._proc = proc
            self.spoken.append(text)
            poll = getattr(proc, "poll", None) if proc is not None else None
            while poll is not None and poll() is None and not self._stop.is_set():
                self._stop.wait(0.05)
            with self._lock:
                self._proc = None
            self._stop_audio(proc)
            if not self.repeat or self._stop.is_set():
                return
            self._stop.wait(config.STRAIGHT_QUESTION_GAP_S)

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


def _synthesize_question(text: str, out: Path) -> Path:
    return ec.synthesize(text, out)


def start_audio(path: Path) -> Optional[subprocess.Popen]:
    """Start playing an mp3 without waiting for it. None if there's no player or it won't start."""
    cmd = ec.find_player_cmd()
    if cmd is None:
        return None
    try:
        return subprocess.Popen(cmd + [str(path)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        return None


def stop_audio(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Shared camera plumbing (Poker Face + Straight Face)
# ---------------------------------------------------------------------------
class FaceRound:
    """Camera + detector for a whole session (the camera stays open), plus the
    browser feed, the claim-setting preview and the exclusive camera lock.
    Subclasses implement _measure_locked() and run(claim_msg)."""

    round_id = 0
    feed_kind = "poker"                   # camera_feed overlay style

    def __init__(self, camera, detector, window_s: float,
                 clock: Callable[[], float] = time.monotonic,
                 preview: Optional[vision.PreviewWindow] = None,
                 rng: Optional[random.Random] = None,
                 start_audio_fn: Callable[[Path], object] = start_audio,
                 stop_audio_fn: Callable[[object], None] = stop_audio):
        self.camera = camera
        self.detector = detector
        self.window_s = float(window_s)
        self.clock = clock
        self.preview = preview
        self.rng = rng or random.Random()
        self._start_audio = start_audio_fn
        self._stop_audio = stop_audio_fn
        self.feed = None                      # camera_feed.CameraFeed (browser stream), set by attach_feed
        self.presage = None                   # PresageSession; real rounds set this, mock rounds do not
        self.on_prompt = None                 # (text) -> None, the live question line
        self.on_prompt_fail = None           # () -> None, ElevenLabs did not speak it
        self._cam_lock = threading.Lock()     # measure() and the idle preview never read at once
        self._measuring = threading.Event()
        self._stop = threading.Event()
        self._idle_thread: Optional[threading.Thread] = None
        self.idle_fps = config.UI_CAMERA_IDLE_FPS
        self.cam_lock_timeout_s = 3.0

    def measure(self, *args, **kwargs):
        """One window under the camera lock (the idle preview yields at its next frame)."""
        self._measuring.set()                 # the idle preview stops at its next frame
        if not self._cam_lock.acquire(timeout=self.cam_lock_timeout_s):
            self._measuring.clear()
            raise vision.VisionUnavailable("camera busy: the browser preview's camera read is stuck")
        try:
            return self._measure_locked(*args, **kwargs)
        finally:
            self._cam_lock.release()
            self._measuring.clear()

    def _measure_locked(self, *args, **kwargs):
        raise NotImplementedError

    def run(self, claim_msg: dict) -> dict:
        raise NotImplementedError

    # ------------------------------------------------------------ browser camera
    def attach_feed(self, feed, idle_preview: bool = False, idle_fps: Optional[float] = None) -> None:
        """Hand measured frames to `feed` (camera_feed.CameraFeed) for GET /api/camera.mjpg.

        idle_preview: between windows, while at least one browser is watching the
        stream, also read the (already open) camera at idle_fps with face detection so
        the player can frame their face while setting the claim. Stops at once when a
        window starts or nobody watches; frames there are raw detector output, not scored.
        """
        self.feed = feed
        if idle_fps is not None:
            self.idle_fps = float(idle_fps)
        if idle_preview and self._idle_thread is None:
            self._idle_thread = threading.Thread(target=self._idle_loop, name="delulu-camera-preview",
                                                 daemon=True)
            self._idle_thread.start()

    def _idle_loop(self) -> None:
        period = 1.0 / max(1.0, self.idle_fps)
        active = False
        reported = False
        while not self._stop.is_set():
            feed = self.feed
            if feed is None or feed.viewers <= 0 or self._measuring.is_set():
                if active and feed is not None:
                    feed.end("preview")             # no-op if a window already took over
                active = False
                self._stop.wait(0.2)
                continue
            t0 = time.monotonic()
            if not self._cam_lock.acquire(timeout=0.2):
                continue
            try:
                if self._measuring.is_set() or self._stop.is_set():
                    continue
                if not active:
                    feed.begin("preview", kind=self.feed_kind)
                    active = True
                frame = self.camera.read()
                if frame is not None:
                    obs = self.detector.detect(frame)
                    feed.offer(frame, obs, obs.smile)
                del frame
            except Exception as exc:  # noqa: BLE001 - the preview must never take the game down
                if not reported:
                    reported = True
                    print(f"   [camera feed] preview read failed ({type(exc).__name__}: {exc}); "
                          "retrying quietly. Rounds are not affected.", file=sys.stderr)
                self._stop.wait(1.0)
            finally:
                self._cam_lock.release()
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
        if active and self.feed is not None:
            self.feed.end("preview")

    def close(self) -> None:
        self._stop.set()
        if self._idle_thread is not None:
            self._idle_thread.join(timeout=2.0)
            self._idle_thread = None
        got = self._cam_lock.acquire(timeout=2.0)   # don't release the camera under a preview read
        try:
            close = getattr(self.camera, "close", None)
            if close is not None:
                close()
        finally:
            if got:
                self._cam_lock.release()
        if getattr(self, "presage", None) is not None:
            self.presage.close()
            self.presage = None
        if self.preview is not None:
            self.preview.close()




class PokerRound(FaceRound):
    """Poker Face: camera + detector + interview-question player for a whole session."""

    round_id = ROUND_POKER
    feed_kind = "poker"

    def __init__(self, camera, detector, window_s: Optional[float] = None,
                 clock: Callable[[], float] = time.monotonic, play_jokes: bool = True,
                 jokes_dir: Optional[Path] = None, preview: Optional[vision.PreviewWindow] = None,
                 rng: Optional[random.Random] = None,
                 start_audio_fn: Callable[[Path], object] = start_audio,
                 stop_audio_fn: Callable[[object], None] = stop_audio):
        super().__init__(camera, detector, config.POKER_WINDOW_S if window_s is None else window_s,
                         clock=clock, preview=preview, rng=rng,
                         start_audio_fn=start_audio_fn, stop_audio_fn=stop_audio_fn)
        self.play_jokes = play_jokes          # (the prompts are interview questions now; old name kept)
        self.jokes_dir = jokes_dir
        self.last_joke: Optional[Path] = None
        self.want_photo = False               # set per round by main.py: the player pressed Y
        self.photo: Optional[bytes] = None    # that round's JPEG (memory only), taken at PHOTO_AT_S

    def _pick_joke(self) -> Optional[Path]:
        files = joke_files(self.jokes_dir)
        if not files:
            return None
        if len(files) > 1 and self.last_joke in files:
            files = [f for f in files if f != self.last_joke]     # no back-to-back repeat
        return self.rng.choice(files)

    def _measure_locked(self) -> vision.WindowStats:
        joke_proc = None
        self.last_live = None
        wants_preview = self.preview is not None and self.preview.enabled
        self.photo = None
        on_frame = self._on_frame if (wants_preview or self.feed is not None or self.presage is not None
                                      or self.want_photo) else None
        if self.feed is not None:
            self.feed.begin("measuring", self.window_s)     # never raises
        try:
            self.camera.begin_window()
            if self.play_jokes and self.jokes_dir is None:
                live = LivePrompt(ec.POKER_QUESTION_LINES, self.rng, self._start_audio, self._stop_audio,
                                  on_text=self.on_prompt, on_fail=self.on_prompt_fail).start()
                self.last_live = live
            elif self.play_jokes:
                joke = self._pick_joke()
                if joke is not None:
                    self.last_joke = joke
                    joke_proc = self._start_audio(joke)
            return vision.measure_window(self.camera, self.detector, self.window_s,
                                         clock=self.clock, on_frame=on_frame)
        finally:
            live = getattr(self, "last_live", None)
            if live is not None:
                live.join()
            self._stop_audio(joke_proc)
            if self.preview is not None:
                self.preview.close()
            if self.feed is not None:
                self.feed.end("measuring")

    def _on_frame(self, frame, obs, smiling: bool, elapsed_s: float) -> None:
        """Per measured frame: Presage (the score), the preview window, and the browser slot."""
        extra = None
        if self.presage is not None:
            self.presage.push(frame)
            latest = self.presage.latest()
            if latest is not None:
                extra = {"composure": round(latest, 1)}
        if self.preview is not None and self.preview.enabled:
            self.preview.show(frame, obs, smiling, elapsed_s, self.window_s)   # never raises
        if self.feed is not None:
            if extra is None:
                self.feed.offer(frame, obs, smiling, elapsed_s)                 # never raises
            else:
                self.feed.offer(frame, obs, smiling, elapsed_s, extra=extra)
        if self.want_photo and self.photo is None and elapsed_s >= config.PHOTO_AT_S:
            self.photo = camera_feed.photo_jpeg(frame)    # encoding lives in camera_feed (memory only)

    def run(self, claim_msg: dict) -> dict:
        try:
            stats = self.measure()
        except PresageError as exc:
            return _presage_failure(claim_msg, self.round_id, exc)
        reading = reading_from_stats(claim_msg, stats)
        return _apply_presage(self.presage, reading)


def reading_from_stats(claim_msg: dict, stats: vision.WindowStats,
                       min_face_frac: Optional[float] = None) -> dict:
    """Result dict (main.parse_line shape) for one measured window."""
    min_face_frac = config.POKER_MIN_FACE_FRAC if min_face_frac is None else min_face_frac
    reading = {
        "type": "result", "round_id": ROUND_POKER, "seq": claim_msg.get("seq"),
        "claim": float(claim_msg["claim"]), "actual": None, "unit": "smile_pct",
        "smile_frac": None, "face_frac": round(stats.face_frac, 4), "frames": stats.frames,
        "fps": round(stats.fps, 1), "first_smile_ms": stats.first_smile_ms,
        "false_start": False, "timeout": False,
    }
    if stats.frames == 0:
        reading["error"] = "camera_read"
    elif stats.face_frac < min_face_frac:
        reading["error"] = "no_face"
    else:
        reading["smile_frac"] = round(stats.smile_frac, 4)
        reading["actual"] = round(stats.smile_frac * 100.0, 2)
    return reading


# ---------------------------------------------------------------------------
# Factory used by main.py
# ---------------------------------------------------------------------------
def open_source(camera_index: Optional[int] = None, video: Optional[str] = None):
    """The real detector plus a camera (or a --video clip): (camera, detector, clock).

    A clip runs on its own video clock, so the numbers don't depend on CPU speed.
    Raises vision.VisionUnavailable with a readable message if OpenCV, the
    cascades, the camera or the file is missing.
    """
    detector = vision.HaarDetector()                     # checks cv2 + cascades before the camera
    if video:
        camera = vision.VideoFileCamera(video).open()
        return camera, detector, camera.now
    return vision.Camera(camera_index).open(), detector, time.monotonic


def build(mock: bool, camera_index: Optional[int] = None, preview: bool = False,
          play_jokes: bool = True, seed: Optional[int] = None,
          window_s: Optional[float] = None, video: Optional[str] = None,
          require_presage: bool = True) -> PokerRound:
    """Real webcam (or video=path) + Haar detector, or (mock=True) a scripted fake
    with a virtual clock. A video wins over mock (--mock --video: fake Arduino, real clip).

    Raises vision.VisionUnavailable with a readable message if OpenCV or the camera is missing.
    """
    window_s = config.POKER_WINDOW_S if window_s is None else window_s
    rng = random.Random(seed)
    if mock and not video:
        cam = vision.MockCamera(seed, window_s)
        return PokerRound(cam, vision.FakeDetector(), window_s, clock=cam.now,
                          play_jokes=play_jokes, rng=rng)
    camera, detector, clock = open_source(camera_index, video)
    session = _open_presage(camera, require_presage)
    game = PokerRound(camera, detector, window_s, clock=clock, play_jokes=play_jokes,
                      preview=vision.PreviewWindow(True) if preview else None, rng=rng)
    game.presage = session
    return game


# ---------------------------------------------------------------------------
# --calibrate --round 5
# ---------------------------------------------------------------------------
class PokerCalibrator:
    """Raw per-window numbers with running min / median / max. No scoring, no logging, no voice."""

    def __init__(self) -> None:
        self.smile: list[float] = []
        self.face: list[float] = []
        self.fps: list[float] = []
        self.windows = 0

    def add(self, reading: dict) -> None:
        self.windows += 1
        first = reading.get("first_smile_ms")
        first_s = "none" if first is None else f"{first} ms"
        smile = reading.get("smile_frac")
        smile_s = "-" if smile is None else f"{smile:.3f}"
        note = ""
        if reading.get("error"):
            note = f" | [{reading['error']}: would not be scored, left out of the stats]"
        print(f"   calib #{self.windows}: smile_frac {smile_s} | face_frac {reading['face_frac']:.2f} | "
              f"fps {reading['fps']:.1f} ({reading['frames']} frames) | first_smile_ms {first_s} | "
              f"(claim {reading['claim']:.0f} ignored){note}")
        if reading.get("error"):
            if reading["error"] == "no_face":
                print("      face the camera (good light, nothing over your face) and try again",
                      file=sys.stderr)
            return
        self.smile.append(smile)
        self.face.append(reading["face_frac"])
        self.fps.append(reading["fps"])
        print(f"      so far: smile_frac min {min(self.smile):.3f} | median "
              f"{statistics.median(self.smile):.3f} | max {max(self.smile):.3f} over "
              f"{len(self.smile)} window(s); face_frac median {statistics.median(self.face):.2f}; "
              f"fps median {statistics.median(self.fps):.1f}")
        if reading["fps"] < 8:
            print("      [warn] under 8 fps: lower VISION_DETECT_WIDTH in pi/config.py", file=sys.stderr)

    def summary(self) -> str:
        if not self.smile:
            return "No usable Round 5 windows recorded."
        return (f"Calibration: {len(self.smile)} window(s), smile_frac min {min(self.smile):.3f}, "
                f"median {statistics.median(self.smile):.3f}, max {max(self.smile):.3f}; "
                f"fps median {statistics.median(self.fps):.1f}. Current thresholds: "
                f"POKER_BEST_FRAC={config.POKER_BEST_FRAC:g} (=100), "
                f"POKER_WORST_FRAC={config.POKER_WORST_FRAC:g} (=0) in pi/config.py. Put BEST just "
                "above your honest stone-face windows (the detector's false-positive floor) and "
                "WORST around a window where you clearly laughed.")
