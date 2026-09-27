"""Hill's Kitchen's face rounds: webcam or video file, Haar face + smile detector, frame differencing.

Fully local: OpenCV's built-in Haar cascades, no network, no external API.

Privacy: frames live only in memory, one at a time, inside the measure_* loops.
Nothing here writes a frame to disk or sends it anywhere. The optional
--preview window only draws on screen; with --ui, the rounds hand the newest
frame to camera_feed.py for the local browser stream (memory only). Only the
numbers (smile_frac, face_frac, seconds held, frame count, fps, ...) are stored.

OpenCV is imported LAZILY (import_cv2()), so Round 1, the tests and --mock run
without it. opencv-python 5.x removed cv2.CascadeClassifier, so the requirement
is pinned to opencv-python>=4.8,<5.

Pieces:
  - Observation        what the detector saw in one frame
  - SmileSmoother      "a smile only counts if it's in 2 of the last 3 face frames"
  - WindowStats / measure_window()      Poker Face: smile_frac over a fixed window
  - FaceSignature / ExpressionTracker / StraightStats / measure_straight_face()
                       Straight Face: seconds until the face differs from its own
                       neutral baseline (frame differencing, normalized by face size)
  - Camera             cv2.VideoCapture(index), configurable index (default 0)
  - VideoFileCamera    a saved clip instead of the webcam (--video), on video time
  - HaarDetector       frontal face on a downscaled frame, then smile on the lower
                       half of the largest face (full resolution, fixed ROI width)
  - PreviewWindow      optional OpenCV window with the face / smile boxes (never
                       crashes headless: it just turns itself off)
  - FakeCamera / FakeDetector / FakeSignature / MockCamera / MockStraightCamera
                       scripted frames for tests and --mock

Run on its own against a clip (no Arduino, nothing saved):
    python pi/vision.py --video clip.mp4 --round poker     # smile_frac per 6 s window
    python pi/vision.py --video clip.mp4 --round straight  # seconds held per window
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

import config

OPENCV_PIN = "opencv-python>=4.8,<5"


class VisionUnavailable(RuntimeError):
    """OpenCV missing or unusable, cascades not found, or the camera can't be opened."""


def import_cv2():
    """Import cv2 on first use, with a clear message if it's missing or too new."""
    try:
        import cv2  # noqa: PLC0415 - lazy on purpose
    except ImportError as exc:
        raise VisionUnavailable(
            f"Round 5 (Poker Face) needs OpenCV, which is not installed ({exc}). "
            f"Install it with: pip install '{OPENCV_PIN}'  (Rounds 1 and 2 don't need it; "
            "--mock --round 5 runs without it)") from exc
    if not hasattr(cv2, "CascadeClassifier"):
        version = getattr(cv2, "__version__", "?")
        raise VisionUnavailable(
            f"OpenCV {version} has no cv2.CascadeClassifier (opencv-python 5.x removed the Haar "
            f"cascades). Install 4.x: pip install '{OPENCV_PIN}'")
    return cv2


# ---------------------------------------------------------------------------
# Per-frame result + smoothing
# ---------------------------------------------------------------------------
Box = tuple[int, int, int, int]   # x, y, w, h in full-frame pixels


@dataclass
class Observation:
    face: bool
    smile: bool = False                 # raw, unsmoothed detector output
    face_box: Optional[Box] = None
    smile_box: Optional[Box] = None


class SmileSmoother:
    """Majority vote over the last `frames` face frames.

    update(raw) -> True if at least `hits` of the last `frames` raw values
    (including this one) were smiles. With the defaults (2 of 3) a one-frame
    false positive never counts, and a real smile counts from its 2nd frame.
    Only frames WITH a face are fed in (smile_frac is per face frame).
    """

    def __init__(self, frames: Optional[int] = None, hits: Optional[int] = None):
        self.frames = config.SMILE_SMOOTH_FRAMES if frames is None else int(frames)
        self.hits = config.SMILE_SMOOTH_HITS if hits is None else int(hits)
        if not 1 <= self.hits <= self.frames:
            raise ValueError("need 1 <= hits <= frames")
        self._history: deque[bool] = deque(maxlen=self.frames)

    def update(self, raw_smile: bool) -> bool:
        self._history.append(bool(raw_smile))
        return sum(self._history) >= self.hits

    def reset(self) -> None:
        self._history.clear()


