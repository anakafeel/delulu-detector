from datetime import datetime, timezone

import pytest

from main import parse_line
from scoring import score_reflex_round
from session_log import SessionLog, new_session_id


@pytest.fixture
def log(tmp_path):
    with SessionLog(tmp_path / "sessions.db") as lg:
        yield lg


def test_creates_db_file(tmp_path):
    path = tmp_path / "nested" / "sessions.db"
    SessionLog(path).close()
    assert path.exists()


def test_log_round_writes_row_with_all_fields(log):
    sid = new_session_id()
    ts = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    n = log.log_round(sid, "saim", score_reflex_round(90, 375), ts=ts)
    assert n == 1
    (row,) = log.rounds("saim")
    assert row["ts"] == ts.isoformat()
    assert row["session_id"] == sid
    assert row["round_id"] == 1 and row["round_number"] == 1
    assert row["claim"] == 90 and row["actual_ms"] == 375
    assert row["performance"] == 50.0 and row["gap"] == 40.0 and row["score"] == 60
    assert row["false_start"] == 0 and row["tier"] == "spicy"


def test_round_numbers_are_per_player_per_session(log):
    s1, s2 = "s1", "s2"
    assert log.log_round(s1, "a", score_reflex_round(50, 300)) == 1
    assert log.log_round(s1, "a", score_reflex_round(50, 300)) == 2
    assert log.log_round(s1, "b", score_reflex_round(50, 300)) == 1
    assert log.log_round(s2, "a", score_reflex_round(50, 300)) == 1


def test_false_start_logged(log):
    log.log_round("s", "jumpy", score_reflex_round(80, None, false_start=True))
    (row,) = log.rounds("jumpy")
    assert row["false_start"] == 1 and row["timeout"] == 0 and row["actual_ms"] is None
    assert row["performance"] is None and row["gap"] is None
    assert row["score"] == 0 and row["tier"] == "false_start"


def test_timeout_logged(log):
    log.log_round("s", "sleepy", score_reflex_round(0, None, timeout=True))
    (row,) = log.rounds("sleepy")
    assert row["timeout"] == 1 and row["gap"] is None and row["score"] == 0
    assert row["tier"] == "timeout"


def test_leaderboard_best_worst_total(log):
    log.log_round("s", "alice", score_reflex_round(80, 240))   # gap 0
    log.log_round("s", "alice", score_reflex_round(100, 600))  # gap 100
    log.log_round("s", "bob", score_reflex_round(70, 375))     # gap 20
    board = log.leaderboard()
    assert [r["player"] for r in board] == ["alice", "bob"]
    alice = board[0]
    assert alice["best_gap"] == 0 and alice["worst_gap"] == 100 and alice["total_rounds"] == 2
    assert board[1]["total_rounds"] == 1
    assert log.most_delulu()["player"] == "alice"


def test_failed_rounds_count_but_do_not_rank(log):
    log.log_round("s", "carol", score_reflex_round(80, None, false_start=True))
    (row,) = log.leaderboard()
    assert row["total_rounds"] == 1
    assert row["best_gap"] is None and row["worst_gap"] is None
    assert row["avg_score"] == 0
    assert log.calibration_series("carol") == []
    assert log.calibration_series("carol", "s") == []
    assert log.most_delulu() is None


def test_claim_zero_timeout_and_false_start_excluded_from_leaderboard(log):
    # The exploit: claim 0 and never press (or jump the gun) used to be gap 0.
    log.log_round("s", "gamer", score_reflex_round(0, None, timeout=True))
    log.log_round("s", "gamer", score_reflex_round(0, None, false_start=True))
    log.log_round("s", "gamer", score_reflex_round(60, 375))        # perf 50, gap 10, score 90
    log.log_round("s", "honest", score_reflex_round(75, 240))       # perf 80, gap 5, score 95
    log.log_round("s", "only_fails", score_reflex_round(0, None, timeout=True))

    board = log.leaderboard()
    assert [r["player"] for r in board] == ["honest", "gamer", "only_fails"]
    gamer = board[1]
    assert gamer["best_gap"] == 10.0 and gamer["worst_gap"] == 10.0
    assert gamer["total_rounds"] == 3
    assert gamer["avg_score"] == 30.0                                # (0 + 0 + 90) / 3
    only_fails = board[2]
    assert only_fails["best_gap"] is None and only_fails["total_rounds"] == 1
    assert log.most_delulu()["player"] == "gamer"                    # only real gaps count
    assert log.calibration_series("gamer", "s") == [(3, 10.0)]
    assert log.calibration_series("gamer") == [(1, 10.0)]


