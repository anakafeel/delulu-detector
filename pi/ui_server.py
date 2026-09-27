"""Live game state for the browser UI (frontend/), served by a tiny stdlib HTTP server.

Enabled with `python pi/main.py --ui` (see main.py). Two parts:

GameState
    The single source of truth for what the browser shows. main.py calls one
    method per game event (Arduino status line, locked claim, scored result,
    verdict text, rejected round, ...). Every method is crash-safe: a bug in
    here is reported once on stderr and swallowed, so the UI can never break a
    round. The state is shaped the way frontend/src/data/useGameState.js expects:
        {"screen": "idle" | "predicting" | "performing" | "reveal",
         "player", "activeRound", "liveClaim", "latestResult", "history": [...], ...}
    plus extras (leaderboard, mostDelulu, board, notice, camera, version).

UIServer
    ThreadingHTTPServer in a daemon thread:
        GET /api/state    current state as JSON
        GET /api/events   Server-Sent Events: the full state again on every change,
                          except a knob turn, which is a small `event: dial` with
                          {"liveClaim": N} (the full state is ~100 KB with history), and
                          the camera's fast numbers, which are a small `event: live` with
                          {"camera": {mode, face, smiling, smilePct, ...}} (at most 4/s)
        GET /api/health   {"ok": true}
        POST /api/player  {"name": "..."}: Poker Face name entry (the player types it on
                          the booth screen before dialing); the next claim is logged under it
        GET /api/camera.mjpg  live webcam (MJPEG) with the OpenCV overlay, from the
                          frames the face rounds already read (camera_feed.py);
                          503 when there is no camera feed (Reflex, --mock)
        GET /...          frontend/dist (the `npm run build` output) if present,
                          so no Node is needed at the venue
    CORS is open (local data; the one write is the player name) so a Vite dev server on another port works.

Stdlib only (the camera JPEGs are made by camera_feed.py with OpenCV). Nothing here
touches the serial port, SQLite writes or audio, or writes a camera frame anywhere.
"""
from __future__ import annotations

import functools
import json
import math
import mimetypes
import select
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlsplit

import config

# Python round type -> the frontend's string round id (frontend/src/data/roundDefs.js).
# The Tell plays 1 / 5 / 6 (labelled Round 1 / 2 / 3: config.ROUND_LABELS); 2 and 3 are
# the cut Steady Hands / Retreat, kept so old session rows still render.
ROUND_KEYS = {1: "reflex", 2: "steady_hands", 3: "retreat", 5: "poker_face", 6: "straight_face"}
ROUND_DISPLAY_NAMES = {1: "Reflex", 2: "Steady Hands", 3: "Retreat", 5: "Poker Face",
                       6: "Straight Face Under Pressure"}

SCREENS = ("idle", "predicting", "performing", "reveal")

# Arduino status states that mean "a round is running, claim locked" (and what's happening).
_PERFORMING_STATES = {"locked", "cue", "countdown", "hold", "false_start", "window"}

SSE_KEEPALIVE_S = 15.0
_MAX_POST_BYTES = 1024
MJPEG_BOUNDARY = "delulu-frame"
_MJPEG_IDLE_S = 1.0        # no new frame for this long -> the "camera paused" placeholder
_MJPEG_PLACEHOLDER_EVERY_S = 2.0   # ...re-sent this often (also notices a closed browser tab)
_SSE_POLL_S = 0.5          # also catches time-based changes (reveal hold ending)


def clean_player_name(raw) -> Optional[str]:
    """A typed name -> what gets logged: printable, single-spaced, at most UI_PLAYER_NAME_MAX
    characters. None if nothing usable is left."""
    if not isinstance(raw, str):
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in raw)
    text = " ".join(text.split())[:config.UI_PLAYER_NAME_MAX].strip()
    return text or None


def round_key(round_id: Optional[int]) -> Optional[str]:
    if round_id is None:
        return None
    return ROUND_KEYS.get(round_id, f"round_{round_id}")