@dataclass
class WindowStats:
    frames: int = 0                     # frames read from the camera
    face_frames: int = 0                # ... with a face
    smile_frames: int = 0               # ... with a face and a smoothed smile
    raw_smile_frames: int = 0           # ... with a face and a raw detector hit (diagnostics)
    elapsed_s: float = 0.0
    first_smile_ms: Optional[int] = None   # from window start to the first smoothed smile
    read_failures: int = 0

    @property
    def smile_frac(self) -> float:
        return self.smile_frames / self.face_frames if self.face_frames else 0.0

    @property
    def face_frac(self) -> float:
        return self.face_frames / self.frames if self.frames else 0.0

    @property
    def fps(self) -> float:
        return self.frames / self.elapsed_s if self.elapsed_s > 0 else 0.0


FrameCallback = Callable[[Any, Observation, bool, float], None]


def measure_window(camera, detector, window_s: float, clock: Callable[[], float] = time.monotonic,
                   smoother: Optional[SmileSmoother] = None, on_frame: Optional[FrameCallback] = None,
                   max_consecutive_failures: int = 25) -> WindowStats:
    """Read frames for window_s seconds (by `clock`) and count face / smile frames.

    camera.read() returns a frame or None (read failure); detector.detect(frame)
    returns an Observation. on_frame(frame, obs, smiling, elapsed_s) is called
    for every good frame (used by --preview). Each frame is dropped as soon as
    the next one is read: nothing is kept or stored.
    """
    smoother = smoother or SmileSmoother()
    stats = WindowStats()
    start = clock()
    now = start
    failures = 0
    while now - start < window_s:
        frame = camera.read()
        now = clock()
        if frame is None:
            stats.read_failures += 1
            failures += 1
            if failures >= max_consecutive_failures:
                break                              # camera unplugged / dead: give up on this window
            continue
        failures = 0
        stats.frames += 1
        obs = detector.detect(frame)
        smiling = False
        if obs.face:
            stats.face_frames += 1
            if obs.smile:
                stats.raw_smile_frames += 1
            smiling = smoother.update(obs.smile)
            if smiling:
                stats.smile_frames += 1
                if stats.first_smile_ms is None:
                    stats.first_smile_ms = int(round((now - start) * 1000))
        if on_frame is not None:
            on_frame(frame, obs, smiling, now - start)
        del frame
    stats.elapsed_s = max(0.0, now - start)
    return stats


# ---------------------------------------------------------------------------
# Straight Face Under Pressure: frame differencing against a neutral baseline
# ---------------------------------------------------------------------------
class FaceSignature:
    """The face box as a small grayscale crop: normalized by face size and brightness.

    signature(frame, obs) -> a STRAIGHT_SIG_SIZE x STRAIGHT_SIG_SIZE float32 array
    (the face box resized, lightly blurred, its mean subtracted so auto-exposure
    drift doesn't read as an expression change), or None without a face.
    The box is smoothed over frames (Haar boxes jitter by a few pixels, which
    would otherwise look like movement). distance(a, b) = mean absolute
    difference in gray levels over the whole face or over the mouth region
    (rows from STRAIGHT_MOUTH_FROM down), whichever is larger.
    """

    def __init__(self, size: Optional[int] = None, mouth_from: Optional[float] = None,
                 box_alpha: float = 0.5, cv2=None):
        self.cv2 = cv2 if cv2 is not None else import_cv2()
        import numpy as np   # noqa: PLC0415 - numpy comes with opencv-python
        self.np = np
        self.size = int(size or config.STRAIGHT_SIG_SIZE)
        self.mouth_row = int(self.size * (config.STRAIGHT_MOUTH_FROM if mouth_from is None else mouth_from))
        self.box_alpha = box_alpha
        self._box: Optional[tuple[float, float, float, float]] = None

    def reset(self) -> None:
        self._box = None

    def _smoothed_box(self, box) -> tuple[int, int, int, int]:
        if self._box is None:
            self._box = tuple(float(v) for v in box)
        else:
            a = self.box_alpha
            self._box = tuple(a * float(n) + (1 - a) * o for n, o in zip(box, self._box))
        return tuple(int(round(v)) for v in self._box)

    def __call__(self, frame, obs: Observation):
        if not obs.face or not obs.face_box:
            return None
        cv2, np = self.cv2, self.np
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        x, y, w, h = self._smoothed_box(obs.face_box)
        x, y = max(0, x), max(0, y)
        crop = gray[y:y + max(1, h), x:x + max(1, w)]
        if crop.size == 0:
            return None
        small = cv2.resize(crop, (self.size, self.size), interpolation=cv2.INTER_AREA).astype(np.float32)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        small -= float(small.mean())
        return small

    def distance(self, a, b) -> float:
        d = self.np.abs(a - b)
        return float(max(d.mean(), d[self.mouth_row:].mean()))


