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
    plus extras (leaderboard, mostDelulu, board, notice, version).

UIServer
    ThreadingHTTPServer in a daemon thread:
        GET /api/state    current state as JSON
        GET /api/events   Server-Sent Events: the state again on every change
        GET /api/health   {"ok": true}
        GET /...          frontend/dist (the `npm run build` output) if present,
                          so no Node is needed at the venue
    CORS is open (read-only, local data) so a Vite dev server on another port works.

Stdlib only. Nothing here touches the serial port, SQLite writes or audio.
"""
from __future__ import annotations

import functools
import json
import math
import mimetypes
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
ROUND_KEYS = {1: "reflex", 2: "steady_hands", 3: "retreat", 5: "poker_face"}
ROUND_DISPLAY_NAMES = {1: "Reflex", 2: "Steady Hands", 3: "Retreat", 5: "Poker Face"}

SCREENS = ("idle", "predicting", "performing", "reveal")

# Arduino status states that mean "a round is running, claim locked" (and what's happening).
_PERFORMING_STATES = {"locked", "cue", "countdown", "hold", "false_start", "window"}

SSE_KEEPALIVE_S = 15.0
_SSE_POLL_S = 0.5          # also catches time-based changes (reveal hold ending)


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
    return {"round_id": round_key(round_id), "round_type_id": round_id, "round_name": round_name(round_id)}


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
        "round_number": row.get("round_number"),
        "session_id": row.get("session_id"),
        "player": row.get("player"),
        "claim": _int(row.get("claim")),
        "actual": _num(row.get("performance")),       # 0-100 normalized reality
        "actual_raw": _num(raw, 1),                    # raw measurement in `actual_unit`
        "actual_unit": unit,                           # "ms" | "mg_rms" | "smile_pct"
        "gap": gap,
        "score": row.get("score"),
        "tier": row.get("tier"),
        "direction": _direction(row.get("claim"), row.get("performance")),
        "false_start": bool(row.get("false_start")),
        "timeout": bool(row.get("timeout")),
        "scored": gap is not None,
        "extra": _safe_extra(extra),
        "verdict_text": verdict_text,
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
        self.player: Optional[str] = None
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
    def session_started(self, player: str, round_id: int, session_id: str, mock: bool = False) -> None:
        with self._cond:
            self.player = player
            self.selected_round = round_id
            self.session_id = session_id
            self.mock = bool(mock)
            self.armed = False
            self.stage = None
            self.active_round_id = round_id
            self.live_claim = None
            self._set_phase("idle")
            self._changed()

    @_crash_safe
    def on_status(self, status: dict) -> None:
        """Feed every {"type":"status",...} line from the Arduino."""
        state = status.get("state")
        with self._cond:
            if state == "mode":
                rid = status.get("round_id")
                self.armed = rid == self.selected_round or self.selected_round is None
                if self.phase in ("idle", "predicting"):
                    self.active_round_id = self.selected_round
                    self.live_claim = None
                    self._set_phase("predicting")
            elif state == "ready":
                if "accel" in status:          # boot banner: the board reset, selection is re-sent
                    self.armed = False
                    self.stage = "booting"
                    if self.phase != "reveal":
                        self._set_phase("idle")
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
        """
        v = _int(value)
        if v is None:
            return
        v = max(0, min(100, v))
        with self._cond:
            if v == self.dial_value:
                return
            self.dial_value = v
            screen = self._effective_screen()
            if (screen == "reveal" and self.armed
                    and self._clock() - self.phase_since >= self.reveal_min_s):
                screen = "predicting"
            if self.armed and screen in ("idle", "predicting"):
                if self.phase != "predicting":
                    self.active_round_id = self.selected_round
                    self.live_claim = None
                self._set_phase("predicting")      # also restarts the idle timeout
            self._changed()

    @_crash_safe
    def claim_locked(self, round_id: int, claim: float) -> None:
        """A claim is known before the result (Round 5: the Arduino sends it, the Pi measures)."""
        with self._cond:
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
            self.notice = None
            self._set_phase("reveal")
            self._changed()

    @_crash_safe
    def verdict_text(self, text: str) -> None:
        """The narrator's line for the latest result (called before the audio plays)."""
        with self._cond:
            if self.latest_result is None:
                return
            key = self.latest_result["round_id"]
            self._verdicts[key] = str(text)
            self.latest_result = dict(self.latest_result, verdict_text=str(text))
            self.history = [dict(r, verdict_text=str(text)) if r.get("round_id") == key else r
                            for r in self.history]
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

    # ---------------------------------------------------------------- reads
    def snapshot(self) -> dict:
        with self._cond:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict:
        screen = self._effective_screen()
        show_round = screen in ("predicting", "performing")
        return {
            "screen": screen,
            "player": self.player,
            "activeRound": active_round(self.active_round_id) if show_round else None,
            "liveClaim": (self.dial_value if screen == "predicting"
                          else self.live_claim if screen in ("performing", "reveal") else None),
            "latestResult": self.latest_result,
            "history": self.history,
            "leaderboard": self.leaderboard,
            "mostDelulu": self.most_delulu,
            "selectedRound": active_round(self.selected_round),
            "board": {"armed": self.armed, "stage": self.stage},
            "notice": self.notice,
            "session": self.session_id,
            "source": "mock" if self.mock else "live",
            "version": self.version,
        }

    def snapshot_json(self) -> str:
        return json.dumps(self.snapshot(), default=str, allow_nan=False)

    def wait_for_change(self, last_json: Optional[str], timeout: float,
                        stop: Optional[threading.Event] = None) -> Optional[str]:
        """Block until the state JSON differs from last_json (or timeout / stop); return it or None."""
        deadline = time.monotonic() + timeout
        while True:
            current = self.snapshot_json()
            if current != last_json:
                return current
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (stop is not None and stop.is_set()):
                return None
            with self._cond:
                self._cond.wait(min(_SSE_POLL_S, remaining))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
_NO_DIST_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Delulu Detector</title></head>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:2em">
<h1>Delulu Detector UI server is running</h1>
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

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
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

    def _route(self, head_only: bool = False) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/api/state":
                self._send(200, self.state.snapshot_json().encode(), "application/json", head_only)
            elif path == "/api/health":
                self._send(200, b'{"ok": true}', "application/json", head_only)
            elif path == "/api/events":
                if head_only:
                    self._send(200, b"", "text/event-stream", True)
                else:
                    self._events()
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
        last = None
        self.wfile.write(b"retry: 1500\n\n")
        while not stop.is_set():
            current = self.state.wait_for_change(last, SSE_KEEPALIVE_S, stop)
            if current is None:
                if stop.is_set():
                    break
                self.wfile.write(b": keepalive\n\n")
            else:
                last = current
                self.wfile.write(b"data: " + current.encode() + b"\n\n")
            self.wfile.flush()

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
