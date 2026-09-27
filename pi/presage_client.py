"""Presage SmartSpectra composure for the face rounds.

The webcam stays the one vision.py already opened. This module pushes those
BGR frames into the SmartSpectra Node SDK (pi/presage/bridge.mjs), which
computes facial-expression scores on the machine. The API key only authorizes
the session. Composure is the SDK's neutral-expression confidence, 0-100,
averaged over the frames it actually classified.

There is no offline number. A missing key, a dead bridge, a timeout, an SDK
error, or a window with no expression sample raises PresageError.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

import config

_HEADER = "<4sIIIQ"
_MAGIC = b"FRM1"
# The SDK rejects a gap above 2s between frames it actually receives.
# Sending is slower than the camera, so a stall has to be clamped under that.
_MAX_FRAME_GAP_US = 1_000_000


def pace_timestamp(last: int | None, now: int, max_gap_us: int = _MAX_FRAME_GAP_US) -> int:
    """Strictly increasing timestamp that never jumps by more than max_gap_us."""
    if last is None:
        return now
    delta = now - last
    if delta < 1:
        delta = 1
    elif delta > max_gap_us:
        delta = max_gap_us
    return last + delta


class PresageError(Exception):
    """The composure measurement did not happen. Callers must not invent a value."""


class PresageSession:
    """One SmartSpectra session for one face-round process."""

    def __init__(self, command: list[str] | None = None, env: dict | None = None,
                 ready_timeout_s: float | None = None):
        self.command = command if command is not None else _default_command()
        self.env = env
        self.ready_timeout_s = (config.PRESAGE_READY_TIMEOUT_S if ready_timeout_s is None
                                else ready_timeout_s)
        self._proc: subprocess.Popen | None = None
        self._samples: list[float] = []
        self._error: str | None = None
        self._ready = threading.Event()
        self._slot: np.ndarray | None = None
        self._slot_cv = threading.Condition()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_ts: int | None = None
        self._window_note: str | None = None
        self._hold = False
        self._restarting = False
        self.last_sample_count: int | None = None   # samples Presage classified in the last window

    def start(self) -> None:
        """Start the bridge and wait until the SDK has authorized the key.

        Raises PresageError if the key is missing, the SDK fails to start, or
        the bridge does not become ready in time.
        """
        if not _key_from_env(self.env) and self.command == _default_command():
            raise PresageError("SMARTSPECTRA_API_KEY is not set")
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_child_env(self.env),
            )
        except OSError as exc:
            raise PresageError(f"could not start the Presage bridge: {exc}") from exc
        self._reader = threading.Thread(target=self._read_stdout, name="presage-read", daemon=True)
        self._writer = threading.Thread(target=self._write_frames, name="presage-write", daemon=True)
        self._reader.start()
        self._writer.start()
        if not self._ready.wait(self.ready_timeout_s):
            message = self._error or "Presage did not become ready before the timeout"
            self.close()
            raise PresageError(message)
        if self._error:
            message = self._error
            self.close()
            raise PresageError(message)

    def push(self, frame: np.ndarray) -> None:
        """Queue the newest BGR frame. Drops older frames still waiting to be sent."""
        if self._hold:
            return
        self._raise_if_failed()
        if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[2] != 3:
            raise PresageError("Presage expected a BGR frame")
        # OpenCV frames are BGR. The SDK sample path is RGB.
        copied = np.ascontiguousarray(frame[:, :, ::-1])
        with self._slot_cv:
            self._slot = copied
            self._slot_cv.notify()

    def latest(self) -> float | None:
        """Mean composure so far, or None if Presage has not classified a frame yet."""
        with self._lock:
            if not self._samples:
                return None
            return sum(self._samples) / len(self._samples)

    def finish(self) -> float:
        """Composure for the window that just ended. Raises if nothing was measured.

        Samples already received are the score. A later SDK error does not erase
        them and does not get averaged into the next claim.
        """
        with self._lock:
            samples = list(self._samples)
            self._samples.clear()
            note = self._window_note
            self._window_note = None
            err = self._error
        self.last_sample_count = len(samples)
        if not samples:
            raise PresageError(err or note or "Presage returned no composure sample for this window")
        return sum(samples) / len(samples)

    def close(self) -> None:
        self._stop.set()
        with self._slot_cv:
            self._slot_cv.notify_all()
        proc = self._proc
        if proc is not None and proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        if proc is not None:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None

    def _raise_if_failed(self) -> None:
        if self._error:
            raise PresageError(self._error)
        proc = self._proc
        if proc is not None and proc.poll() is not None and not self._ready.is_set():
            raise PresageError(self._error or "Presage bridge exited before it was ready")
        if proc is not None and proc.poll() is not None:
            raise PresageError(self._error or "Presage bridge exited")

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._fail(f"Presage bridge sent a non-JSON line: {line[:160]}")
                return
            kind = msg.get("type")
            if kind == "ready":
                self._ready.set()
            elif kind == "sample":
                value = msg.get("composure")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    self._fail("Presage sample was not a number")
                    return
                number = float(value)
                if number < 0.0 or number > 100.0:
                    self._fail(f"Presage composure {number} is outside 0-100")
                    return
                with self._lock:
                    self._samples.append(number)
            elif kind == "validation":
                with self._lock:
                    self._last_validation = f"{msg.get('code')}: {msg.get('hint') or ''}".strip()
            elif kind == "error":
                detail = str(msg.get("message") or "Presage error")
                code = msg.get("code")
                if code is not None:
                    detail = f"{detail} (code {code})"
                hint = None
                with self._lock:
                    hint = getattr(self, "_last_validation", None)
                if hint:
                    detail = f"{detail}; last camera check {hint}"
                with self._lock:
                    have_samples = bool(self._samples)
                if have_samples:
                    # The SDK will not score further frames on this session.
                    # Keep the samples this window already returned.
                    self._window_note = detail
                    self._hold = True
                    self._schedule_restart()
                    return
                self._fail(detail)
                self._schedule_restart()
                return
            else:
                self._fail(f"Presage bridge sent an unknown message type: {kind}")
                return
        if not self._ready.is_set():
            err = ""
            if proc.stderr is not None:
                err = proc.stderr.read().decode("utf-8", "replace").strip()
            self._fail(err or "Presage bridge closed its output before it was ready")

    def _fail(self, message: str) -> None:
        self._error = message
        self._ready.set()
        with self._slot_cv:
            self._slot_cv.notify_all()

    def _schedule_restart(self) -> None:
        """Start a new SDK process so the next claim is not stuck on this error."""
        if self.command != _default_command() or self._restarting:
            return
        self._restarting = True
        threading.Thread(target=self._restart, name="presage-restart", daemon=True).start()

    def _restart(self) -> None:
        try:
            self.close()
            writer = self._writer
            if writer is not None and writer.is_alive():
                writer.join(timeout=1)
            self._stop = threading.Event()
            self._error = None
            self._window_note = None
            self._hold = False
            self._last_ts = None
            self._ready = threading.Event()
            with self._lock:
                self._samples.clear()
            self.start()
        except PresageError as exc:
            self._error = str(exc)
        finally:
            self._restarting = False

    def _write_frames(self) -> None:
        import struct
        pack = struct.Struct(_HEADER).pack
        while not self._stop.is_set():
            with self._slot_cv:
                while self._slot is None and not self._stop.is_set():
                    self._slot_cv.wait(timeout=0.2)
                frame = self._slot
                self._slot = None
            if frame is None or self._stop.is_set():
                continue
            proc = self._proc
            if proc is None or proc.stdin is None or proc.poll() is not None:
                self._fail(self._error or "Presage bridge is not running")
                return
            height, width = frame.shape[:2]
            stride = int(frame.strides[0])
            timestamp_us = pace_timestamp(self._last_ts, time.time_ns() // 1000)
            self._last_ts = timestamp_us
            try:
                proc.stdin.write(pack(_MAGIC, int(width), int(height), stride, timestamp_us))
                proc.stdin.write(frame.tobytes())
                proc.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                self._fail(self._error or f"could not send a frame to Presage: {exc}")
                return


def _default_command() -> list[str]:
    bridge = Path(__file__).resolve().parent / "presage" / "bridge.mjs"
    node = os.environ.get("PRESAGE_NODE", "node")
    return [node, str(bridge)]


def _key_from_env(overlay: dict | None) -> str:
    if overlay is not None:
        return (overlay.get("SMARTSPECTRA_API_KEY") or overlay.get("PRESAGE_API_KEY") or "").strip()
    return (os.environ.get("SMARTSPECTRA_API_KEY") or os.environ.get("PRESAGE_API_KEY") or "").strip()


def _child_env(overlay: dict | None) -> dict:
    env = os.environ.copy()
    if overlay:
        env.update(overlay)
    key = (env.get("SMARTSPECTRA_API_KEY") or env.get("PRESAGE_API_KEY") or "").strip()
    if key:
        env["SMARTSPECTRA_API_KEY"] = key
    return env