class ExpressionTracker:
    """Neutral baseline, then "has the face changed?" for each later face frame.

    The first `baseline_s` seconds of face signatures (at least
    `min_baseline_frames` of them) are averaged into the reference neutral face.
    Their own distances to it give the noise level: threshold =
    max(min_diff, mean + k * std). After that, update() returns the window time
    of the first frame of a run of `hold_frames` consecutive frames over the
    threshold (the change), else None. Signatures can be anything `distance`
    understands (numpy arrays for real frames, floats in tests).
    """

    def __init__(self, distance: Callable[[Any, Any], float], baseline_s: Optional[float] = None,
                 k: Optional[float] = None, min_diff: Optional[float] = None,
                 hold_frames: Optional[int] = None, min_baseline_frames: Optional[int] = None):
        self.distance = distance
        self.baseline_s = config.STRAIGHT_BASELINE_S if baseline_s is None else float(baseline_s)
        self.k = config.STRAIGHT_K if k is None else float(k)
        self.min_diff = config.STRAIGHT_MIN_DIFF if min_diff is None else float(min_diff)
        self.hold_frames = max(1, int(config.STRAIGHT_HOLD_FRAMES if hold_frames is None else hold_frames))
        self.min_baseline_frames = max(1, int(config.STRAIGHT_MIN_BASELINE_FRAMES
                                              if min_baseline_frames is None else min_baseline_frames))
        self._baseline: list = []
        self.reference = None
        self.base_mean: Optional[float] = None
        self.base_std: Optional[float] = None
        self.threshold: Optional[float] = None
        self.last_score: Optional[float] = None
        self.peak = 0.0
        self._over = 0
        self._first_over_t: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.reference is not None

    @property
    def baseline_frames(self) -> int:
        return len(self._baseline)

    @property
    def level(self) -> Optional[float]:
        """last score / threshold (1.0 = at the threshold), None before the baseline is done."""
        if self.threshold is None or self.last_score is None or self.threshold <= 0:
            return None
        return self.last_score / self.threshold

    def update(self, sig, t: float) -> Optional[float]:
        if self.reference is None:
            self._baseline.append(sig)
            if t >= self.baseline_s and len(self._baseline) >= self.min_baseline_frames:
                self._finish_baseline()
            return None
        score = float(self.distance(sig, self.reference))
        self.last_score = score
        self.peak = max(self.peak, score)
        if score > self.threshold:
            if self._over == 0:
                self._first_over_t = t
            self._over += 1
            if self._over >= self.hold_frames:
                return self._first_over_t
        else:
            self._over = 0
        return None

    def _finish_baseline(self) -> None:
        sigs = self._baseline
        n = len(sigs)
        ref = sigs[0]
        for s in sigs[1:]:
            ref = ref + s
        ref = ref / n
        scores = [float(self.distance(s, ref)) for s in sigs]
        mean = sum(scores) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in scores) / n)
        self.reference = ref
        self.base_mean, self.base_std = mean, std
        self.threshold = max(self.min_diff, mean + self.k * std)
        self._baseline = []                       # drop the crops: memory only, and not needed


@dataclass
class StraightStats:
    """Numbers from one Straight Face window (never frames)."""

    max_s: float = 0.0
    frames: int = 0
    face_frames: int = 0
    elapsed_s: float = 0.0
    changed_at_s: Optional[float] = None      # window time of the change; None = held to the end
    trigger: Optional[str] = None             # "expression" or "smile"
    baseline_ok: bool = False
    threshold: Optional[float] = None
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    peak_score: float = 0.0
    read_failures: int = 0
    completed: bool = False                   # ran until a change or the full max_s (not cut short)

    @property
    def broke(self) -> bool:
        return self.changed_at_s is not None

    @property
    def held_s(self) -> float:
        if self.changed_at_s is not None:
            return max(0.0, min(self.max_s, self.changed_at_s))
        return self.max_s if self.completed else max(0.0, min(self.max_s, self.elapsed_s))

    @property
    def face_frac(self) -> float:
        return self.face_frames / self.frames if self.frames else 0.0

    @property
    def fps(self) -> float:
        return self.frames / self.elapsed_s if self.elapsed_s > 0 else 0.0


StraightFrameCallback = Callable[[Any, Observation, dict], None]


