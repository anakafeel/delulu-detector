"""Tiger Data (Timescale) copy of every scored round, for the calibration curve and leaderboard.

SQLite (session_log.py) stays the game's own log. This module only mirrors scored rounds to a
Timescale hypertable when TIGER_DATA_URL is set, and reads them back:

    round_events          hypertable on ts, one row per scored round
    gap_by_round_daily    continuous aggregate: per player, round_number and day, the gap sum and
                          count (real-time: rows not yet materialized are included on read)

A round is written by a background thread (TigerWriter.submit never blocks and never raises), so
a slow or unreachable database can't stall or fail a round at the booth. Reads (curve,
leaderboard) have a short timeout and raise TigerError, which the UI server turns into a 503.

Heart rate and HRV are nullable and currently always NULL: the Presage bridge only requests the
face metrics, and HRV needs far more than one 6 s window. Nothing here makes a value up.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import uuid
from typing import Optional

import config

try:  # psycopg 3; only needed when TIGER_DATA_URL is set
    import psycopg
except ImportError:  # pragma: no cover - the game runs without it
    psycopg = None

CONNECT_TIMEOUT_S = 3          # per address; the Tiger host resolves to several
READ_BACKOFF_S = 30.0          # after a failed read, answer 503 at once for this long
STATEMENT_TIMEOUT_MS = 4000

SCHEMA = [
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    """CREATE TABLE IF NOT EXISTS round_events (
        ts               timestamptz      NOT NULL,
        session_id       uuid             NOT NULL,
        player_id        text             NOT NULL,
        round_number     int              NOT NULL,
        round_type       int              NOT NULL,   -- 1 Reflex, 5 Poker Face, 6 Straight Face
        claim            double precision,
        confidence_score double precision,            -- Presage composure (NEUTRAL confidence), 0-100
        heart_rate       double precision,            -- not measured yet: NULL
        hrv              double precision,            -- not measured yet: NULL
        gap_score        double precision NOT NULL    -- |claim - performance|, as the game scores it
    )""",
    "SELECT create_hypertable('round_events', by_range('ts'), if_not_exists => TRUE)",
    "CREATE INDEX IF NOT EXISTS round_events_player_idx ON round_events (player_id, ts DESC)",
    # A continuous aggregate must bucket the time column, so it keeps per-day sums and counts;
    # the curve adds the buckets up, which gives the exact average across all sessions.
    """CREATE MATERIALIZED VIEW IF NOT EXISTS gap_by_round_daily
       WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
       SELECT time_bucket(INTERVAL '1 day', ts) AS day,
              player_id, round_number,
              sum(gap_score) AS gap_sum,
              count(*)       AS n
       FROM round_events
       GROUP BY day, player_id, round_number
       WITH NO DATA""",
    """SELECT add_continuous_aggregate_policy('gap_by_round_daily',
           start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 minute',
           schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE)""",
]

INSERT_SQL = """INSERT INTO round_events (ts, session_id, player_id, round_number, round_type, claim,
                                          confidence_score, heart_rate, hrv, gap_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

CURVE_SQL = """SELECT round_number, sum(gap_sum) / sum(n) AS avg_gap, sum(n)::int AS rounds
               FROM gap_by_round_daily
               WHERE player_id = %s
               GROUP BY round_number
               ORDER BY round_number"""

LEADERBOARD_SQL = """SELECT player_id, avg(gap_score) AS avg_gap, count(*)::int AS rounds,
                            min(gap_score) AS best_gap, max(gap_score) AS worst_gap
                     FROM round_events
                     GROUP BY player_id
                     ORDER BY avg_gap ASC, rounds DESC
                     LIMIT %s"""


class TigerError(Exception):
    pass


def enabled() -> bool:
    return bool(config.TIGER_DATA_URL) and psycopg is not None


def session_uuid(session_id: str) -> uuid.UUID:
    """The game's session ids ("20260926-221120-1a8715") as a stable uuid.

    The "the-tell:" prefix is the project's first name, kept on purpose: changing it would give
    every logged session a new uuid, and re-running tiger_backfill.py would then duplicate rows."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"the-tell:{session_id}")


def connect():
    if not enabled():
        raise TigerError("TIGER_DATA_URL is not set" if psycopg is not None else "psycopg is not installed")
    try:
        return psycopg.connect(config.TIGER_DATA_URL, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True,
                               options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}")
    except psycopg.Error as exc:
        raise TigerError(f"could not connect to Tiger Data: {exc}") from exc


def ensure_schema(conn) -> None:
    """Idempotent: safe on every start."""
    with conn.cursor() as cur:
        for stmt in SCHEMA:
            cur.execute(stmt)


def row_for(result, player: str, session_id: str, round_number: int, ts) -> Optional[tuple]:
    """A scored RoundResult -> the insert parameters; None for rounds without a gap."""
    if result.gap is None:
        return None
    composure = result.performance if result.unit == "composure" else None
    return (ts, session_uuid(session_id), player, int(round_number), int(result.round_id),
            float(result.claim), composure, None, None, float(result.gap))


class TigerWriter:
    """Background writer. submit() never blocks and never raises; failures are reported once."""

    def __init__(self, connect_fn=connect, max_queue: int = 500):
        self._connect = connect_fn
        self._q: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._reported: set[str] = set()
        self.written = 0
        self.schema_ready = threading.Event()

    def start(self) -> "TigerWriter":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="tiger-writer", daemon=True)
            self._thread.start()
        return self

    def submit(self, params: Optional[tuple]) -> None:
        if params is None:
            return
        try:
            self._q.put_nowait(params)
        except queue.Full:
            self._report("queue", "Tiger Data write queue is full; dropping a round (SQLite still has it)")

    def close(self, timeout: float = 3.0) -> None:
        if self._thread is not None:
            self._q.put(None)
            self._thread.join(timeout)
            self._thread = None

    def _report(self, key: str, message: str) -> None:
        if key not in self._reported:
            self._reported.add(key)
            print(f"   [tiger] {message}. The game carries on. (Reported once.)", file=sys.stderr)

    def _run(self) -> None:
        conn = None
        while True:
            params = self._q.get()
            if params is None:
                break
            for attempt in (1, 2):                      # one reconnect per round, then give up on it
                try:
                    if conn is None:
                        conn = self._connect()
                        if not self.schema_ready.is_set():
                            ensure_schema(conn)
                            self.schema_ready.set()
                    with conn.cursor() as cur:
                        cur.execute(INSERT_SQL, params)
                    self.written += 1
                    break
                except Exception as exc:  # noqa: BLE001 - never let the mirror break the game
                    try:
                        if conn is not None:
                            conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = None
                    if attempt == 2:
                        self._report("write", f"could not write a round ({type(exc).__name__}: {exc})")
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


class TigerReader:
    """Curve and leaderboard queries on one reused connection (reconnects once on failure)."""

    def __init__(self, connect_fn=connect, backoff_s: float = READ_BACKOFF_S,
                 clock=time.monotonic):
        self._connect = connect_fn
        self._conn = None
        self._lock = threading.Lock()
        self._backoff_s = backoff_s
        self._clock = clock
        self._down_until = 0.0

    def _query(self, sql: str, params: tuple) -> list[tuple]:
        if self._clock() < self._down_until:           # unreachable a moment ago: don't hang the chart
            raise TigerError("Tiger Data unreachable (retrying shortly)")
        with self._lock:
            last = None
            for _ in (1, 2):
                try:
                    if self._conn is None:
                        self._conn = self._connect()
                    with self._conn.cursor() as cur:
                        cur.execute(sql, params)
                        return cur.fetchall()
                except TigerError:
                    self._down_until = self._clock() + self._backoff_s
                    raise
                except Exception as exc:  # noqa: BLE001 - psycopg errors, dropped connections
                    last = exc
                    try:
                        if self._conn is not None:
                            self._conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._conn = None
            self._down_until = self._clock() + self._backoff_s
            raise TigerError(f"Tiger Data query failed: {type(last).__name__}: {last}")

    def curve(self, player: str) -> list[dict]:
        """round_number -> average gap across all of the player's sessions (from the aggregate)."""
        rows = self._query(CURVE_SQL, (player,))
        return [{"round_number": int(r[0]), "avg_gap": round(float(r[1]), 1), "rounds": int(r[2])}
                for r in rows]

    def leaderboard(self, limit: int = 10) -> list[dict]:
        """Lowest average gap first."""
        rows = self._query(LEADERBOARD_SQL, (int(limit),))
        return [{"player": r[0], "avg_gap": round(float(r[1]), 1), "rounds": int(r[2]),
                 "best_gap": round(float(r[3]), 1), "worst_gap": round(float(r[4]), 1)} for r in rows]