def round_name(round_id: Optional[int]) -> Optional[str]:
    if round_id is None:
        return None
    return ROUND_DISPLAY_NAMES.get(round_id) or config.ROUND_NAMES.get(round_id, f"Round {round_id}")


def _num(value, digits: int = 1):
    """JSON-safe number: None stays None, NaN/inf become None, floats get rounded."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, digits)


def _int(value) -> Optional[int]:
    f = _num(value, 0)
    return None if f is None else int(f)


def _safe_extra(extra) -> dict:
    if not isinstance(extra, dict):
        return {}
    out = {}
    for k, v in extra.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[str(k)] = _num(v, 3)
        elif v is None or isinstance(v, (str, bool)):
            out[str(k)] = v
    return out


def active_round(round_id: Optional[int]) -> Optional[dict]:
    if round_id is None:
        return None
    info = {"round_id": round_key(round_id), "round_type_id": round_id, "round_name": round_name(round_id),
            "round_label": config.ROUND_LABELS.get(round_id)}
    if round_id == 6:                  # Straight Face: the dial's 0-100 stands for 0-max seconds
        info["claim_max_s"] = _num(config.STRAIGHT_MAX_S, 1)
    return info


def result_from_row(row: dict, verdict_text: Optional[str] = None) -> dict:
    """One `rounds` row (SessionLog.rounds()) -> a result in the frontend's shape.

    round_id is unique per result ("reflex-12", like the frontend mock) so the
    reveal re-animates for every round; round_key is the round type id.
    """
    rid = int(row["round_id"])
    extra = row.get("extra")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError:
            extra = None
    raw = row.get("actual")
    if raw is None:
        raw = row.get("actual_ms")
    unit = row.get("unit") or ("ms" if rid == 1 else None)
    gap = _num(row.get("gap"))
    return {
        "round_id": f"{round_key(rid)}-{row.get('id')}",
        "db_id": row.get("id"),
        "round_key": round_key(rid),
        "round_type_id": rid,
        "round_name": round_name(rid),
        "round_label": config.ROUND_LABELS.get(rid),
        "round_number": row.get("round_number"),
        "session_id": row.get("session_id"),
        "player": row.get("player"),
        "claim": _int(row.get("claim")),
        "actual": _num(row.get("performance")),       # 0-100 normalized reality
        "actual_raw": _num(raw, 1),                    # raw measurement in `actual_unit`
        "actual_unit": unit,                           # "ms" | "mg_rms" | "smile_pct" | "s"
        "gap": gap,
        "score": row.get("score"),
        "tier": row.get("tier"),
        "direction": _direction(row.get("claim"), row.get("performance")),
        "false_start": bool(row.get("false_start")),
        "timeout": bool(row.get("timeout")),
        "scored": gap is not None,
        "extra": _safe_extra(extra),
        "verdict_text": verdict_text,
        "verdict_status": "ready" if verdict_text else "pending",
        "timestamp": row.get("ts"),
    }


def _direction(claim, performance) -> str:
    if claim is None or performance is None:
        return "n/a"
    if abs(float(claim) - float(performance)) < 0.5:
        return "spot_on"
    return "over" if float(claim) > float(performance) else "under"


def result_from_round(result, player: str, session_id: str, round_number: int,
                      db_id=None, verdict_text: Optional[str] = None) -> dict:
    """A scoring.RoundResult (just played) -> a result in the frontend's shape."""
    row = {
        "id": db_id if db_id is not None else f"s{round_number}",
        "round_id": result.round_id, "round_number": round_number, "session_id": session_id,
        "player": player, "claim": result.claim, "performance": result.performance,
        "actual": result.actual, "unit": result.unit, "gap": result.gap, "score": result.score,
        "tier": result.tier, "false_start": result.false_start, "timeout": result.timeout,
        "extra": result.extra, "ts": datetime.now(timezone.utc).isoformat(),
    }
    out = result_from_row(row, verdict_text)
    out["direction"] = result.direction
    return out