def measure_straight_face(camera, detector, signature, max_s: float,
                          clock: Callable[[], float] = time.monotonic,
                          tracker: Optional[ExpressionTracker] = None,
                          smoother: Optional[SmileSmoother] = None,
                          on_frame: Optional[StraightFrameCallback] = None,
                          on_change: Optional[Callable[[float, str], None]] = None,
                          tail_s: Optional[float] = None,
                          smile_breaks: Optional[bool] = None,
                          baseline_timeout_s: Optional[float] = None,
                          max_consecutive_failures: int = 25) -> StraightStats:
    """Read frames for up to max_s seconds and time how long the face stays neutral.

    Ends early `tail_s` after a change (so the overlay can show the marker), or
    when no neutral baseline could be taken within `baseline_timeout_s` (no
    face -> the caller reports "no_face"), or when the camera stops delivering.
    on_frame(frame, obs, info) gets each frame plus a small info dict for the
    overlay; on_change(t, trigger) fires once, the moment a change is detected
    (main.py uses it to stop the Arduino's cue early). Frames are never kept.
    """
    smoother = smoother or SmileSmoother()
    tracker = tracker or ExpressionTracker(signature.distance)
    tail_s = config.STRAIGHT_TAIL_S if tail_s is None else float(tail_s)
    smile_breaks = config.STRAIGHT_SMILE_BREAKS if smile_breaks is None else bool(smile_breaks)
    baseline_timeout_s = (config.STRAIGHT_BASELINE_TIMEOUT_S if baseline_timeout_s is None
                          else float(baseline_timeout_s))
    if hasattr(signature, "reset"):
        signature.reset()
    stats = StraightStats(max_s=float(max_s))
    start = clock()
    now = start
    end_at = float(max_s)
    failures = 0
    ended_by_change = False

    def changed(t_change: float, trigger: str, t_now: float) -> None:
        nonlocal end_at, ended_by_change
        stats.changed_at_s = round(max(0.0, t_change), 3)
        stats.trigger = trigger
        end_at = min(end_at, t_now + tail_s)
        ended_by_change = True
        if on_change is not None:
            try:
                on_change(stats.changed_at_s, trigger)
            except Exception as exc:  # noqa: BLE001 - a serial hiccup must not end the window
                print(f"   [warn] could not signal the expression change: {exc}", file=sys.stderr)

    while now - start < end_at:
        frame = camera.read()
        now = clock()
        t = now - start
        if frame is None:
            stats.read_failures += 1
            failures += 1
            if failures >= max_consecutive_failures:
                break
            continue
        failures = 0
        stats.frames += 1
        obs = detector.detect(frame)
        smiling = False
        if obs.face:
            stats.face_frames += 1
            smiling = smoother.update(obs.smile)
            if stats.changed_at_s is None:
                sig = signature(frame, obs)
                if sig is not None:
                    hit = tracker.update(sig, t)
                    if hit is not None:
                        changed(hit, "expression", t)
                if smile_breaks and smiling and stats.changed_at_s is None:
                    changed(t, "smile", t)
        if on_frame is not None:
            phase = ("changed" if stats.changed_at_s is not None
                     else "watching" if tracker.ready else "baseline")
            on_frame(frame, obs, {
                "phase": phase, "elapsed": t, "smiling": smiling,
                "held_s": stats.changed_at_s if stats.changed_at_s is not None else min(t, max_s),
                "changed_at_s": stats.changed_at_s, "trigger": stats.trigger,
                "level": tracker.level, "max_s": float(max_s),
            })
        del frame
        if not tracker.ready and stats.changed_at_s is None and t >= baseline_timeout_s:
            break                                  # never got a neutral baseline: no face
    stats.elapsed_s = max(0.0, now - start)
    stats.completed = ended_by_change or (tracker.ready and now - start >= end_at)
    stats.baseline_ok = tracker.ready or stats.trigger == "smile"
    stats.threshold = tracker.threshold
    stats.baseline_mean = tracker.base_mean
    stats.baseline_std = tracker.base_std
    stats.peak_score = tracker.peak
    return stats


# ---------------------------------------------------------------------------
# Real camera + detector (need OpenCV)
# ---------------------------------------------------------------------------
class Camera:
    """cv2.VideoCapture(index) at CAMERA_WIDTH x CAMERA_HEIGHT (requested; the driver may differ).

    index defaults to config.POKER_CAMERA_INDEX (main.py passes --camera N when given).

    Kept open for the whole session so a window starts instantly; begin_window()
    drops frames the driver buffered while nobody was reading.
    """

    def __init__(self, index: Optional[int] = None, width: Optional[int] = None,
                 height: Optional[int] = None):
        self.index = config.POKER_CAMERA_INDEX if index is None else int(index)
        self.width = width or config.CAMERA_WIDTH
        self.height = height or config.CAMERA_HEIGHT
        self._cap = None
        self.size: Optional[tuple[int, int]] = None

    def open(self) -> "Camera":
        cv2 = import_cv2()
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            cap.release()
            raise VisionUnavailable(
                f"could not open camera index {self.index}. Is the webcam plugged in (and allowed: "
                "macOS asks for camera permission for the terminal)? Try another index: --camera 1, or "
                "--camera 2 for an external USB webcam")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)        # ignored by backends that don't support it
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            raise VisionUnavailable(f"camera index {self.index} opened but delivered no frames; "
                                    "try another --camera index")
        self.size = (int(frame.shape[1]), int(frame.shape[0]))
        del frame
        self._cap = cap
        return self

    def begin_window(self) -> None:
        """Drop stale buffered frames: grab until a grab actually waits for a new frame (max 5)."""
        if self._cap is None:
            return
        for _ in range(5):
            t0 = time.monotonic()
            if not self._cap.grab():
                return
            if time.monotonic() - t0 > 0.012:      # had to wait: we're at the live frame now
                return

    def read(self):
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            time.sleep(0.02)                       # don't spin if the camera hiccups
            return None
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()


