#!/usr/bin/env python3
"""Copy the scored rounds already in SQLite session logs to Tiger Data (round_events).

    PYTHONPATH=pi python pi/tiger_backfill.py data/sessions.db data/sessions.pre-demo.db

Safe to run again: a row already in Tiger (same session, player, round number, round type and
timestamp) is skipped. Unscored rounds (false starts, timeouts) are skipped like the live mirror.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import tiger_store as t

INSERT_NEW = t.INSERT_SQL.replace(
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
    """SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
       WHERE NOT EXISTS (SELECT 1 FROM round_events
                         WHERE ts = %s AND session_id = %s AND player_id = %s
                           AND round_number = %s AND round_type = %s)""")


def rows_from(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = []
    for r in conn.execute("SELECT * FROM rounds WHERE gap IS NOT NULL ORDER BY id"):
        ts = datetime.fromisoformat(r["ts"])
        composure = r["performance"] if r["unit"] == "composure" else None
        out.append((ts, t.session_uuid(r["session_id"]), r["player"], int(r["round_number"]),
                    int(r["round_id"]), float(r["claim"]), composure, None, None, float(r["gap"])))
    conn.close()
    return out


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__)
        return 2
    conn = t.connect()
    t.ensure_schema(conn)
    total_new = 0
    for p in paths:
        rows = rows_from(Path(p))
        new = 0
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(INSERT_NEW, row + (row[0], row[1], row[2], row[3], row[4]))
                new += cur.rowcount
        print(f"{p}: {len(rows)} scored rounds, {new} copied, {len(rows) - new} already in Tiger")
        total_new += new
    with conn.cursor() as cur:
        cur.execute("CALL refresh_continuous_aggregate('gap_by_round_daily', NULL, NULL)")
        cur.execute("SELECT count(*), count(DISTINCT player_id) FROM round_events")
        n, players = cur.fetchone()
    print(f"Tiger now has {n} rounds from {players} players ({total_new} added).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
