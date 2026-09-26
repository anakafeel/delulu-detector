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