class VideoFileCamera:
    """A saved clip played like a webcam (--video), on the clip's own clock.

    now() is the video time of the frames read so far (frames / fps), so a 6 s
    window always covers 6 s of video, however fast the CPU decodes it, and the
    same clip gives the same numbers every run. loop=True rewinds at the end
    (repeated windows, --calibrate); loop=False makes read() return None there.
    """

    def __init__(self, path, loop: bool = True, fps: Optional[float] = None):
        self.path = Path(path)
        self.index = str(path)                     # shown where a camera index would be
        self.loop = loop
        self._fps_override = fps
        self.fps = 30.0
        self.size: Optional[tuple[int, int]] = None
        self.ended = False
        self._cap = None
        self._pending = None
        self._ticks = 0

    def _capture(self):
        cv2 = import_cv2()
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            cap.release()
            raise VisionUnavailable(f"could not open video {self.path} (no OpenCV decoder for it? "
                                    "try an .mp4 or an MJPG .avi)")
        return cap

    def open(self) -> "VideoFileCamera":
        if not self.path.is_file():
            raise VisionUnavailable(f"video file not found: {self.path}")
        cv2 = import_cv2()
        cap = self._capture()
        fps = self._fps_override or cap.get(cv2.CAP_PROP_FPS) or 0.0
        self.fps = float(fps) if 1.0 <= float(fps) <= 240.0 else 30.0
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            raise VisionUnavailable(f"video {self.path} has no readable frames")
        self.size = (int(frame.shape[1]), int(frame.shape[0]))
        self._pending = frame                      # no seek back: some codecs seek badly
        self._cap = cap
        return self

    def now(self) -> float:
        return self._ticks / self.fps

    def begin_window(self) -> None:
        pass                                       # nothing is buffered: the clip just continues

    def read(self):
        if self._cap is None:
            return None
        self._ticks += 1                           # the clock moves even on a failed read
        if self._pending is not None:
            frame, self._pending = self._pending, None
            return frame
        ok, frame = self._cap.read()
        if ok and frame is not None:
            return frame
        if not self.loop:
            self.ended = True
            return None
        self._cap.release()
        self._cap = self._capture()
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()


def cascade_path(name: str, cv2=None) -> Path:
    """Full path of a built-in Haar cascade XML (config.CASCADE_DIR, cv2.data, or common system dirs)."""
    candidates: list[Path] = []
    if config.CASCADE_DIR:
        candidates.append(Path(config.CASCADE_DIR) / name)
    data = getattr(cv2, "data", None) if cv2 is not None else None
    if data is not None and getattr(data, "haarcascades", None):
        candidates.append(Path(data.haarcascades) / name)
    candidates += [Path(d) / name for d in ("/usr/share/opencv4/haarcascades",
                                            "/usr/local/share/opencv4/haarcascades",
                                            "/usr/share/opencv/haarcascades")]
    for c in candidates:
        if c.is_file():
            return c
    raise VisionUnavailable(f"Haar cascade {name} not found (looked in: "
                            f"{', '.join(str(c.parent) for c in candidates)}). Set DELULU_CASCADE_DIR.")


