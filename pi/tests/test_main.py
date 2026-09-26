"""main loop keeps running when one round blows up."""
import sqlite3

import config
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


# --------------------------------------------------------------- Round 2
MOCK_R2 = ["--mock", "--legacy-rounds", "--round", "2", "--mock-delay", "0", "--no-audio"]


def _result_lines(rounds, seed, round_id):
    lines = list(main.mock_lines(rounds, seed, 0, round_id))
    return [main.parse_line(ln) for ln in lines if main.parse_line(ln) is not None]


def test_mock_round_2_emits_arduino_format():
    results = _result_lines(40, 7, 2)
    assert len(results) == 40
    assert all(r["round_id"] == 2 and r["unit"] == "mg_rms" for r in results)
    good = [r for r in results if not main.is_sensor_error(r)]
    bad = [r for r in results if main.is_sensor_error(r)]
    assert good and bad                                      # the odd I2C hiccup is simulated
    assert all(r["actual"] > 0 and r["peak"] >= r["actual"] and r["samples"] == 500 for r in good)
    assert all(r["error"] == "accel_read" and r["actual"] is None for r in bad)
    assert not any(r["false_start"] or r["timeout"] for r in results)


def test_mock_round_1_is_unchanged_by_round_2_support():
    results = _result_lines(5, 1, 1)
    assert [r["round_id"] for r in results] == [1] * 5
    assert all(r["unit"] == "ms" and "peak" not in r for r in results)


def test_mock_round_2_end_to_end_logs_mg(monkeypatch, tmp_path):
    verdicts = []
    monkeypatch.setattr(main, "deliver_verdict", lambda r, p, play=True: verdicts.append(r))
    db = tmp_path / "s.db"
    assert main.main(MOCK_R2 + ["--rounds", "12", "--seed", "4", "--db", str(db)]) == 0
    expected = [r for r in _result_lines(12, 4, 2) if not main.is_sensor_error(r)]
    with SessionLog(db) as log:
        rows = log.rounds()
    assert len(rows) == len(verdicts) == len(expected) < 12    # sensor errors are not logged
    for row, reading in zip(rows, expected):
        assert row["round_id"] == 2 and row["unit"] == "mg_rms"
        assert row["actual"] == reading["actual"] and row["actual_ms"] is None
        assert row["gap"] is not None and row["score"] == 100 - round(row["gap"])


def test_sensor_error_result_is_reported_not_logged(monkeypatch, tmp_path, capsys):
    lines = ['{"type":"status","state":"mode","round_id":2,"accel":"none"}',
             '{"type":"result","round_id":2,"seq":1,"claim":72,"actual":null,"unit":"mg_rms",'
             '"peak":null,"samples":0,"false_start":false,"timeout":false,"error":"no_accel"}']
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    db = tmp_path / "s.db"
    assert main.main(MOCK_R2 + ["--db", str(db)]) == 0
    err = capsys.readouterr().err
    assert "no accelerometer detected" in err
    assert "sensor error 'no_accel'" in err and "Not scored or logged" in err
    with SessionLog(db) as log:
        assert log.rounds() == []


def test_mismatched_round_result_is_scored_as_its_own_round(monkeypatch, tmp_path, capsys):
    lines = ['{"type":"result","round_id":1,"seq":1,"claim":50,"actual":300,"unit":"ms",'
             '"false_start":false,"timeout":false}']
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    db = tmp_path / "s.db"
    main.main(MOCK_R2 + ["--db", str(db)])
    assert "Round 1: Reflex result while Round 2 [legacy]: Steady Hands is selected" in capsys.readouterr().out
    with SessionLog(db) as log:
        (row,) = log.rounds()
    assert row["round_id"] == 1 and row["actual_ms"] == 300