def _crash_safe(method):
    """Never let a UI problem escape into the game loop."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - the UI must never break a round
            self._report_error(method.__name__, exc)
            return None
    return wrapper


class GameState:
    """Thread-safe live state. main.py writes (one thread), HTTP threads read."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 reveal_hold_s: Optional[float] = None, idle_after_s: Optional[float] = None,
                 history_limit: Optional[int] = None, reveal_min_s: Optional[float] = None):
        self._clock = clock
        self.reveal_hold_s = config.UI_REVEAL_HOLD_S if reveal_hold_s is None else reveal_hold_s
        self.reveal_min_s = config.UI_REVEAL_MIN_S if reveal_min_s is None else reveal_min_s
        self.idle_after_s = config.UI_IDLE_AFTER_S if idle_after_s is None else idle_after_s
        self.history_limit = config.UI_HISTORY_LIMIT if history_limit is None else history_limit
        self._cond = threading.Condition()
        self._errors_reported: set[str] = set()
        self.version = 0
        self.live_version = 0          # bumps for the camera's fast numbers (SSE `live` events only)
        self.player: Optional[str] = None      # the fallback name (--player, or "Guest")
        self.name_entry = False        # Poker Face --ui: players type their name before dialing
        self.named_player: Optional[str] = None
        self._activity_at = clock()    # last name / dial / claim / result: the name expires with idle
        self.session_id: Optional[str] = None
        self.selected_round: Optional[int] = None
        self.mock = False
        self.phase = "idle"
        self.phase_since = clock()
        self.armed = False             # the board acknowledged the round / is waiting for a claim
        self.stage: Optional[str] = None   # last Arduino status state (locked, cue, hold, ...)
        self.active_round_id: Optional[int] = None
        self.live_claim: Optional[float] = None
        self.dial_value: Optional[int] = None   # live knob position ({"type":"dial"}), newer sketches only
        self.latest_result: Optional[dict] = None
        self.history: list[dict] = []
        self.leaderboard: list[dict] = []
        self.most_delulu: Optional[dict] = None
        self.notice: Optional[dict] = None
        self._verdicts: dict = {}      # result round_id -> verdict text (not stored in SQLite)
        self.camera_feed = None        # camera_feed.CameraFeed: face rounds with a real camera only

    # ------------------------------------------------------------ internals
    def _report_error(self, where: str, exc: Exception) -> None:
        if where in self._errors_reported:
            return
        self._errors_reported.add(where)
        print(f"   [ui] {where} failed ({type(exc).__name__}: {exc}); the game carries on. "
              "(Reported once.)", file=sys.stderr)

    def _set_phase(self, phase: str) -> None:
        if phase != self.phase:
            self.phase = phase
        self.phase_since = self._clock()

    def _changed(self) -> None:
        self.version += 1
        self._cond.notify_all()

    def _effective_screen(self) -> str:
        """The phase, with time-based transitions applied (reveal hold, idle timeout)."""
        elapsed = self._clock() - self.phase_since
        if self.phase == "reveal" and elapsed >= self.reveal_hold_s:
            if not self.armed:
                return "idle"
            return "idle" if elapsed >= self.reveal_hold_s + self.idle_after_s else "predicting"
        if self.phase == "predicting" and elapsed >= self.idle_after_s:
            return "idle"
        return self.phase

    # --------------------------------------------------------------- events
    @_crash_safe
    def session_started(self, player: str, round_id: int, session_id: str, mock: bool = False,
                        name_entry: bool = False) -> None:
        with self._cond:
            self.player = player
            self.name_entry = bool(name_entry)
            self.named_player = None
            self.selected_round = round_id
            self.session_id = session_id
            self.mock = bool(mock)
            self.armed = False
            self.stage = None
            self.active_round_id = round_id
            self.live_claim = None
            self.dial_value = None             # a new round type: wait for the sketch to re-send it
            self._set_phase("idle")
            self._changed()

    @_crash_safe
    def serial_opened(self) -> None:
        """The Pi (re)opened the serial port: whatever the board said before may be stale."""
        with self._cond:
            self._board_reset_locked("connecting")
            self._changed()

    def _board_reset_locked(self, stage: str) -> None:
        # The sketch that answers next may be an older one without a live dial: show "?"
        # until it sends a value, never the previous board's last position.
        self.armed = False
        self.stage = stage
        self.dial_value = None
        if self.phase != "reveal":
            self._set_phase("idle")

    @_crash_safe
    def on_status(self, status: dict) -> None:
        """Feed every {"type":"status",...} line from the Arduino."""
        state = status.get("state")
        with self._cond:
            if state == "mode":
                rid = status.get("round_id")
                self.armed = rid == self.selected_round or self.selected_round is None
                self.dial_value = None         # the sketch re-sends it right after the ack (if it can)
                if self.phase in ("idle", "predicting"):
                    self.active_round_id = self.selected_round
                    self.live_claim = None
                    self._set_phase("predicting")
            elif state == "ready":
                if "accel" in status:          # boot banner: the board reset, selection is re-sent
                    self._board_reset_locked("booting")
                    self._changed()
                    return
                self.armed = True
                if self.phase in ("idle", "performing"):
                    # performing -> ready without a result: the round was dropped (sensor error, ...)
                    self.active_round_id = self.selected_round
                    self.live_claim = None
                    self._set_phase("predicting")
            elif state in _PERFORMING_STATES:
                self.armed = True
                if self.phase != "performing":
                    self.active_round_id = self.selected_round
                    # Newer sketches put the locked claim on "locked"; else the last dial position.
                    claim = _int(status.get("claim")) if state == "locked" else None
                    self.live_claim = claim if claim is not None else self.dial_value
                    self.notice = None
                    self._set_phase("performing")
            elif state == "error":
                self._notice(f"Arduino error: {status.get('error')}", "warn")
            else:
                return
            self.stage = state
            self._changed()

    @_crash_safe
    def dial(self, value) -> None:
        """The knob moved ({"type":"dial","value":N}, sent only while a claim is being set).

        Shown as liveClaim on the "predicting" screen. Turning the knob also wakes the idle
        screen, and ends the reveal once it has been up for reveal_min_s: someone is setting
        the next claim. (The sketch re-sends an unchanged value after each round; that
        doesn't count as turning.)

        A turn that only moves the number doesn't bump `version`: the event stream sends
        it as a small `event: dial` instead of the whole state (see next_event()).
        """
        v = _int(value)
        if v is None:
            return
        v = max(0, min(100, v))
        with self._cond:
            if v == self.dial_value:
                return
            self.dial_value = v
            self._activity_at = self._clock()
            before = self._effective_screen()
            screen = before
            structural = False
            if (screen == "reveal" and self.armed
                    and self._clock() - self.phase_since >= self.reveal_min_s):
                screen = "predicting"
            if self.armed and screen in ("idle", "predicting"):
                if self.phase != "predicting":
                    self.active_round_id = self.selected_round
                    self.live_claim = None
                    structural = True
                self._set_phase("predicting")      # also restarts the idle timeout
            if structural or self._effective_screen() != before:
                self._changed()                    # a new screen: full state
            else:
                self._cond.notify_all()            # just the number: event stream sends `dial`

    @_crash_safe
    def claim_locked(self, round_id: int, claim: float) -> None:
        """A claim is known before the result (Round 5: the Arduino sends it, the Pi measures)."""
        with self._cond:
            self._activity_at = self._clock()
            self.armed = True
            self.active_round_id = round_id
            self.live_claim = _int(claim)
            self.stage = "measuring"
            self.notice = None
            self._set_phase("performing")
            self._changed()

    @_crash_safe
    def round_result(self, result, player: str, session_id: str, round_number: int, log=None) -> None:
        """A round was scored and logged: show the reveal and refresh history/leaderboard."""
        with self._cond:
            if log is not None:
                self._refresh_locked(log)
            db_id = None
            for row in reversed(self.history):
                if (row.get("session_id") == session_id and row.get("player") == player
                        and row.get("round_number") == round_number):
                    db_id = row.get("db_id")
                    break
            ui_result = result_from_round(result, player, session_id, round_number, db_id=db_id)
            self.latest_result = ui_result
            if db_id is None:          # not in the log (SQLite trouble): still show it this session
                self.history = (self.history + [ui_result])[-self.history_limit:]
            self.active_round_id = result.round_id
            self.live_claim = _int(result.claim)
            self.stage = "result"
            self._activity_at = self._clock()
            self.notice = None
            self._set_phase("reveal")
            self._changed()

    @_crash_safe
    def set_player(self, raw) -> Optional[str]:
        """The booth screen's name entry. Returns the name as it will be logged, or None."""
        name = clean_player_name(raw)
        if name is None:
            return None
        with self._cond:
            self.named_player = name
            self._activity_at = self._clock()
            # Typed on the attract screen: someone is here, go to the dial (like turning the knob).
            if self.armed and self._effective_screen() == "idle":
                self.active_round_id = self.selected_round
                self.live_claim = None
                self._set_phase("predicting")
            self._changed()
        return name

    def player_named(self) -> bool:
        """A name was typed for this player (and hasn't expired with the idle timeout)."""
        with self._cond:
            return bool(self.named_player) and not self._name_expired_locked()

    def round_player(self) -> str:
        """The name to log the round that is starting under (called when the claim locks)."""
        with self._cond:
            return self._current_player_locked()

    def _name_expired_locked(self) -> bool:
        # Nobody has touched the rig for the idle timeout and the attract screen is up:
        # the next person to walk up is someone else.
        return (self._effective_screen() == "idle"
                and self._clock() - self._activity_at >= self.idle_after_s)

    def _current_player_locked(self) -> str:
        if self.named_player and not self._name_expired_locked():
            return self.named_player
        return self.player or config.UI_DEFAULT_PLAYER

    @_crash_safe
    def verdict_text(self, text: str) -> None:
        """The narrator's line, only after ElevenLabs has returned the audio."""
        with self._cond:
            if self.latest_result is None:
                return
            key = self.latest_result["round_id"]
            self._verdicts[key] = str(text)
            self.latest_result = dict(self.latest_result, verdict_text=str(text),
                                      verdict_status="ready")
            self.history = [dict(r, verdict_text=str(text), verdict_status="ready")
                            if r.get("round_id") == key else r
                            for r in self.history]
            self._changed()

    @_crash_safe
    def verdict_unavailable(self) -> None:
        """ElevenLabs did not return audio. The screen says so. No substitute line."""
        with self._cond:
            if self.latest_result is None:
                return
            key = self.latest_result["round_id"]
            self.latest_result = dict(self.latest_result, verdict_text="",
                                      verdict_status="unavailable")
            self.history = [dict(r, verdict_text="", verdict_status="unavailable")
                            if r.get("round_id") == key else r
                            for r in self.history]
            self._changed()

    @_crash_safe
    def question_text(self, text: str) -> None:
        """The live interview question, shown while ElevenLabs speaks it."""
        with self._cond:
            self._notice(str(text), "info")
            self._changed()

    @_crash_safe
    def question_unavailable(self) -> None:
        """The question call failed. No stand-in audio is played."""
        with self._cond:
            self._notice("question unavailable", "error")
            self._changed()

    @_crash_safe
    def round_rejected(self, message: str) -> None:
        """A round that wasn't scored (sensor error, sensor resting, camera trouble)."""
        with self._cond:
            self._notice(message, "error")
            self.live_claim = None
            self.active_round_id = self.selected_round
            self._set_phase("predicting" if self.armed else "idle")
            self._changed()

    @_crash_safe
    def refresh_from_log(self, log) -> None:
        with self._cond:
            self._refresh_locked(log)
            self._changed()

    def _notice(self, message: str, level: str) -> None:
        self.notice = {"message": str(message), "level": level,
                       "at": datetime.now(timezone.utc).isoformat()}

    def _refresh_locked(self, log) -> None:
        try:
            rows = log.rounds()
            self.leaderboard = [{k: (_num(v) if isinstance(v, float) else v) for k, v in r.items()}
                                for r in log.leaderboard()]
            shame = log.most_delulu()
        except Exception as exc:  # noqa: BLE001 - sqlite3.Error and friends: keep the old history
            self._report_error("reading the session log", exc)
            return
        rows = rows[-self.history_limit:] if self.history_limit else rows
        history = []
        for row in rows:
            item = result_from_row(row)
            item["verdict_text"] = self._verdicts.get(item["round_id"])
            history.append(item)
        self.history = history
        self.most_delulu = result_from_row(shame) if shame else None

    @_crash_safe
    def attach_camera(self, feed) -> None:
        """Round 5 live camera: serve `feed` at /api/camera.mjpg and put its numbers in the state."""
        with self._cond:
            self.camera_feed = feed
            feed.set_notify(self.poke)
            self._changed()

    @_crash_safe
    def poke(self, full: bool = False) -> None:
        """The camera feed changed. full: its mode (-> new snapshot); else only the live numbers,
        which go out as a small SSE "live" event instead of the whole state."""
        with self._cond:
            if full:
                self._changed()
            else:
                self.live_version += 1
                self._cond.notify_all()

    def _camera_state(self, live: bool = False) -> dict:
        feed = self.camera_feed
        if feed is None:
            return {"available": False}
        try:
            return feed.public_state() if live else feed.summary()
        except Exception as exc:  # noqa: BLE001
            self._report_error("camera state", exc)
            return {"available": False}

    def _camera_live(self) -> dict:
        """The camera's fast numbers ({mode, face, smiling, smilePct, ...}); {} without a feed."""
        feed = self.camera_feed
        if feed is None:
            return {}
        try:
            return feed.live_state()
        except Exception as exc:  # noqa: BLE001
            self._report_error("camera live state", exc)
            return {}

    def live_json(self) -> Optional[str]:
        """Payload of the SSE `live` event: {"camera": {...}}; None without a feed."""
        if self.camera_feed is None:
            return None
        return json.dumps({"camera": self._camera_live()}, allow_nan=False)

    # ---------------------------------------------------------------- reads
    def snapshot(self, live: bool = False) -> dict:
        """The state. live=True also puts the camera's fast numbers in (GET /api/state)."""
        with self._cond:
            return self._snapshot_locked(live=live)

    def _live_claim_for(self, screen: str):
        if screen == "predicting":
            return self.dial_value
        return self.live_claim if screen in ("performing", "reveal") else None

    def _snapshot_locked(self, screen: Optional[str] = None, live: bool = False) -> dict:
        if screen is None:
            screen = self._effective_screen()
        show_round = screen in ("predicting", "performing")
        return {
            "screen": screen,
            "player": self._current_player_locked(),
            "nameEntry": self.name_entry,
            "playerNamed": bool(self.named_player) and not self._name_expired_locked(),
            "activeRound": active_round(self.active_round_id) if show_round else None,
            "liveClaim": self._live_claim_for(screen),
            "latestResult": self.latest_result,
            "history": self.history,
            "leaderboard": self.leaderboard,
            "mostDelulu": self.most_delulu,
            "selectedRound": active_round(self.selected_round),
            "board": {"armed": self.armed, "stage": self.stage},
            "notice": self.notice,
            "camera": self._camera_state(live),
            "session": self.session_id,
            "source": "mock" if self.mock else "live",
            "version": self.version,
        }

    def snapshot_json(self, live: bool = False) -> str:
        return json.dumps(self.snapshot(live), default=str, allow_nan=False)

    def next_event(self, cursor, timeout: float,
                   stop: Optional[threading.Event] = None):
        """Block until there is something new for one event-stream client.

        cursor is what this client was last sent (None at first). Returns
        (kind, data_json, new_cursor), or None on timeout / stop:
          kind "state": the full snapshot (any real change: version bump or a new screen,
                        including the time-based ones like the reveal hold ending)
          kind "dial":  only liveClaim moved (the knob): {"liveClaim": N}, a few bytes
                        instead of re-sending history and leaderboard 10 times a second
          kind "live":  only the camera's fast numbers moved (poke()): {"camera": {...}}
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._cond:
                screen = self._effective_screen()
                key = (self.version, screen)
                claim = self._live_claim_for(screen)
                live_v = self.live_version
                if cursor is None or cursor[0] != key:
                    snap = self._snapshot_locked(screen)
                    kind = "state"
                elif claim != cursor[1]:
                    snap = {"liveClaim": claim}
                    kind = "dial"
                elif live_v != cursor[2]:
                    snap = {"camera": self._camera_live()}
                    kind = "live"
                else:
                    snap = None
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or (stop is not None and stop.is_set()):
                        return None
                    self._cond.wait(min(_SSE_POLL_S, remaining))
            if snap is not None:
                # history/leaderboard lists are replaced, never mutated, so this is safe unlocked
                return kind, json.dumps(snap, default=str, allow_nan=False), (key, claim, live_v)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
_NO_DIST_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>The Tell</title></head>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:2em">
<h1>The Tell UI server is running</h1>
<p>No built frontend found at <code>frontend/dist</code>. Build it once with
<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, or run the dev server
(<code>npm run dev</code>) and open the URL it prints.</p>
<p>Live state: <a href="/api/state" style="color:#6cf">/api/state</a></p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeluluUI/1"
    protocol_version = "HTTP/1.1"

    # set on the server object by UIServer
    @property
    def state(self) -> GameState:
        return self.server.game_state  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # keep the game terminal clean
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError):
            pass  # a browser dropped a kept-alive connection: normal, no traceback in the game terminal

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cache-Control, Last-Event-ID")

    def _send(self, code: int, body: bytes, content_type: str, head_only: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802 - http.server naming
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):  # noqa: N802
        self._route(head_only=True)

    def do_GET(self):  # noqa: N802
        self._route()

    def do_POST(self):  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path != "/api/player":
                self._send(404, b'{"error": "not found"}', "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 < length <= _MAX_POST_BYTES:
                self._send(400, b'{"error": "send {\\"name\\": \\"...\\"}"}', "application/json")
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                body = None
            name = self.state.set_player(body.get("name")) if isinstance(body, dict) else None
            if name is None:
                self._send(400, b'{"error": "empty or invalid name"}', "application/json")
                return
            self._send(200, json.dumps({"ok": True, "player": name}).encode(), "application/json")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _route(self, head_only: bool = False) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/api/state":
                self._send(200, self.state.snapshot_json(live=True).encode(), "application/json", head_only)
            elif path == "/api/health":
                self._send(200, b'{"ok": true}', "application/json", head_only)
            elif path == "/api/events":
                if head_only:
                    self._send(200, b"", "text/event-stream", True)
                else:
                    self._events()
            elif path == "/api/camera.mjpg":
                self._camera(head_only)
            elif path.startswith("/api/"):
                self._send(404, b'{"error": "not found"}', "application/json", head_only)
            else:
                self._static(path, head_only)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        self.close_connection = True
        stop: threading.Event = self.server.stopping  # type: ignore[attr-defined]
        cursor = None
        self.wfile.write(b"retry: 1500\n\n")
        while not stop.is_set():
            event = self.state.next_event(cursor, SSE_KEEPALIVE_S, stop)
            if event is None:
                if stop.is_set():
                    break
                self.wfile.write(b": keepalive\n\n")
            else:
                kind, data, cursor = event
                # Full state as a plain message (onmessage); knob turns as `event: dial`.
                prefix = b"event: " + kind.encode() + b"\n" if kind in ("dial", "live") else b""
                self.wfile.write(prefix + b"data: " + data.encode() + b"\n\n")
            self.wfile.flush()

    def _camera(self, head_only: bool) -> None:
        """MJPEG (multipart/x-mixed-replace) of the Round 5 camera, about UI_CAMERA_FPS per browser.

        Only reads the feed's latest-frame slot; the camera itself belongs to the
        round. Any error here ends this HTTP response only, never the round.
        """
        feed = self.state.camera_feed
        if feed is None:
            self._send(503, b'{"error": "no camera feed: only Round 5 with the real webcam '
                            b'(--round 5 --ui, not --mock) has one"}', "application/json", head_only)
            return
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        self.close_connection = True
        if head_only:
            return
        stop: threading.Event = self.server.stopping  # type: ignore[attr-defined]
        period = 1.0 / max(1.0, feed.fps)
        feed.add_viewer()
        try:
            last_seq, last_sent, last_placeholder = 0, float("-inf"), float("-inf")
            first = True
            while not stop.is_set() and not self._client_gone():
                wait = period - (time.monotonic() - last_sent)
                if wait > 0 and stop.wait(wait):
                    break
                item = feed.wait_jpeg(last_seq, 0.3 if first else _MJPEG_IDLE_S)
                first = False
                now = time.monotonic()
                if item is not None:
                    last_seq, jpeg = item
                    last_placeholder = float("-inf")
                elif now - last_placeholder >= _MJPEG_PLACEHOLDER_EVERY_S:
                    jpeg = feed.placeholder()
                    last_placeholder = now
                    if jpeg is None:
                        continue
                else:
                    continue
                self.wfile.write(f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                                 f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                last_sent = now
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass                                       # the browser left
        except Exception as exc:  # noqa: BLE001 - encoding trouble ends this stream only
            self.state._report_error("camera stream", exc)
        finally:
            feed.remove_viewer()

    def _client_gone(self) -> bool:
        """True once the browser closed the connection (EOF), so a viewer isn't counted for long."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _static(self, path: str, head_only: bool) -> None:
        root: Optional[Path] = self.server.static_dir  # type: ignore[attr-defined]
        if root is None or not (root / "index.html").is_file():
            self._send(200, _NO_DIST_PAGE.encode(), "text/html; charset=utf-8", head_only)
            return
        rel = unquote(path).lstrip("/")
        target = (root / rel).resolve() if rel else root / "index.html"
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self._send(404, b"not found", "text/plain", head_only)
            return
        if not target.is_file():
            if "." in Path(rel).name:           # a missing asset, not an app route
                self._send(404, b"not found", "text/plain", head_only)
                return
            target = root / "index.html"        # single-page app fallback
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype, head_only)