def test_legacy_rows_with_a_gap_on_failed_rounds_are_still_excluded(log):
    # Rows written before this fix stored performance 0 and a gap for failed rounds.
    log.conn.execute(
        """INSERT INTO rounds (ts, session_id, player, round_id, round_number, claim, actual_ms,
                               false_start, timeout, performance, gap, score, tier)
           VALUES ('2026-09-25T12:00:00+00:00', 'old', 'legacy', 1, 1, 0, NULL, 0, 1,
                   0.0, 0.0, 100, 'timeout')"""
    )
    log.conn.commit()
    log.log_round("new", "legacy", score_reflex_round(70, 375))      # gap 20, score 80
    (row,) = log.leaderboard()
    assert row["best_gap"] == 20.0 and row["worst_gap"] == 20.0
    assert row["total_rounds"] == 2 and row["avg_score"] == 40.0      # legacy row counts as 0
    assert log.calibration_series("legacy") == [(1, 20.0)]


def test_calibration_series(log):
    for claim in (95, 85, 75):                     # perf is 80 each time (240 ms)
        log.log_round("s1", "dana", score_reflex_round(claim, 240))
    log.log_round("s2", "dana", score_reflex_round(80, 240))
    log.log_round("s1", "other", score_reflex_round(0, 240))
    assert log.calibration_series("dana", "s1") == [(1, 15.0), (2, 5.0), (3, 5.0)]
    assert log.calibration_series("dana") == [(1, 15.0), (2, 5.0), (3, 5.0), (4, 0.0)]


@pytest.mark.parametrize("line,ok", [
    ('{"type":"result","round_id":1,"seq":1,"claim":72,"actual":243,"unit":"ms","false_start":false,"timeout":false}', True),
    ('{"type":"result","round_id":1,"seq":2,"claim":72,"actual":null,"unit":"ms","false_start":true,"timeout":false}', True),
    ('{"claim":50,"actual":300,"round_id":1}', True),          # bare PRD shape
    ('{"type":"status","state":"ready"}', False),
    ('garbage \x00 from boot', False),
    ('{"type":"result","round_id":1,"claim":', False),          # half line
])
def test_parse_line(line, ok):
    assert (parse_line(line) is not None) == ok


# ------------------------------------------------------- Round 2 + schema v2
import json
import sqlite3

import session_log
from scoring import score_steady_round

# The exact table the Round-1-only version created (schema v1, user_version 0).
LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    session_id   TEXT    NOT NULL,
    player       TEXT    NOT NULL,
    round_id     INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    claim        INTEGER NOT NULL,
    actual_ms    REAL,
    false_start  INTEGER NOT NULL DEFAULT 0,
    timeout      INTEGER NOT NULL DEFAULT 0,
    performance  REAL,
    gap          REAL,
    score        INTEGER,
    tier         TEXT
);
CREATE INDEX IF NOT EXISTS idx_rounds_player ON rounds(player);
CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
"""

LEGACY_ROWS = [
    ("2026-09-25T20:00:00+00:00", "old", "saim", 1, 1, 90, 375.0, 0, 0, 50.0, 40.0, 60, "spicy"),
    ("2026-09-25T20:01:00+00:00", "old", "saim", 1, 2, 80, None, 1, 0, None, None, 0, "false_start"),
    ("2026-09-25T20:02:00+00:00", "old", "bob", 1, 1, 75, 240.0, 0, 0, 80.0, 5.0, 95, "validated"),
]


def _make_legacy_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany(
        """INSERT INTO rounds (ts, session_id, player, round_id, round_number, claim, actual_ms,
                               false_start, timeout, performance, gap, score, tier)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", LEGACY_ROWS)
    conn.commit()
    conn.close()