class HaarDetector:
    """Largest frontal face (on a downscaled copy), then a smile in its lower half.

    Tunables (config.*): VISION_DETECT_WIDTH, FACE_SCALE_FACTOR, FACE_MIN_NEIGHBORS,
    FACE_MIN_SIZE_FRAC, SMILE_ROI_WIDTH, SMILE_SCALE_FACTOR (~1.7),
    SMILE_MIN_NEIGHBORS (~20), SMILE_MIN_W_FRAC / SMILE_MIN_H_FRAC (min smile
    size relative to the face). Keyword arguments override them.
    """

    def __init__(self, **overrides):
        self.cv2 = import_cv2()
        p = {k: getattr(config, k) for k in (
            "VISION_DETECT_WIDTH", "FACE_SCALE_FACTOR", "FACE_MIN_NEIGHBORS", "FACE_MIN_SIZE_FRAC",
            "SMILE_ROI_WIDTH", "SMILE_SCALE_FACTOR", "SMILE_MIN_NEIGHBORS", "SMILE_MIN_W_FRAC",
            "SMILE_MIN_H_FRAC")}
        for key, value in overrides.items():
            if key.upper() not in p:
                raise TypeError(f"unknown detector parameter {key}")
            p[key.upper()] = value
        self.params = p
        self.face = self._load(config.FACE_CASCADE)
        self.smile = self._load(config.SMILE_CASCADE)

    def _load(self, name: str):
        path = cascade_path(name, self.cv2)
        clf = self.cv2.CascadeClassifier(str(path))
        if clf.empty():
            raise VisionUnavailable(f"could not load Haar cascade {path}")
        return clf

    def detect(self, frame) -> Observation:
        cv2, p = self.cv2, self.params
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        scale = min(1.0, float(p["VISION_DETECT_WIDTH"]) / w)
        small = gray if scale >= 1.0 else cv2.resize(
            gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        small = cv2.equalizeHist(small)
        min_face = max(20, int(p["FACE_MIN_SIZE_FRAC"] * small.shape[1]))
        faces = self.face.detectMultiScale(small, scaleFactor=p["FACE_SCALE_FACTOR"],
                                           minNeighbors=p["FACE_MIN_NEIGHBORS"],
                                           minSize=(min_face, min_face))
        if len(faces) == 0:
            return Observation(face=False)
        x, y, fw, fh = max((tuple(int(v) for v in f) for f in faces), key=lambda f: f[2] * f[3])
        # back to full resolution
        X, Y = int(x / scale), int(y / scale)
        FW, FH = min(w - X, int(round(fw / scale))), min(h - Y, int(round(fh / scale)))
        face_box = (X, Y, FW, FH)
        top = Y + FH // 2
        mouth = gray[top:Y + FH, X:X + FW]
        if mouth.size == 0 or FW < 8:
            return Observation(face=True, face_box=face_box)
        roi_w = int(p["SMILE_ROI_WIDTH"])
        r = roi_w / float(FW)
        roi_h = max(1, int(round(mouth.shape[0] * r)))
        roi = cv2.resize(mouth, (roi_w, roi_h),
                         interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
        roi = cv2.equalizeHist(roi)
        min_w = max(1, int(p["SMILE_MIN_W_FRAC"] * roi_w))
        min_h = max(1, int(p["SMILE_MIN_H_FRAC"] * roi_w))
        smiles = self.smile.detectMultiScale(roi, scaleFactor=p["SMILE_SCALE_FACTOR"],
                                             minNeighbors=p["SMILE_MIN_NEIGHBORS"],
                                             minSize=(min_w, min_h))
        if len(smiles) == 0:
            return Observation(face=True, face_box=face_box)
        sx, sy, sw, sh = max((tuple(int(v) for v in s) for s in smiles), key=lambda s: s[2] * s[3])
        smile_box = (X + int(sx / r), top + int(sy / r), int(sw / r), int(sh / r))
        return Observation(face=True, smile=True, face_box=face_box, smile_box=smile_box)


def display_available() -> bool:
    """False on a headless Linux box (no X11 / Wayland), where cv2.imshow can abort the process."""
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


class PreviewWindow:
    """--preview: show the camera with the face (green) and smile (yellow) boxes during the window.

    Screen only, never saved. Turns itself off (with one warning) when there is
    no display or the OpenCV build has no GUI (opencv-python-headless), instead
    of crashing the round.
    """

    TITLE = "Hill's Kitchen - face round (preview)"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._open = False
        self.cv2 = None
        if enabled and not display_available():
            self._disable("no display found (DISPLAY / WAYLAND_DISPLAY not set)")

    def _disable(self, why: str) -> None:
        if self.enabled:
            print(f"   [warn] --preview turned off: {why}. The round runs without it.", file=sys.stderr)
        self.enabled = False

    def show(self, frame, obs: Observation, smiling: bool, elapsed_s: float, window_s: float) -> None:
        if not self.enabled:
            return
        try:
            cv2 = self.cv2 = self.cv2 or import_cv2()
            img = frame.copy()
            if obs.face_box:
                x, y, w, h = obs.face_box
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 0), 2)
            if obs.smile_box:
                x, y, w, h = obs.smile_box
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 220, 255), 2)
            label = "SMILE!" if smiling else ("face" if obs.face else "no face")
            cv2.putText(img, f"{label}  {max(0.0, window_s - elapsed_s):.1f}s", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255) if smiling else (255, 255, 255), 2)
            cv2.imshow(self.TITLE, img)
            cv2.waitKey(1)
            self._open = True
        except Exception as exc:  # noqa: BLE001 - a GUI problem must never break the round
            self._disable(f"{type(exc).__name__}: {exc}")

    def close(self) -> None:
        if self._open and self.cv2 is not None:
            try:
                self.cv2.destroyWindow(self.TITLE)
                self.cv2.waitKey(1)
            except Exception:  # noqa: BLE001
                pass
        self._open = False