class UIServer:
    """Runs the HTTP server in a daemon thread. start() never raises."""

    def __init__(self, state: GameState, host: Optional[str] = None, port: Optional[int] = None,
                 static_dir: Optional[Path] = None):
        self.state = state
        self.host = config.UI_HOST if host is None else host
        self.port = config.UI_PORT if port is None else port
        self.static_dir = Path(config.UI_STATIC_DIR if static_dir is None else static_dir)
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        host = "localhost" if self.host in ("127.0.0.1", "0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}"

    def start(self) -> bool:
        try:
            httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        except OSError as exc:
            print(f"   [ui] could not start the UI server on {self.host}:{self.port}: {exc}. "
                  "The game runs without it (try --ui-port).", file=sys.stderr)
            return False
        httpd.daemon_threads = True
        httpd.game_state = self.state                  # type: ignore[attr-defined]
        httpd.static_dir = self.static_dir.resolve()   # type: ignore[attr-defined]
        httpd.stopping = threading.Event()             # type: ignore[attr-defined]
        self.httpd = httpd
        self.port = httpd.server_address[1]
        self.thread = threading.Thread(target=httpd.serve_forever, name="delulu-ui", daemon=True)
        self.thread.start()
        return True

    @property
    def serving_frontend(self) -> bool:
        return (self.static_dir / "index.html").is_file()

    def stop(self) -> None:
        if self.httpd is None:
            return
        self.httpd.stopping.set()                      # type: ignore[attr-defined]
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