def _cols(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(rounds)")]
    finally:
        conn.close()


def test_new_db_has_schema_v2(tmp_path):
    path = tmp_path / "sessions.db"
    with SessionLog(path) as lg:
        assert lg.migration_backup is None
        assert lg.conn.execute("PRAGMA user_version").fetchone()[0] == session_log.SCHEMA_VERSION == 2
    assert {"actual", "unit", "extra", "actual_ms"} <= set(_cols(path))
    assert not lg.backup_path().exists()


def test_legacy_db_is_migrated_without_losing_anything(tmp_path):
    path = tmp_path / "sessions.db"
    _make_legacy_db(path)
    old_cols = _cols(path)

    with SessionLog(path) as lg:
        rows = lg.rounds()
        assert lg.migration_backup == tmp_path / "sessions.pre-v2-backup.db"
    # every old column and value is untouched, in the same order
    assert _cols(path)[:len(old_cols)] == old_cols
    assert len(rows) == 3
    for row, legacy in zip(rows, LEGACY_ROWS):
        assert tuple(row[c] for c in old_cols[1:]) == legacy
    # old Round 1 rows are backfilled into the generic columns
    assert [(r["actual"], r["unit"], r["extra"]) for r in rows] == [
        (375.0, "ms", None), (None, "ms", None), (240.0, "ms", None)]

    # the backup is a faithful copy of the pre-migration file
    backup = sqlite3.connect(str(tmp_path / "sessions.pre-v2-backup.db"))
    assert backup.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 3
    assert "actual" not in [r[1] for r in backup.execute("PRAGMA table_info(rounds)")]
    backup.close()


def test_migration_is_idempotent_and_backs_up_only_once(tmp_path):
    path = tmp_path / "sessions.db"
    _make_legacy_db(path)
    SessionLog(path).close()
    before = sorted(p.name for p in tmp_path.iterdir())
    with SessionLog(path) as lg:
        assert lg.migration_backup is None
        assert len(lg.rounds()) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_existing_backup_is_never_overwritten(tmp_path):
    path = tmp_path / "sessions.db"
    _make_legacy_db(path)
    earlier = tmp_path / "sessions.pre-v2-backup.db"
    earlier.write_bytes(b"an earlier backup")
    with SessionLog(path) as lg:
        assert lg.migration_backup != earlier and lg.migration_backup.exists()
    assert earlier.read_bytes() == b"an earlier backup"


def test_empty_legacy_db_migrates_without_backup(tmp_path):
    path = tmp_path / "sessions.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_SCHEMA)
    conn.close()
    with SessionLog(path) as lg:
        assert lg.migration_backup is None
    assert "unit" in _cols(path)


def test_failed_migration_rolls_back_and_keeps_data(tmp_path, monkeypatch):
    path = tmp_path / "sessions.db"
    _make_legacy_db(path)
    monkeypatch.setattr(session_log, "_V2_COLUMNS",
                        (("actual", "REAL"), ("unit", "TEXT"), ("bad col", "NOPE(")))
    with pytest.raises(sqlite3.OperationalError):
        SessionLog(path)
    assert "actual" not in _cols(path)             # all-or-nothing
    conn = sqlite3.connect(str(path))
    assert conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 3
    conn.close()


def test_migrated_legacy_data_keeps_working_with_new_rounds(tmp_path):
    path = tmp_path / "sessions.db"
    _make_legacy_db(path)
    with SessionLog(path) as lg:
        lg.log_round("new", "saim", score_steady_round(80, 22.4, peak_mg=70.0, samples=500))  # gap 0
        board = {r["player"]: r for r in lg.leaderboard()}
        assert board["saim"]["best_gap"] == 0.0 and board["saim"]["worst_gap"] == 40.0
        assert board["saim"]["total_rounds"] == 3
        assert board["saim"]["avg_score"] == round((60 + 0 + 100) / 3, 1)
        assert lg.calibration_series("saim") == [(1, 40.0), (2, 0.0)]


def test_round_2_row_fields(log):
    ts = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    n = log.log_round("s", "steady", score_steady_round(90, 44.0, peak_mg=150.5, samples=498), ts=ts)
    assert n == 1
    (row,) = log.rounds("steady")
    assert row["round_id"] == 2 and row["unit"] == "mg_rms"
    assert row["actual"] == 44.0 and row["actual_ms"] is None
    assert json.loads(row["extra"]) == {"peak": 150.5, "samples": 498}
    assert row["performance"] == 50.0 and row["gap"] == 40.0 and row["score"] == 60
    assert row["tier"] == "spicy" and row["false_start"] == 0 and row["timeout"] == 0


def test_round_1_rows_fill_both_actual_columns(log):
    log.log_round("s", "fast", score_reflex_round(90, 375))
    (row,) = log.rounds("fast")
    assert row["actual_ms"] == 375 and row["actual"] == 375 and row["unit"] == "ms"
    assert row["extra"] is None


def test_leaderboard_and_failed_rules_across_rounds(log):
    log.log_round("s", "mix", score_reflex_round(0, None, timeout=True))          # fail: 0, no gap
    log.log_round("s", "mix", score_steady_round(60, 44.0))                       # gap 10, score 90
    log.log_round("s", "mix", score_reflex_round(80, 600))                        # gap 80, score 20
    log.log_round("s", "calm", score_steady_round(75, 22.4))                      # gap 5, score 95
    board = log.leaderboard()
    assert [r["player"] for r in board] == ["calm", "mix"]
    mix = board[1]
    assert mix["best_gap"] == 10.0 and mix["worst_gap"] == 80.0
    assert mix["total_rounds"] == 3 and mix["avg_score"] == round((0 + 90 + 20) / 3, 1)
    assert log.most_delulu()["round_id"] == 1
    # round numbers run across round types; the curve mixes rounds unless filtered
    assert log.calibration_series("mix", "s") == [(2, 10.0), (3, 80.0)]
    assert log.calibration_series("mix", "s", round_id=2) == [(2, 10.0)]
    assert log.calibration_series("mix", round_id=1) == [(1, 80.0)]


@pytest.mark.parametrize("line,ok", [
    ('{"type":"result","round_id":2,"seq":1,"claim":72,"actual":14.3,"unit":"mg_rms","peak":61.2,"samples":500,"false_start":false,"timeout":false}', True),
    ('{"type":"result","round_id":2,"seq":2,"claim":72,"actual":null,"unit":"mg_rms","peak":null,"samples":0,"false_start":false,"timeout":false,"error":"no_accel"}', True),
    ('{"type":"status","state":"mode","round_id":2,"accel":"LIS3DH@0x19"}', False),
])
def test_parse_line_round_2(line, ok):
    assert (parse_line(line) is not None) == ok


def test_rows_written_by_an_older_checkout_after_upgrade_are_backfilled(tmp_path):
    path = tmp_path / "sessions.db"
    SessionLog(path).close()                                   # already v2
    conn = sqlite3.connect(str(path))                          # old-style INSERT (no new columns)
    conn.execute(
        """INSERT INTO rounds (ts, session_id, player, round_id, round_number, claim, actual_ms,
                               false_start, timeout, performance, gap, score, tier)
           VALUES ('2026-09-26T12:00:00+00:00', 'x', 'old_code', 1, 1, 50, 300.0, 0, 0,
                   66.7, 16.7, 83, 'mild')""")
    conn.commit()
    conn.close()
    with SessionLog(path) as lg:
        (row,) = lg.rounds("old_code")
    assert row["actual"] == 300.0 and row["unit"] == "ms"
