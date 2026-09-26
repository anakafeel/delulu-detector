"""SQLite session log + leaderboard (data/sessions.db by default).

One row per round:
    ts, session_id, player, round_id (round type, 1 = Reflex), round_number
    (1, 2, 3... per player per session), claim, actual_ms, false_start,
    timeout, performance, gap, score, tier

False starts and timeouts score 0 and have no performance or gap. They count
toward rounds played and the average score, but never toward best gap, worst
gap, "most delulu" or the calibration series. The read queries also filter on
the false_start / timeout flags, so rows written by older versions (which
stored a gap for these rounds) are excluded the same way.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config
from scoring import RoundResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,          -- ISO-8601 UTC
    session_id   TEXT    NOT NULL,
    player       TEXT    NOT NULL,
    round_id     INTEGER NOT NULL,          -- round type (1 = Reflex)
    round_number INTEGER NOT NULL,          -- nth round for this player in this session
    claim        INTEGER NOT NULL,          -- 0-100 from the dial
    actual_ms    REAL,                      -- raw sensor value (NULL on false start / timeout)
    false_start  INTEGER NOT NULL DEFAULT 0,
    timeout      INTEGER NOT NULL DEFAULT 0,
    performance  REAL,                      -- 0-100 normalized reality (NULL on false start / timeout)
    gap          REAL,                      -- |claim - performance| (NULL on false start / timeout)
    score        INTEGER,                   -- 100 - gap (0 on false start / timeout)
    tier         TEXT
);
CREATE INDEX IF NOT EXISTS idx_rounds_player ON rounds(player);
CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
"""

# SQL condition for rounds that have a real, comparable gap.
_GAP_COUNTS = "(false_start = 0 AND timeout = 0 AND gap IS NOT NULL)"


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


class SessionLog:
    def __init__(self, db_path: Path | str = config.DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------------------------------------------------------- writes
    def next_round_number(self, session_id: str, player: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(round_number), 0) FROM rounds WHERE session_id=? AND player=?",
            (session_id, player),
        ).fetchone()
        return int(row[0]) + 1

    def log_round(self, session_id: str, player: str, result: RoundResult,
                  ts: Optional[datetime] = None) -> int:
        """Append a row; returns the round_number assigned."""
        ts = ts or datetime.now(timezone.utc)
        round_number = self.next_round_number(session_id, player)
        self.conn.execute(
            """INSERT INTO rounds (ts, session_id, player, round_id, round_number, claim,
                                   actual_ms, false_start, timeout, performance, gap, score, tier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts.isoformat(), session_id, player, result.round_id, round_number, result.claim,
             result.actual_ms, int(result.false_start), int(result.timeout),
             result.performance, result.gap, result.score, result.tier),
        )
        self.conn.commit()
        return round_number

    # ----------------------------------------------------------------- reads
    def rounds(self, player: Optional[str] = None) -> list[dict]:
        if player is None:
            cur = self.conn.execute("SELECT * FROM rounds ORDER BY id")
        else:
            cur = self.conn.execute("SELECT * FROM rounds WHERE player=? ORDER BY id", (player,))
        return [dict(r) for r in cur.fetchall()]

    def leaderboard(self) -> list[dict]:
        """Per player: best (smallest) gap, worst ('most delulu') gap, total rounds, avg score.

        Sorted by best gap ascending. False starts and timeouts count toward
        total_rounds and toward avg_score (as config.FAILED_ROUND_SCORE), but
        not toward best/worst gap. A player with only false starts / timeouts
        has best_gap and worst_gap None and sorts last.
        """
        cur = self.conn.execute(
            f"""SELECT player,
                      MIN(CASE WHEN {_GAP_COUNTS} THEN gap END) AS best_gap,
                      MAX(CASE WHEN {_GAP_COUNTS} THEN gap END) AS worst_gap,
                      COUNT(*)  AS total_rounds,
                      ROUND(AVG(CASE WHEN false_start = 0 AND timeout = 0 THEN score
                                     ELSE ? END), 1) AS avg_score
               FROM rounds
               GROUP BY player
               ORDER BY best_gap IS NULL, best_gap ASC, total_rounds DESC""",
            (config.FAILED_ROUND_SCORE,),
        )
        return [dict(r) for r in cur.fetchall()]

    def most_delulu(self) -> Optional[dict]:
        """The single worst-gap round across everyone (the hall of shame)."""
        row = self.conn.execute(
            f"SELECT * FROM rounds WHERE {_GAP_COUNTS} ORDER BY gap DESC, id ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def calibration_series(self, player: str, session_id: Optional[str] = None) -> list[tuple[int, float]]:
        """[(round_number, gap), ...] for one player, in play order, for a calibration curve.

        False starts and timeouts are skipped (they have no gap). If session_id
        is None, rounds from all sessions are concatenated and renumbered 1..N
        in play order.
        """
        if session_id is not None:
            cur = self.conn.execute(
                f"""SELECT round_number, gap FROM rounds
                   WHERE player=? AND session_id=? AND {_GAP_COUNTS} ORDER BY id""",
                (player, session_id),
            )
            return [(int(r["round_number"]), float(r["gap"])) for r in cur.fetchall()]
        cur = self.conn.execute(
            f"SELECT gap FROM rounds WHERE player=? AND {_GAP_COUNTS} ORDER BY id", (player,)
        )
        return [(i, float(r["gap"])) for i, r in enumerate(cur.fetchall(), start=1)]
