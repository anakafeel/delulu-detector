"""SQLite session log + leaderboard (data/sessions.db by default).

One row per round:
    ts, session_id, player, round_id (round type, 1 = Reflex, 2 = Steady Hands),
    round_number (1, 2, 3... per player per session, across round types), claim,
    actual (raw metric), unit ("ms" or "mg_rms"), actual_ms (Round 1 only, kept
    for older readers), extra (JSON, e.g. Round 2 peak and sample count),
    false_start, timeout, performance, gap, score, tier

Gaps are normalized 0-100 for every round type, so the leaderboard, "most
delulu" and the calibration series mix rounds on purpose.

False starts and timeouts score 0 and have no performance or gap. They count
toward rounds played and the average score, but never toward best gap, worst
gap, "most delulu" or the calibration series. The read queries also filter on
the false_start / timeout flags, so rows written by older versions (which
stored a gap for these rounds) are excluded the same way.

Schema versions (PRAGMA user_version):
    0/1  original Round-1-only table (actual_ms only)
    2    adds actual, unit, extra. Migrated in place on open with ADD COLUMN
         only (nothing is dropped or rewritten), old Round 1 rows get
         actual = actual_ms and unit = 'ms', and a one-off copy of the old file
         is saved next to it first (sessions.pre-v2-backup.db).
"""
from __future__ import annotations

import json
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
    round_id     INTEGER NOT NULL,          -- round type (1 = Reflex, 2 = Steady Hands)
    round_number INTEGER NOT NULL,          -- nth round for this player in this session
    claim        INTEGER NOT NULL,          -- 0-100 from the dial
    actual_ms    REAL,                      -- Round 1 reaction ms (NULL on false start / timeout, and for other rounds)
    false_start  INTEGER NOT NULL DEFAULT 0,
    timeout      INTEGER NOT NULL DEFAULT 0,
    performance  REAL,                      -- 0-100 normalized reality (NULL on false start / timeout)
    gap          REAL,                      -- |claim - performance| (NULL on false start / timeout)
    score        INTEGER,                   -- 100 - gap (0 on false start / timeout)
    tier         TEXT,
    actual       REAL,                      -- raw metric in `unit` (NULL if nothing was measured)
    unit         TEXT,                      -- 'ms' (Round 1) or 'mg_rms' (Round 2)
    extra        TEXT                       -- JSON with round-specific raw extras, or NULL
);
CREATE INDEX IF NOT EXISTS idx_rounds_player ON rounds(player);
CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
"""

SCHEMA_VERSION = 2
# Columns added in schema v2, in order (ALTER TABLE ... ADD COLUMN, never drops anything).
_V2_COLUMNS = (("actual", "REAL"), ("unit", "TEXT"), ("extra", "TEXT"))
# Old Round 1 rows whose raw value still only lives in actual_ms.
_NEEDS_BACKFILL = "round_id = 1 AND actual IS NULL AND unit IS NULL"

# SQL condition for rounds that have a real, comparable gap.
_GAP_COUNTS = "(false_start = 0 AND timeout = 0 AND gap IS NOT NULL)"


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


class SessionLog:
    def __init__(self, db_path: Path | str = config.DB_PATH):
        self.db_path = Path(db_path)
        self.migration_backup: Optional[Path] = None   # set if this open migrated an old file
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()

    # ------------------------------------------------------------- migration
    def _columns(self) -> set[str]:
        return {r["name"] for r in self.conn.execute("PRAGMA table_info(rounds)")}

    def _needs_backfill(self) -> bool:
        """Round 1 rows without actual/unit (e.g. written by an older checkout after the upgrade)."""
        return bool(self.conn.execute(f"SELECT EXISTS(SELECT 1 FROM rounds WHERE {_NEEDS_BACKFILL})").fetchone()[0])

    def _user_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def backup_path(self) -> Path:
        """Where the one-off pre-migration copy goes (matches the data/*.db gitignore)."""
        return self.db_path.with_name(f"{self.db_path.stem}.pre-v2-backup{self.db_path.suffix or '.db'}")

    def _backup_before_migration(self) -> Optional[Path]:
        if str(self.db_path) == ":memory:":
            return None
        dest = self.backup_path()
        if dest.exists():                          # never overwrite an earlier backup
            dest = dest.with_name(f"{dest.stem}-{datetime.now():%Y%m%d-%H%M%S}{dest.suffix}")
        target = sqlite3.connect(str(dest))
        try:
            self.conn.backup(target)
        finally:
            target.close()
        return dest

    def _migrate(self) -> None:
        """Bring an older sessions.db up to SCHEMA_VERSION without losing anything.

        Additive only: ADD COLUMN for the new columns, then copy actual_ms into
        actual (unit 'ms') for old Round 1 rows (also rows an older checkout
        writes after the upgrade; its INSERT still works since the new
        columns are nullable). Runs in one IMMEDIATE
        transaction (another process opening the same file waits, then sees the
        columns already there). Safe to run on every open.
        """
        missing = [c for c in _V2_COLUMNS if c[0] not in self._columns()]
        if not missing and self._user_version() >= SCHEMA_VERSION and not self._needs_backfill():
            return
        if missing:
            has_rows = self.conn.execute("SELECT EXISTS(SELECT 1 FROM rounds)").fetchone()[0]
            if has_rows:
                self.migration_backup = self._backup_before_migration()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            present = self._columns()               # re-check under the write lock
            for name, sql_type in _V2_COLUMNS:
                if name not in present:
                    self.conn.execute(f"ALTER TABLE rounds ADD COLUMN {name} {sql_type}")
            self.conn.execute(f"UPDATE rounds SET actual = actual_ms, unit = 'ms' WHERE {_NEEDS_BACKFILL}")
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

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
                                   actual_ms, false_start, timeout, performance, gap, score, tier,
                                   actual, unit, extra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts.isoformat(), session_id, player, result.round_id, round_number, result.claim,
             result.actual_ms, int(result.false_start), int(result.timeout),
             result.performance, result.gap, result.score, result.tier,
             result.actual, result.unit, json.dumps(result.extra) if result.extra else None),
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

    def calibration_series(self, player: str, session_id: Optional[str] = None,
                           round_id: Optional[int] = None) -> list[tuple[int, float]]:
        """[(round_number, gap), ...] for one player, in play order, for a calibration curve.

        False starts and timeouts are skipped (they have no gap). Round types
        are mixed unless round_id is given (gaps are all 0-100). If session_id
        is None, rounds from all sessions are concatenated and renumbered 1..N
        in play order.
        """
        where = f"player=? AND {_GAP_COUNTS}"
        params: list = [player]
        if round_id is not None:
            where += " AND round_id=?"
            params.append(round_id)
        if session_id is not None:
            cur = self.conn.execute(
                f"SELECT round_number, gap FROM rounds WHERE {where} AND session_id=? ORDER BY id",
                (*params, session_id),
            )
            return [(int(r["round_number"]), float(r["gap"])) for r in cur.fetchall()]
        cur = self.conn.execute(f"SELECT gap FROM rounds WHERE {where} ORDER BY id", params)
        return [(i, float(r["gap"])) for i, r in enumerate(cur.fetchall(), start=1)]
