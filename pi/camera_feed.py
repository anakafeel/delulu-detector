"""Live camera for the browser (the face rounds): a latest-frame slot and on-demand MJPEG.

Serves GET /api/camera.mjpg (pi/ui_server.py) with the frames the Poker Face and
Straight Face measurements already read (pi/poker_round.py, pi/straight_round.py).
The camera is never opened a second time.

Hand-off (the measurement loop must never wait for the browser):
    producer   the round calls offer(frame, obs, smiling[, elapsed, extra]) per frame. That
               only swaps references in ONE slot (the newest frame replaces the
               previous one; there is no queue that could grow) and bumps a
               sequence number. No drawing, no encoding, no I/O, never raises.
    consumers  each /api/camera.mjpg request (an HTTP thread) takes the newest
               frame at most UI_CAMERA_FPS times a second, draws the face / smile
               boxes and the live smile %, scales it to UI_CAMERA_MAX_WIDTH and
               encodes a JPEG (cv2 releases the GIL while it works). Several
               browsers share one encoded JPEG per frame. Nothing is encoded when
               nobody is watching.

Privacy: frames live only in memory. The slot holds at most the newest frame,
and end() drops it when the window (or preview) stops. Nothing here writes a
frame to disk or sends it anywhere but the local browser that asked for it.

Modes: "measuring" (the scored window), "preview" (while the claim is being set;
raw detector output, not scored) or None (camera not being read: the endpoint
shows a "camera paused" placeholder).
Kinds (set by begin()): "poker" shows the live smile % (the same number the round
uses: smoothed smiling face frames / face frames so far); "straight" shows the
seconds held, a level bar (difference from the neutral baseline / threshold) and
an "expression change" marker, from the `extra` dict measure_straight_face passes.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, Optional

import config

MODES = ("measuring", "preview")
KINDS = ("poker", "straight")
_NOTIFY_MIN_S = 0.25          # push the live smile % to the browsers at most 4x a second


class CameraFeed:
    """Latest-frame slot shared by the measurement loop (producer) and the MJPEG handlers."""

    def __init__(self, fps: Optional[float] = None, max_width: Optional[int] = None,
                 quality: Optional[int] = None, mirror: Optional[bool] = None,
                 renderer: Optional[Callable[[Any, Any, dict], bytes]] = None,
                 placeholder_renderer: Optional[Callable[[], Optional[bytes]]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.fps = float(config.UI_CAMERA_FPS if fps is None else fps)
        self.max_width = int(config.UI_CAMERA_MAX_WIDTH if max_width is None else max_width)
        self.quality = int(config.UI_CAMERA_JPEG_QUALITY if quality is None else quality)
        self.mirror = bool(config.UI_CAMERA_MIRROR if mirror is None else mirror)
        self._render = renderer or self._render_cv2
        self._render_placeholder = placeholder_renderer or self._placeholder_cv2
        self._clock = clock
        self._cv2 = None
        self._cond = threading.Condition()
        self._errors_reported: set[str] = set()
        # the slot (guarded by _cond)
        self._frame: Any = None
        self._obs: Any = None
        self._seq = 0
        self._jpeg: Optional[bytes] = None
        self._jpeg_seq = 0
        # what's going on (guarded by _cond)
        self._mode: Optional[str] = None
        self._window_s: Optional[float] = None
        self._kind = "poker"
        self._extra: dict = {}
        self._elapsed_s = 0.0
        self._face = False
        self._smiling = False
        self._face_frames = 0
        self._smile_frames = 0
        self._viewers = 0
        self._placeholder: Optional[bytes] = None
        self._placeholder_done = False
        # UI hook GameState.poke(full): full=True on a mode change (goes into the state
        # snapshot), False for the fast numbers (a small SSE "live" event). Called outside _cond.
        self._notify: Optional[Callable[[bool], None]] = None
        self._last_notify_at = float("-inf")
        self._last_notified: Optional[dict] = None

    # ------------------------------------------------------------ internals
    def _report_error(self, where: str, exc: BaseException) -> None:
        if where in self._errors_reported:
            return
        self._errors_reported.add(where)
        print(f"   [camera feed] {where} failed ({type(exc).__name__}: {exc}); the round carries on "
              "(browser camera only). (Reported once.)", file=sys.stderr)

    def set_notify(self, fn: Optional[Callable[[bool], None]]) -> None:
        self._notify = fn

    def _maybe_notify(self, force: bool = False) -> None:
        fn = self._notify
        if fn is None:
            return
        try:
            now = self._clock()
            if not force and now - self._last_notify_at < _NOTIFY_MIN_S:
                return
            current = self.live_state()
            if not force and current == self._last_notified:
                return
            self._last_notify_at, self._last_notified = now, current
            fn(force)
        except Exception as exc:  # noqa: BLE001 - the UI hook must never hurt the caller
            self._report_error("notifying the UI", exc)

    # ------------------------------------------------ producer (game thread)
    def begin(self, mode: str, window_s: Optional[float] = None, kind: str = "poker") -> None:
        """Frames of `mode` ("measuring" / "preview") start flowing. Never raises."""
        try:
            with self._cond:
                self._mode = mode if mode in MODES else "preview"
                self._window_s = window_s
                self._kind = kind if kind in KINDS else "poker"
                self._extra = {}
                self._frame = self._obs = self._jpeg = None   # never show a frame from the last mode
                self._elapsed_s = 0.0
                self._face = self._smiling = False
                self._face_frames = self._smile_frames = 0
                self._cond.notify_all()
        except Exception as exc:  # noqa: BLE001
            self._report_error("begin", exc)
        self._maybe_notify(force=True)

    def offer(self, frame, obs, smiling: bool, elapsed_s: float = 0.0,
              extra: Optional[dict] = None) -> None:
        """Newest frame + what the detector saw. O(1): swaps references, never blocks long or raises."""
        try:
            with self._cond:
                if self._mode is None:
                    return
                self._frame, self._obs = frame, obs
                if extra is not None:
                    self._extra = extra
                self._seq += 1
                face = bool(getattr(obs, "face", False))
                self._face, self._smiling = face, bool(smiling) and face
                self._elapsed_s = float(elapsed_s)
                if face and self._mode == "measuring":
                    self._face_frames += 1
                    if smiling:
                        self._smile_frames += 1
                self._cond.notify_all()
        except Exception as exc:  # noqa: BLE001 - a stream problem must never break the round
            self._report_error("offer", exc)

    def end(self, mode: Optional[str] = None) -> None:
        """Stop showing frames (drops the last one). With `mode`, only if that mode is current."""
        try:
            with self._cond:
                if mode is not None and self._mode != mode:
                    return
                self._mode = None
                self._frame = self._obs = self._jpeg = None
                self._face = self._smiling = False
                self._cond.notify_all()
        except Exception as exc:  # noqa: BLE001
            self._report_error("end", exc)
            return
        self._maybe_notify(force=True)

    @property
    def mode(self) -> Optional[str]:
        return self._mode

    # ------------------------------------------------ consumers (HTTP threads)
    def add_viewer(self) -> None:
        with self._cond:
            self._viewers += 1

    def remove_viewer(self) -> None:
        with self._cond:
            self._viewers = max(0, self._viewers - 1)

    @property
    def viewers(self) -> int:
        return self._viewers

    def _info_locked(self) -> dict:
        smile_frac = (self._smile_frames / self._face_frames
                      if self._mode == "measuring" and self._face_frames else None)
        remaining = (max(0.0, self._window_s - self._elapsed_s)
                     if self._mode == "measuring" and self._window_s else None)
        info = {"mode": self._mode, "face": self._face, "smiling": self._smiling,
                "smile_frac": smile_frac, "remaining_s": remaining, "kind": self._kind}
        if self._kind == "straight" and self._mode == "measuring":
            x = self._extra
            info.update(phase=x.get("phase"), held_s=x.get("held_s"),
                        changed_at_s=x.get("changed_at_s"), trigger=x.get("trigger"),
                        level=x.get("level"))
        return info

    def wait_jpeg(self, last_seq: int, timeout: float) -> Optional[tuple[int, bytes]]:
        """Newest frame newer than last_seq as (seq, jpeg), or None after `timeout` without one.

        Encodes outside the lock, so the producer is never held up; a JPEG already
        made for this frame (by another browser) is reused.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._frame is None or self._seq == last_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            seq = self._seq
            if self._jpeg is not None and self._jpeg_seq == seq:
                return seq, self._jpeg
            frame, obs, info = self._frame, self._obs, self._info_locked()
        jpeg = self._render(frame, obs, info)
        del frame
        with self._cond:
            if self._frame is not None and seq >= self._jpeg_seq:
                self._jpeg, self._jpeg_seq = jpeg, seq
        self._maybe_notify()
        return seq, jpeg

    def placeholder(self) -> Optional[bytes]:
        """JPEG shown while the camera isn't being read (made once). None if it can't be made."""
        if not self._placeholder_done:
            self._placeholder_done = True
            try:
                self._placeholder = self._render_placeholder()
            except Exception as exc:  # noqa: BLE001
                self._report_error("placeholder", exc)
        return self._placeholder

    def summary(self) -> dict:
        """The slow part ("camera" in the state snapshot): changes only when a window/preview starts or stops."""
        return {"available": True, "mode": self._mode, "kind": self._kind}

    def live_state(self) -> dict:
        """The fast part (SSE "live" event): what the detector sees now, and the smile % so far
        (Poker Face) or the seconds held / level / change marker (Straight Face)."""
        with self._cond:
            info = self._info_locked()
        frac = info["smile_frac"]
        live = {"mode": info["mode"], "face": info["face"], "smiling": info["smiling"],
                "smilePct": None if frac is None else int(round(frac * 100))}
        if "phase" in info:
            held, changed, level = info["held_s"], info["changed_at_s"], info["level"]
            live.update(phase=info["phase"],
                        heldS=None if held is None else round(float(held), 1),
                        changedAtS=None if changed is None else round(float(changed), 1),
                        trigger=info["trigger"],
                        level=None if level is None else round(min(float(level), 9.99), 2))
        return live

    def public_state(self) -> dict:
        """Both parts (GET /api/state, for polling clients)."""
        return {"available": True, **self.live_state()}

    # ------------------------------------------------------------ rendering
    def _cv(self):
        if self._cv2 is None:
            import vision  # noqa: PLC0415 - OpenCV stays lazy (vision imports it on demand)
            self._cv2 = vision.import_cv2()
        return self._cv2

    def _render_cv2(self, frame, obs, info: dict) -> bytes:
        """Scaled, mirrored copy of the frame with boxes and the live numbers, as JPEG bytes."""
        cv2 = self._cv()
        img = frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        h, w = img.shape[:2]
        s = min(1.0, self.max_width / float(w))
        if s < 1.0:
            img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        img = cv2.flip(img, 1) if self.mirror else img.copy()    # never draw on the measured frame
        H, W = img.shape[:2]

        def box(b, color):
            if not b:
                return
            x, y, bw, bh = (int(round(v * s)) for v in b)
            if self.mirror:
                x = W - x - bw
            cv2.rectangle(img, (x, y), (x + bw, y + bh), color, 2)

        box(getattr(obs, "face_box", None), (80, 220, 80))
        box(getattr(obs, "smile_box", None), (0, 220, 255))
        font = cv2.FONT_HERSHEY_SIMPLEX
        bar = max(24, H // 14)
        fs = bar / 40.0
        for y0, y1 in ((0, bar), (H - bar, H)):                # darken top and bottom strips
            img[y0:y1] = cv2.convertScaleAbs(img[y0:y1], alpha=0.35)
        smiling, face = info.get("smiling"), info.get("face")
        changed = info.get("phase") == "changed"
        label = "CHANGE!" if changed else "SMILE!" if smiling else ("face" if face else "no face")
        color = ((60, 60, 255) if (smiling or changed)
                 else ((255, 255, 255) if face else (150, 150, 150)))
        cv2.putText(img, label, (8, int(bar * 0.72)), font, fs, color, 2, cv2.LINE_AA)
        if info.get("mode") == "measuring" and info.get("kind") == "straight":
            held = info.get("held_s")
            right = "held --" if held is None else f"held {held:.1f}s"
            phase = info.get("phase")
            if changed:
                at = info.get("changed_at_s") or 0.0
                bottom = f"expression change @ {at:.1f}s" + (" (smile)" if info.get("trigger") == "smile" else "")
                cv2.rectangle(img, (1, bar), (W - 2, H - bar), (60, 60, 255), 3)   # the marker
            elif phase == "baseline":
                bottom = "reading your neutral face..."
            else:
                bottom = "hold that straight face"
                level = info.get("level")
                if level is not None:                    # difference / threshold, threshold at 2/3
                    x0, x1 = W // 2, W - 10
                    y0, y1 = H - int(bar * 0.75), H - int(bar * 0.3)
                    cv2.rectangle(img, (x0, y0), (x1, y1), (120, 120, 120), 1)
                    fill = x0 + int((x1 - x0) * min(level / 1.5, 1.0))
                    col = (60, 60, 255) if level >= 1.0 else (80, 220, 80)
                    cv2.rectangle(img, (x0, y0), (max(x0, fill), y1), col, -1)
                    tx = x0 + int((x1 - x0) / 1.5)
                    cv2.line(img, (tx, y0 - 2), (tx, y1 + 2), (255, 255, 255), 1)
        elif info.get("mode") == "measuring":
            frac = info.get("smile_frac")
            right = "smiling --" if frac is None else f"smiling {frac * 100:.0f}%"
            rem = info.get("remaining_s")
            bottom = "measuring" + ("" if rem is None else f"  {rem:.1f}s left")
        else:
            right = "PREVIEW"
            bottom = "not scored - frame your face, then lock"
        (tw, _), _ = cv2.getTextSize(right, font, fs, 2)
        cv2.putText(img, right, (W - tw - 8, int(bar * 0.72)), font, fs, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, bottom, (8, H - int(bar * 0.28)), font, fs * 0.8, (220, 220, 220), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            raise RuntimeError("cv2.imencode failed")
        return buf.tobytes()

    def _placeholder_cv2(self) -> Optional[bytes]:
        cv2 = self._cv()
        import numpy as np  # noqa: PLC0415 - comes with opencv-python
        img = np.full((240, 320, 3), (24, 14, 14), np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        for text, y, fs in (("camera paused", 112, 0.8), ("live during the face rounds", 146, 0.5)):
            (tw, _), _ = cv2.getTextSize(text, font, fs, 1)
            cv2.putText(img, text, ((320 - tw) // 2, y), font, fs, (200, 200, 200), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        return buf.tobytes() if ok else None
