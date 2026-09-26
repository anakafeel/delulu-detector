"""main loop keeps running when one round blows up."""
import sqlite3

import main
from session_log import SessionLog

MOCK_ARGS = ["--mock", "--rounds", "3", "--seed", "1", "--mock-delay", "0", "--no-audio"]


def test_audio_or_mp3_failure_does_not_stop_the_loop(monkeypatch, tmp_path, capsys):
    calls = []

    def flaky_verdict(result, player, play=True):
        calls.append(result)
        if len(calls) == 1:
            raise OSError("No space left on device: data/tts/verdict.mp3")

    monkeypatch.setattr(main, "deliver_verdict", flaky_verdict)
    db = tmp_path / "s.db"
    assert main.main(MOCK_ARGS + ["--db", str(db)]) == 0
    assert len(calls) == 3
    err = capsys.readouterr().err
    assert "[error] round failed: file or audio error" in err
    with SessionLog(db) as log:
        assert len(log.rounds()) == 3


def test_sqlite_failure_does_not_stop_the_loop(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    real_log_round = SessionLog.log_round
    state = {"n": 0}

    def flaky_log_round(self, *a, **k):
        state["n"] += 1
        if state["n"] == 2:
            raise sqlite3.OperationalError("database is locked")
        return real_log_round(self, *a, **k)

    monkeypatch.setattr(SessionLog, "log_round", flaky_log_round)
    db = tmp_path / "s.db"
    assert main.main(MOCK_ARGS + ["--db", str(db)]) == 0
    err = capsys.readouterr().err
    assert "SQLite" in err and "database is locked" in err
    with SessionLog(db) as log:
        assert len(log.rounds()) == 2


def test_unexpected_error_is_reported_with_traceback(monkeypatch, tmp_path, capsys):
    def broken(*a, **k):
        raise ValueError("bad DELULU_AUDIO_PLAYER quoting")

    monkeypatch.setattr(main, "deliver_verdict", broken)
    with SessionLog(tmp_path / "s.db") as log:
        reading = main.parse_line('{"type":"result","round_id":1,"claim":50,"actual":300}')
        assert main.process_reading(reading, "p", "s", log, play_audio=False) is False
    err = capsys.readouterr().err
    assert "unexpected ValueError" in err and "Traceback" in err