# ---------------------------------------------------------------------------
# Fakes: tests and --mock (no camera, no OpenCV)
# ---------------------------------------------------------------------------
FrameSpec = tuple[bool, bool]     # (face, raw smile)


class FakeCamera:
    """Plays scripted windows of frames on a virtual clock (fps frames per second).

    Each begin_window() loads the next script from `windows`; a frame is any
    object FakeDetector understands, typically a (face, smile) tuple. None in a
    script is a read failure. Past the end of a script read() returns None.
    Use camera.now as the clock for measure_window(), so a 6 s window runs instantly.
    """

    def __init__(self, windows: Iterable[Sequence], fps: float = 15.0):
        self.fps = float(fps)
        self._windows = iter(windows)
        self._frames: list = []
        self._pos = 0
        self._ticks = 0
        self.opened = True

    def now(self) -> float:
        return self._ticks / self.fps

    def begin_window(self) -> None:
        self._frames = list(next(self._windows, []))
        self._pos = 0

    def read(self):
        self._ticks += 1
        if self._pos >= len(self._frames):
            return None
        frame = self._frames[self._pos]
        self._pos += 1
        return frame

    def close(self) -> None:
        self.opened = False


class FakeDetector:
    """Detector for FakeCamera frames: (face, smile) tuples or dicts with those keys."""

    def detect(self, frame) -> Observation:
        if isinstance(frame, Observation):
            return frame
        if isinstance(frame, dict):
            face, smile = bool(frame.get("face")), bool(frame.get("smile"))
        else:
            face, smile = bool(frame[0]), bool(frame[1])
        return Observation(face=face, smile=face and smile,
                           face_box=(200, 120, 220, 220) if face else None)