def test_calibrate_prints_raw_mg_and_never_scores_or_logs(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise AssertionError("calibrate must not score, narrate or log")

    monkeypatch.setattr(main, "deliver_verdict", boom)
    monkeypatch.setattr(main, "process_reading", boom)
    db = tmp_path / "never.db"
    assert main.main(["--mock", "--calibrate", "--legacy-rounds", "--round", "2", "--rounds", "6", "--seed", "4",
                      "--mock-delay", "0", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    good = [r for r in _result_lines(6, 4, 2) if not main.is_sensor_error(r)]
    for r in good:
        assert f"tremor {r['actual']:.1f} mg RMS" in out
    assert out.count("calib #") == len(good)
    assert "Calibration:" in out and "STEADY_BEST_MG=8" in out
    assert not db.exists()


def test_calibrate_ignores_round_1_results(monkeypatch, capsys):
    lines = ['{"type":"result","round_id":1,"claim":50,"actual":300}']
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    assert main.main(["--mock", "--calibrate", "--legacy-rounds", "--round", "2"]) == 0
    out = capsys.readouterr().out
    assert "ignoring a Round 1 result" in out and "No Round 2 holds recorded" in out


def test_calibrate_rejects_round_1():
    import pytest
    with pytest.raises(SystemExit):
        main.main(["--mock", "--calibrate", "--round", "1"])


def test_round_flag_selects_mock_round(monkeypatch, tmp_path):
    seen = {}

    def fake_mock(rounds, seed, delay, round_id):
        seen["round"] = round_id
        return iter([])

    monkeypatch.setattr(main, "mock_lines", fake_mock)
    main.main(["--mock", "--db", str(tmp_path / "a.db")])
    assert seen["round"] == 1
    main.main(["--mock", "--legacy-rounds", "--round", "2", "--db", str(tmp_path / "a.db")])
    assert seen["round"] == 2


def test_cut_rounds_need_the_legacy_flag(capsys):
    import pytest
    with pytest.raises(SystemExit):
        main.main(["--mock", "--round", "2"])
    assert "--legacy-rounds" in capsys.readouterr().err
    assert config.GAME_ROUNDS == (1, 5, 6) and config.LEGACY_ROUNDS == (2,)
    assert config.ROUND_LABELS == {1: 1, 5: 2, 6: 3}


def test_round_titles_use_the_game_numbering():
    assert main.round_title(1) == "Round 1: Reflex"
    assert main.round_title(5) == "Round 2: Poker Face"
    assert main.round_title(6) == "Round 3: Straight Face"
    assert main.round_title(2) == "Round 2 [legacy]: Steady Hands"


def _r2(seq, actual):
    return ('{"type":"result","round_id":2,"seq":%d,"claim":100,"actual":%s,"unit":"mg_rms",'
            '"peak":40.0,"samples":500,"false_start":false,"timeout":false}' % (seq, actual))


def test_resting_sensor_is_rejected_in_play_not_logged(monkeypatch, tmp_path, capsys):
    import config
    monkeypatch.setattr(config, "STEADY_REST_MG", 30.0)
    monkeypatch.setattr(config, "STEADY_BEST_MG", 35.0)
    monkeypatch.setattr(config, "STEADY_WORST_MG", 500.0)
    lines = [_r2(1, "21.0"), _r2(2, "68.0")]   # table hold, then a real steady hand
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    db = tmp_path / "s.db"
    assert main.main(MOCK_R2 + ["--db", str(db)]) == 0
    err = capsys.readouterr().err
    assert "[rejected] Round 2 tremor 21.0 mg RMS" in err and "Not scored or logged" in err
    with SessionLog(db) as log:
        (row,) = log.rounds()
    assert row["actual"] == 68.0 and row["performance"] < 100


def test_resting_hold_still_shows_in_calibrate(monkeypatch, capsys):
    import config
    monkeypatch.setattr(config, "STEADY_REST_MG", 30.0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    main._run_calibration(iter([_r2(1, "21.0")]), 2)
    out = capsys.readouterr().out
    assert "21.0" in out and "[rejected]" not in out


def test_is_resting_edges(monkeypatch):
    import config
    monkeypatch.setattr(config, "STEADY_REST_MG", 30.0)
    assert main.is_resting({"round_id": 2, "actual": 29.9})
    assert not main.is_resting({"round_id": 2, "actual": 30.0})
    assert not main.is_resting({"round_id": 2, "actual": None, "error": "no_accel"})
    assert not main.is_resting({"round_id": 1, "actual": 5.0})


def test_non_finite_values_are_ignored_not_scored():
    for bad in ("NaN", "Infinity", "-Infinity"):
        assert main.parse_line(_r2(1, bad)) is None
        assert main.parse_line('{"type":"result","round_id":1,"claim":%s,"actual":300}' % bad) is None
    assert main.parse_line(_r2(1, "68.0"))["actual"] == 68.0


def test_shipped_rest_is_below_best():
    import importlib.util
    import pathlib
    import config
    spec = importlib.util.spec_from_file_location("shipped_config2", pathlib.Path(config.__file__))
    shipped = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shipped)
    assert 0 < shipped.STEADY_REST_MG <= shipped.STEADY_BEST_MG < shipped.STEADY_WORST_MG