def mock_windows(seed: Optional[int], window_s: float, fps: float = 15.0):
    """Endless (face, smile) scripts for --mock --round 5.

    A simulated player with a personal "crack" tendency: most windows they hold
    a straight face with the odd one-frame detector blip (smoothing removes it),
    sometimes they crack into a smile burst after a few seconds, and about one
    window in ten they look away (-> no_face error, not scored).
    """
    rng = random.Random(seed)
    tendency = rng.uniform(0.5, 0.9)                # how likely this player cracks
    n = int(round(window_s * fps)) + 2
    while True:
        if rng.random() < 0.1:                      # looked away / walked off
            present = rng.uniform(0.1, 0.4)
            yield [(rng.random() < present, False) for _ in range(n)]
            continue
        frames = [(rng.random() > 0.03, rng.random() < 0.04) for _ in range(n)]   # blips
        if rng.random() < tendency:                 # cracked: a smile burst once the joke lands
            start = rng.randint(int(fps // 2), int(n * 0.6))
            length = int(rng.uniform(0.1, 0.6) * n)
            for i in range(start, min(n, start + length)):
                frames[i] = (True, rng.random() < 0.9)
        yield frames


class MockCamera(FakeCamera):
    """FakeCamera fed by mock_windows(): what --mock --round 5 uses instead of a webcam."""

    def __init__(self, seed: Optional[int], window_s: float, fps: float = 15.0):
        super().__init__(mock_windows(seed, window_s, fps), fps)


class FakeSignature:
    """Signature for FakeCamera frames: the "sig" number in a dict frame (None otherwise)."""

    def reset(self) -> None:
        pass

    def __call__(self, frame, obs: Observation):
        if not obs.face or not isinstance(frame, dict):
            return None
        return frame.get("sig")

    @staticmethod
    def distance(a, b) -> float:
        return abs(float(a) - float(b))


def mock_straight_windows(seed: Optional[int], max_s: float, fps: float = 15.0):
    """Endless dict-frame scripts for --mock --round 6 (with FakeDetector + FakeSignature).

    The simulated player keeps a neutral face ("sig" noise around a personal
    level) until a random moment, then their face changes (a jump in "sig",
    sometimes a smile). Some windows they hold to the end; about one in ten they
    look away (-> no_face, not scored).
    """
    rng = random.Random(seed)
    nerve = rng.uniform(0.3, 1.0)                  # fraction of max_s they tend to last
    n = int(round((max_s + 1.0) * fps))
    while True:
        level = rng.uniform(20.0, 60.0)
        if rng.random() < 0.1:
            yield [{"face": rng.random() < 0.2, "smile": False, "sig": level} for _ in range(n)]
            continue
        break_at = rng.uniform(1.5, max_s * 1.25) * nerve + rng.uniform(0.0, 3.0)
        smiles = rng.random() < 0.35
        frames = []
        for i in range(n):
            t = i / fps
            broke = t >= break_at
            frames.append({"face": rng.random() > 0.02,
                           "smile": broke and smiles and rng.random() < 0.9,
                           "sig": level + rng.gauss(0.0, 0.8) + (rng.uniform(18, 30) if broke else 0.0)})
        yield frames


class MockStraightCamera(FakeCamera):
    """FakeCamera fed by mock_straight_windows(): --mock --round 6's webcam."""

    def __init__(self, seed: Optional[int], max_s: float, fps: float = 15.0):
        super().__init__(mock_straight_windows(seed, max_s, fps), fps)


# ---------------------------------------------------------------------------
# Command line: measure a saved clip (calibration without the Arduino)
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run Hill's Kitchen's face measurements on a saved video clip or a webcam "
                    "(no Arduino, nothing saved). Prints the numbers per window.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", metavar="PATH", help="video file to measure (.mp4, .avi, ...)")
    src.add_argument("--camera", type=int, metavar="N", help="webcam index instead of a clip")
    ap.add_argument("--round", choices=("poker", "straight"), default="straight",
                    help="poker = smile fraction per window; straight = seconds until the face changes")
    ap.add_argument("--windows", type=int, default=1, help="how many windows to measure (default 1)")
    ap.add_argument("--window-s", type=float, default=None,
                    help=f"window length (default {config.POKER_WINDOW_S:g} s for poker, "
                         f"{config.STRAIGHT_MAX_S:g} s for straight)")
    ap.add_argument("--no-loop", action="store_true", help="stop at the end of the clip instead of rewinding")
    ap.add_argument("--preview", action="store_true", help="show the frames with the detector boxes")
    args = ap.parse_args(argv)
    straight = args.round == "straight"
    window_s = args.window_s or (config.STRAIGHT_MAX_S if straight else config.POKER_WINDOW_S)
    try:
        if args.video:
            camera = VideoFileCamera(args.video, loop=not args.no_loop).open()
            clock = camera.now
        else:
            camera = Camera(args.camera).open()
            clock = time.monotonic
        detector = HaarDetector()
        signature = FaceSignature() if straight else None
    except VisionUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    preview = PreviewWindow() if args.preview else None
    print(f"{args.round} | source {camera.index} {camera.size} | window {window_s:g} s")
    try:
        for i in range(1, max(1, args.windows) + 1):
            camera.begin_window()
            if straight:
                show = ((lambda f, o, info: preview.show(f, o, info["smiling"], info["elapsed"], window_s))
                        if preview else None)
                st = measure_straight_face(camera, detector, signature, window_s, clock=clock, on_frame=show)
                if not st.baseline_ok:
                    verdict = "NO BASELINE (no face)"
                elif st.broke:
                    verdict = f"changed at {st.changed_at_s:.2f} s ({st.trigger})"
                else:
                    verdict = f"held the full {window_s:g} s"
                thr = f"{st.threshold:.1f}" if st.threshold is not None else "-"
                base = (f"{st.baseline_mean:.1f}+/-{st.baseline_std:.1f}"
                        if st.baseline_mean is not None else "-")
                print(f"  window {i}: {verdict} | held {st.held_s:.2f} s | baseline {base} | "
                      f"threshold {thr} | peak {st.peak_score:.1f} | face {st.face_frac * 100:.0f}% | "
                      f"{st.frames} frames @ {st.fps:.1f} fps")
            else:
                show = (lambda f, o, s, e: preview.show(f, o, s, e, window_s)) if preview else None
                st = measure_window(camera, detector, window_s, clock=clock, on_frame=show)
                first = "-" if st.first_smile_ms is None else f"{st.first_smile_ms / 1000:.2f} s"
                print(f"  window {i}: smile {st.smile_frac * 100:.1f}% of face frames | "
                      f"face {st.face_frac * 100:.0f}% | first smile {first} | "
                      f"{st.frames} frames @ {st.fps:.1f} fps")
            if getattr(camera, "ended", False):
                print("  (end of clip)")
                break
    finally:
        if preview:
            preview.close()
        camera.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
