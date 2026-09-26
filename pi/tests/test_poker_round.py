"""Round 5 (Poker Face): smile_frac -> performance, scoring, the claim line, the
fake camera + detector driving whole rounds (smoothing, no_face), --mock and
--calibrate for Round 5, the joke stimulus, lazy OpenCV import, privacy, and
that Rounds 1 and 2 are unchanged. No OpenCV, no camera, no network."""
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import config
import elevenlabs_client as ec
import main
import poker_round
import vision
from poker_round import PokerRound, parse_claim, reading_from_stats
from scoring import (ROUND_POKER, score_poker_round, score_reading, score_steady_round,
                     smile_frac_to_performance)
from session_log import SessionLog
from vision import FakeCamera, FakeDetector, SmileSmoother, measure_window

PI_DIR = Path(main.__file__).resolve().parent
CLAIM_LINE = '{"type":"claim","round_id":5,"seq":6,"claim":72}'
F, S, N = (True, False), (True, True), (False, False)     # face / face+smile / no face


# ------------------------------------------------------------------ mapping
@pytest.mark.parametrize("frac,expected", [
    (0.0, 100.0),    # never smiled
    (0.05, 100.0),   # best bound (conftest pins 0.05 / 0.45)
    (0.25, 50.0),    # midpoint
    (0.13, 80.0),
    (0.45, 0.0),     # worst bound
    (1.0, 0.0),      # smiled the whole time clamps to 0
])
def test_smile_mapping_bounds_and_linearity(frac, expected):
    assert smile_frac_to_performance(frac) == pytest.approx(expected)


def test_smile_mapping_follows_config_and_rejects_bad_bounds(monkeypatch):
    assert (config.POKER_BEST_FRAC, config.POKER_WORST_FRAC) == (0.05, 0.45)
    monkeypatch.setattr(config, "POKER_BEST_FRAC", 0.0)
    monkeypatch.setattr(config, "POKER_WORST_FRAC", 0.5)
    assert smile_frac_to_performance(0.25) == pytest.approx(50.0)
    with pytest.raises(ValueError):
        smile_frac_to_performance(0.2, best_frac=0.4, worst_frac=0.1)


def test_shipped_poker_defaults():
    import importlib.util
    spec = importlib.util.spec_from_file_location("shipped_config", Path(config.__file__))
    shipped = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shipped)
    assert (shipped.POKER_BEST_FRAC, shipped.POKER_WORST_FRAC) == (0.03, 0.40)
    assert shipped.POKER_WINDOW_S == 6.0 and shipped.POKER_MIN_FACE_FRAC == 0.5
    assert shipped.POKER_CAMERA_INDEX == 0 or "DELULU_CAMERA_INDEX" in __import__("os").environ
    assert (shipped.SMILE_SCALE_FACTOR, shipped.SMILE_MIN_NEIGHBORS) == (1.7, 20)
    assert (shipped.SMILE_SMOOTH_FRAMES, shipped.SMILE_SMOOTH_HITS) == (3, 2)
    # Round 2 calibration is untouched
    assert (shipped.STEADY_REST_MG, shipped.STEADY_BEST_MG, shipped.STEADY_WORST_MG) == (30.0, 35.0, 500.0)
    assert shipped.ROUND_NAMES == {1: "Reflex", 2: "Steady Hands", 5: "Poker Face", 6: "Straight Face"}


# ------------------------------------------------------------------ scoring
def test_poker_round_overconfident():
    r = score_poker_round(claim=90, smile_frac=0.25, face_frac=0.97, frames=88, fps=14.66,
                          first_smile_ms=2310)
    assert r.round_id == ROUND_POKER and r.unit == "smile_pct"
    assert r.actual == 25.0 and r.actual_ms is None
    assert r.performance == 50.0 and r.gap == 40.0 and r.score == 60
    assert r.tier == "spicy" and r.direction == "over"
    assert r.extra == {"smile_frac": 0.25, "face_frac": 0.97, "frames": 88, "fps": 14.7,
                       "first_smile_ms": 2310}
    assert r.scored and not r.failed


def test_poker_round_stone_face_and_sandbagger():
    r = score_poker_round(claim=100, smile_frac=0.0)
    assert r.performance == 100.0 and r.gap == 0.0 and r.score == 100 and r.tier == "validated"
    assert r.extra["first_smile_ms"] is None
    r = score_poker_round(claim=20, smile_frac=0.01)               # stayed stony, claimed 20
    assert r.gap == 80.0 and r.tier == "delulu" and r.direction == "under"


def test_poker_round_same_scoring_rules_as_other_rounds():
    r2 = score_steady_round(claim=30, tremor_mg=44.0)              # perf 50
    r5 = score_poker_round(claim=30, smile_frac=0.25)              # perf 50
    assert (r2.gap, r2.score, r2.tier, r2.direction) == (r5.gap, r5.score, r5.tier, r5.direction)


def test_poker_round_without_a_value_is_not_scored():
    with pytest.raises(ValueError):
        score_poker_round(claim=50, smile_frac=None)


def test_score_reading_dispatches_round_5():
    reading = {"round_id": 5, "claim": 72.0, "actual": 13.0, "smile_frac": 0.13, "face_frac": 1.0,
               "frames": 90, "fps": 15.0, "first_smile_ms": 1200}
    r = score_reading(reading)
    assert r.round_id == 5 and r.performance == 80.0 and r.extra["frames"] == 90
    r = score_reading({"round_id": 5, "claim": 72.0, "actual": 13.0})    # smile_frac from actual
    assert r.performance == 80.0


# ------------------------------------------------------------------ claim line
def test_parse_claim_line():
    msg = parse_claim(CLAIM_LINE + "\r\n")
    assert msg == {"type": "claim", "round_id": 5, "seq": 6, "claim": 72.0}


@pytest.mark.parametrize("line", [
    '{"type":"result","round_id":1,"claim":50,"actual":300}',
    '{"type":"status","state":"mode","round_id":5,"accel":"none"}',
    '{"type":"claim","round_id":5,"seq":6,"claim":',
    '{"type":"claim","round_id":5}',
    '{"type":"claim","round_id":"x","claim":5}',
    "boot noise", "", "[1,2]",
])
def test_parse_claim_rejects_everything_else(line):
    assert parse_claim(line) is None


def test_claim_line_is_not_a_result_or_status():
    assert main.parse_line(CLAIM_LINE) is None and main.parse_status(CLAIM_LINE) is None


# ------------------------------------------------------------------ smoothing
def test_smoother_needs_2_of_the_last_3():
    sm = SmileSmoother(3, 2)
    raw = [True, False, False, True, True, False, False, True, False, True]
    assert [sm.update(x) for x in raw] == [False, False, False, False, True, True, False, False,
                                           False, True]


def test_smoother_single_frame_blips_never_count():
    sm = SmileSmoother()
    assert not any(sm.update(i % 3 == 0) for i in range(30))       # 1 in 3 -> never 2 of 3


def test_smoother_rejects_bad_settings():
    with pytest.raises(ValueError):
        SmileSmoother(3, 4)


# ------------------------------------------------------------------ window measurement
def _measure(frames, window_s=1.0, fps=10):
    cam = FakeCamera([frames], fps=fps)
    cam.begin_window()
    return measure_window(cam, FakeDetector(), window_s, clock=cam.now)


def test_window_counts_frames_faces_and_smoothed_smiles():
    # 10 frames at 10 fps: 2 without a face, a lone blip at frame 3, a real smile at frames 6-8
    frames = [F, F, S, F, N, F, S, S, S, N]
    st = _measure(frames)
    assert st.frames == 10 and st.face_frames == 8
    assert st.raw_smile_frames == 4
    assert st.smile_frames == 2                  # frames 7 and 8 (2 of 3); the blip and frame 6 don't
    assert st.smile_frac == pytest.approx(2 / 8) and st.face_frac == pytest.approx(0.8)
    assert st.first_smile_ms == 800              # 8th frame, read at t = 0.8 s
    assert st.fps == pytest.approx(10.0) and st.elapsed_s == pytest.approx(1.0)


def test_window_stone_face_has_no_first_smile():
    st = _measure([F] * 10)
    assert st.smile_frac == 0.0 and st.first_smile_ms is None and st.face_frac == 1.0


def test_window_length_follows_window_s():
    st = _measure([F] * 200, window_s=6.0, fps=15)
    assert st.frames == 90 and st.fps == pytest.approx(15.0)


def test_window_gives_up_on_a_dead_camera():
    st = _measure([F, F] + [None] * 100, window_s=60.0)
    assert st.frames == 2 and st.read_failures == 25


def test_reading_from_stats_scored_and_errors():
    claim = {"claim": 72, "seq": 6}
    ok = reading_from_stats(claim, _measure([F, S, S, S, F, F, F, F, F, F]))
    assert ok["round_id"] == 5 and ok["unit"] == "smile_pct" and "error" not in ok
    # raw smiles in frames 2-4 -> smoothed smiles in frames 3-5 (majority vote lags by one frame)
    assert ok["smile_frac"] == 0.3 and ok["actual"] == 30.0 and ok["frames"] == 10
    assert ok["first_smile_ms"] == 300 and not main.is_sensor_error(ok)
    no_face = reading_from_stats(claim, _measure([F, F, F, F, N, N, N, N, N, N]))   # face 40%
    assert no_face["error"] == "no_face" and no_face["actual"] is None and no_face["face_frac"] == 0.4
    assert main.is_sensor_error(no_face)
    half = reading_from_stats(claim, _measure([F] * 5 + [N] * 5))                    # exactly 50% is fine
    assert "error" not in half
    dead = reading_from_stats(claim, _measure([]))
    assert dead["error"] == "camera_read" and main.is_sensor_error(dead)


# ------------------------------------------------------------------ PokerRound + jokes
class _Audio:
    def __init__(self):
        self.started, self.stopped = [], []

    def start(self, path):
        self.started.append(path)
        return f"proc:{path.name}"

    def stop(self, proc):
        self.stopped.append(proc)


def _poker(windows, tmp_path, jokes=(), play_jokes=True, window_s=1.0):
    jokes_dir = tmp_path / "jokes"
    jokes_dir.mkdir(exist_ok=True)
    for name in jokes:
        (jokes_dir / name).write_bytes(b"ID3")
    cam = FakeCamera(windows, fps=10)
    audio = _Audio()
    pr = PokerRound(cam, FakeDetector(), window_s, clock=cam.now, play_jokes=play_jokes,
                    jokes_dir=jokes_dir, start_audio_fn=audio.start, stop_audio_fn=audio.stop)
    return pr, audio


def test_full_round_plays_a_joke_and_stops_it_after_the_window(tmp_path):
    pr, audio = _poker([[F, F, S, S, S, S, F, F, F, F]], tmp_path, jokes=["joke_01.mp3"])
    reading = pr.run({"claim": 90, "seq": 1})
    assert [p.name for p in audio.started] == ["joke_01.mp3"]
    assert audio.stopped == ["proc:joke_01.mp3"]
    assert reading["smile_frac"] == 0.4 and reading["first_smile_ms"] == 400   # 4-frame burst -> 4 frames
    r = score_reading(reading)
    assert r.performance == pytest.approx(12.5) and r.tier == "delulu" and r.direction == "over"


def test_no_joke_files_is_silently_skipped(tmp_path):
    pr, audio = _poker([[F] * 10], tmp_path)
    assert pr.run({"claim": 50})["smile_frac"] == 0.0
    assert audio.started == [] and audio.stopped == [None]


def test_jokes_off_with_no_audio(tmp_path):
    pr, audio = _poker([[F] * 10], tmp_path, jokes=["joke_01.mp3"], play_jokes=False)
    pr.run({"claim": 50})
    assert audio.started == []


def test_jokes_do_not_repeat_back_to_back(tmp_path):
    pr, audio = _poker([[F] * 10] * 12, tmp_path, jokes=["joke_01.mp3", "joke_02.mp3", "joke_03.mp3"])
    for _ in range(12):
        pr.run({"claim": 50})
    names = [p.name for p in audio.started]
    assert all(a != b for a, b in zip(names, names[1:])) and len(set(names)) > 1


def test_joke_is_stopped_even_if_the_window_blows_up(tmp_path):
    pr, audio = _poker([[F] * 10], tmp_path, jokes=["joke_01.mp3"])

    class Boom(FakeDetector):
        def detect(self, frame):
            raise RuntimeError("cv2 exploded")

    pr.detector = Boom()
    with pytest.raises(RuntimeError):
        pr.run({"claim": 50})
    assert audio.stopped == ["proc:joke_01.mp3"]


def test_start_audio_is_non_blocking_and_stop_terminates(monkeypatch, tmp_path):
    monkeypatch.setattr(ec, "find_player_cmd", lambda: [sys.executable, "-c",
                                                        "import time, sys; time.sleep(30)"])
    proc = poker_round.start_audio(tmp_path / "joke.mp3")
    assert proc is not None and proc.poll() is None                 # still playing: we didn't wait
    poker_round.stop_audio(proc)
    assert proc.poll() is not None
    monkeypatch.setattr(ec, "find_player_cmd", lambda: None)
    assert poker_round.start_audio(tmp_path / "joke.mp3") is None   # no player: just skip


# ------------------------------------------------------------------ main: --mock / errors / calibrate
MOCK_R5 = ["--mock", "--round", "5", "--mock-delay", "0", "--no-audio"]


def test_mock_round_5_emits_claim_lines():
    lines = list(main.mock_lines(6, 3, 0, 5))
    assert json.loads(lines[0]) == {"type": "status", "state": "mode", "round_id": 5, "accel": "none"}
    claims = [parse_claim(ln) for ln in lines if parse_claim(ln)]
    assert [c["seq"] for c in claims] == [1, 2, 3, 4, 5, 6]
    assert all(c["round_id"] == 5 and 0 <= c["claim"] <= 100 for c in claims)
    assert not any(main.parse_line(ln) for ln in lines)             # the sketch sends no results


def test_mock_round_5_end_to_end_logs_smile_pct(monkeypatch, tmp_path, capsys):
    verdicts = []
    monkeypatch.setattr(main, "deliver_verdict", lambda r, p, play=True: verdicts.append(r))
    db = tmp_path / "s.db"
    assert main.main(MOCK_R5 + ["--rounds", "20", "--seed", "4", "--db", str(db)]) == 0
    out, err = capsys.readouterr()
    assert "mock camera + fake detector" in out and "Round 2: Poker Face" in out
    with SessionLog(db) as log:
        rows = log.rounds()
    errors = err.count("sensor error 'no_face'")
    assert errors >= 1 and len(rows) == len(verdicts) == 20 - errors      # no_face is not logged
    for row in rows:
        extra = json.loads(row["extra"])
        assert row["round_id"] == 5 and row["unit"] == "smile_pct" and row["actual_ms"] is None
        assert set(extra) == {"smile_frac", "face_frac", "frames", "fps", "first_smile_ms"}
        assert row["actual"] == pytest.approx(extra["smile_frac"] * 100, abs=0.01)
        assert extra["face_frac"] >= 0.5 and extra["frames"] == 90
        assert row["performance"] == pytest.approx(smile_frac_to_performance(extra["smile_frac"]), abs=0.05)
        assert row["score"] == 100 - round(row["gap"])
    assert "FACE THE CAMERA" in err and "Not scored or logged" in err


def _scripted_main(monkeypatch, windows, claims):
    lines = [json.dumps({"type": "status", "state": "mode", "round_id": 5, "accel": "none"})]
    lines += [json.dumps({"type": "claim", "round_id": 5, "seq": i, "claim": c})
              for i, c in enumerate(claims, start=1)]
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    cam = FakeCamera(windows, fps=15)
    fake = PokerRound(cam, FakeDetector(), 6.0, clock=cam.now, play_jokes=False)
    monkeypatch.setattr(poker_round, "build", lambda **kw: fake)
    return cam


def test_no_face_is_reported_not_scored_logged_or_spoken(monkeypatch, tmp_path, capsys):
    spoken = []
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: spoken.append(a))
    cam = _scripted_main(monkeypatch, [[N] * 60 + [F] * 30, [F] * 88 + [S] * 2], [80, 90])
    db = tmp_path / "s.db"
    assert main.main(MOCK_R5 + ["--db", str(db)]) == 0
    out, err = capsys.readouterr()
    assert "sensor error 'no_face' (face in 33% of 90 frames)" in err and "FACE THE CAMERA" in err
    with SessionLog(db) as log:
        (row,) = log.rounds()                                     # only the second window
    assert len(spoken) == 1 and row["claim"] == 90
    assert json.loads(row["extra"])["smile_frac"] == pytest.approx(1 / 90, abs=1e-4)
    assert not cam.opened                                          # camera released at the end


def test_round_5_claim_is_ignored_when_round_5_is_not_selected(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter([CLAIM_LINE]))
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: pytest.fail("nothing to narrate"))
    assert main.main(["--mock", "--round", "1", "--no-audio", "--db", str(tmp_path / "s.db")]) == 0
    assert "ignoring a Round 2: Poker Face claim" in capsys.readouterr().out


def test_vision_crash_is_reported_and_the_loop_survives(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    cam = _scripted_main(monkeypatch, [[F] * 90, [F] * 90], [50, 60])
    calls = {"n": 0}
    real = vision.measure_window

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("camera unplugged mid-window")
        return real(*a, **k)

    monkeypatch.setattr(vision, "measure_window", flaky)
    db = tmp_path / "s.db"
    assert main.main(MOCK_R5 + ["--db", str(db)]) == 0
    assert "camera / vision error" in capsys.readouterr().err
    with SessionLog(db) as log:
        assert [r["claim"] for r in log.rounds()] == [60]
    assert not cam.opened


def test_calibrate_round_5_prints_raw_numbers_and_never_scores_or_logs(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise AssertionError("calibrate must not score, narrate or log")

    monkeypatch.setattr(main, "deliver_verdict", boom)
    monkeypatch.setattr(main, "process_reading", boom)
    _scripted_main(monkeypatch, [[F] * 90, [F] * 60 + [S] * 30, [N] * 90, [F] * 80 + [S] * 10],
                   [10, 20, 30, 40])
    db = tmp_path / "never.db"
    assert main.main(["--mock", "--calibrate", "--round", "5", "--db", str(db)]) == 0
    out, err = capsys.readouterr()
    assert "CALIBRATION (Round 2: Poker Face: raw smile_frac" in out
    assert "calib #1: smile_frac 0.000 | face_frac 1.00 | fps 15.0 (90 frames) | first_smile_ms none" in out
    assert "calib #2: smile_frac 0.322" in out and "first_smile_ms 4133 ms" in out   # 62nd frame
    assert "calib #3: smile_frac - | face_frac 0.00" in out and "[no_face: would not be scored" in out
    assert "so far: smile_frac min 0.000 | median 0.100 | max 0.322 over 3 window(s)" in out
    assert "Calibration: 3 window(s)" in out and "POKER_BEST_FRAC=0.05" in out
    assert "face the camera" in err
    assert not db.exists()


def test_mock_calibrate_round_5_runs(capsys):
    assert main.main(MOCK_R5[:3] + ["--calibrate", "--rounds", "4", "--seed", "2", "--mock-delay", "0"]) == 0
    out = capsys.readouterr().out
    assert out.count("calib #") == 4 and "Calibration:" in out


def test_plain_calibrate_is_poker_face_now(monkeypatch):
    seen = {}

    def fake_mock(rounds, seed, delay, round_id):
        seen["round"] = round_id
        return iter([])

    monkeypatch.setattr(main, "mock_lines", fake_mock)
    main.main(["--mock", "--calibrate"])
    assert seen["round"] == 5                        # Steady Hands was cut from the game
    main.main(["--mock", "--calibrate", "--legacy-rounds", "--round", "2"])
    assert seen["round"] == 2
    main.main(["--mock", "--calibrate", "--round", "6"])
    assert seen["round"] == 6


def test_camera_and_preview_flags_reach_the_factory(monkeypatch, tmp_path):
    seen = {}

    def fake_build(**kw):
        seen.update(kw)
        raise vision.VisionUnavailable("no camera in tests")

    monkeypatch.setattr(poker_round, "build", fake_build)
    code = main.main(["--round", "5", "--camera", "2", "--preview", "--port", "/dev/null",
                      "--db", str(tmp_path / "s.db")])
    assert code == 2 and not (tmp_path / "s.db").exists()
    assert seen["camera_index"] == 2 and seen["preview"] is True and seen["mock"] is False
    assert seen["play_jokes"] is True


def test_camera_index_comes_from_config_unless_camera_flag_is_given(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "POKER_CAMERA_INDEX", 2)            # e.g. an external USB webcam
    assert vision.Camera().index == 2 and vision.Camera(0).index == 0
    seen = []

    def fake_build(**kw):
        seen.append(vision.Camera(kw["camera_index"]).index)
        raise vision.VisionUnavailable("no camera in tests")

    monkeypatch.setattr(poker_round, "build", fake_build)
    base = ["--round", "5", "--port", "/dev/null", "--db", str(tmp_path / "s.db")]
    assert main.main(base) == 2 and main.main(base + ["--camera", "0"]) == 2
    assert main.main(base + ["--camera", "3"]) == 2
    assert seen == [2, 0, 3]


def test_window_outside_the_sketch_range_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "POKER_WINDOW_S", 45.0)
    with pytest.raises(SystemExit):
        main.main(["--mock", "--round", "5"])


# ------------------------------------------------------------------ lazy OpenCV
def _run_without_cv2(tmp_path, *args):
    blocker = tmp_path / "block"
    blocker.mkdir(parents=True)
    (blocker / "cv2.py").write_text("raise ImportError('No module named cv2 (blocked by test)')\n")
    import os
    env = {**os.environ, "PYTHONPATH": str(blocker), "ELEVENLABS_API_KEY": ""}
    return subprocess.run([sys.executable, str(PI_DIR / "main.py"), *args], env=env,
                          capture_output=True, text=True, timeout=60)


def test_rounds_1_and_2_and_mock_5_run_without_opencv(tmp_path):
    for extra in (["--round", "1"], ["--legacy-rounds", "--round", "2"], ["--round", "5"], ["--round", "6"]):
        proc = _run_without_cv2(tmp_path / extra[-1], "--mock", *extra, "--rounds", "2", "--seed", "1",
                                "--mock-delay", "0", "--no-audio", "--db", str(tmp_path / "s.db"))
        assert proc.returncode == 0, proc.stderr
        assert "Leaderboard" in proc.stdout


def test_real_round_5_without_opencv_is_a_clear_error(tmp_path):
    proc = _run_without_cv2(tmp_path, "--round", "5", "--port", "/dev/null", "--db", str(tmp_path / "s.db"))
    assert proc.returncode == 2
    assert "needs OpenCV" in proc.stderr and "opencv-python>=4.8,<5" in proc.stderr
    assert "Traceback" not in proc.stderr and not (tmp_path / "s.db").exists()


def test_importing_the_app_does_not_import_cv2():
    code = ("import sys; sys.path.insert(0, %r); import main, vision, poker_round; "
            "print('cv2' in sys.modules)" % str(PI_DIR))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.stdout.strip() == "False", proc.stderr


def test_opencv_5_without_cascadeclassifier_is_a_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace(__version__="5.0.0"))
    with pytest.raises(vision.VisionUnavailable, match=r"5\.0\.0.*CascadeClassifier.*opencv-python>=4.8,<5"):
        vision.import_cv2()
    with pytest.raises(vision.VisionUnavailable):
        vision.HaarDetector()


def test_requirements_pin_opencv_4():
    req = (PI_DIR / "requirements.txt").read_text()
    assert "opencv-python>=4.8,<5" in req


# ------------------------------------------------------------------ preview never crashes headless
def test_preview_turns_itself_off_without_a_display(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    pv = vision.PreviewWindow(True)
    assert not pv.enabled and "--preview turned off" in capsys.readouterr().err
    pv.show(object(), vision.Observation(True), False, 0.0, 6.0)      # no-op, no crash
    pv.close()


def test_preview_gui_error_disables_it_instead_of_crashing(monkeypatch, capsys):
    monkeypatch.setattr(vision, "display_available", lambda: True)

    class NoGui:
        FONT_HERSHEY_SIMPLEX = 0

        def rectangle(self, *a): pass

        def putText(self, *a): pass

        def imshow(self, *a):
            raise RuntimeError("The function is not implemented (headless build)")

    class Frame:
        def copy(self):
            return self

    monkeypatch.setattr(vision, "import_cv2", lambda: NoGui())
    pv = vision.PreviewWindow(True)
    pv.show(Frame(), vision.Observation(True, face_box=(1, 2, 3, 4)), False, 1.0, 6.0)
    assert not pv.enabled and "not implemented" in capsys.readouterr().err


# ------------------------------------------------------------------ privacy
@pytest.mark.parametrize("module", ["vision.py", "poker_round.py"])
def test_frames_are_never_written_or_sent(module):
    import re
    src = (PI_DIR / module).read_text()
    for forbidden in ("imwrite", "VideoWriter", "imencode", "requests", "socket", "urllib",
                      "pickle", "np.save", "tofile", "write_bytes", "write_text"):
        assert forbidden not in src, f"{module} must not persist or send frames ({forbidden})"
    # no builtin open() at all (Camera.open() / subprocess.Popen() are fine)
    assert not re.search(r"(?<![\w.])open\(", src.replace("def open(", "")), module


# ------------------------------------------------------------------ verdict text
class _PickEach:
    def __init__(self, i):
        self.i = i

    def choice(self, options):
        return options[self.i % len(options)]


def test_round_5_verdicts_mention_smile_and_skip_secs_when_never_smiled():
    cracked = score_poker_round(100, 0.44, first_smile_ms=1400)        # delulu_over
    texts = {ec.build_verdict_text(cracked, "Saim", rng=_PickEach(i))
             for i in range(len(ec.POKER_TEMPLATES["delulu_over"]))}
    assert any("44 percent" in t for t in texts) and any("cracked in 1 seconds" in t for t in texts)
    stony = score_poker_round(100, 0.10)                               # mild_over, no first smile
    for i in range(10):
        t = ec.build_verdict_text(stony, "Saim", rng=_PickEach(i))
        assert "unknown" not in t and "{" not in t
    assert ec.templates_for(5) is ec.POKER_TEMPLATES


def test_round_5_lines_are_poker_themed_and_not_other_rounds():
    joined = " ".join(line for lines in ec.POKER_TEMPLATES.values() for line in lines).lower()
    assert "poker" in joined and "camera" in joined
    for word in ("milli", "accelerometer", "reflex", "button"):
        assert word not in joined


def test_round_5_memory_never_repeats():
    r = score_poker_round(95, 0.40, first_smile_ms=900)
    memory = ec.LastLineMemory()
    texts = [ec.build_verdict_text(r, "Saim", memory=memory) for _ in range(20)]
    assert all(a != b for a, b in zip(texts, texts[1:]))


# ------------------------------------------------------------------ interview questions
def test_poker_questions_are_short_unique_questions_and_party_safe():
    lines = ec.POKER_QUESTION_LINES
    assert len(lines) >= 8 and len(set(lines)) == len(lines)
    for text in lines:
        assert 4 <= ec.word_count(text) <= 16, text         # fits the 6 s window
        assert "?" in text and "{" not in text and "}" not in text
        assert not any(w in text.lower() for w in ("damn", "hell", "sex", "drunk", "kill", "fat", "ugly"))
    plan = ec.question_plan("poker")
    assert [p.name for p, _ in plan][:2] == ["poker_01.mp3", "poker_02.mp3"]
    assert all(p.parent == config.QUESTIONS_DIR for p, _ in plan)


def test_default_poker_prompts_are_the_questions_then_the_old_jokes(tmp_path):
    q, j = config.QUESTIONS_DIR, config.JOKES_DIR        # isolated tmp folders (conftest)
    assert poker_round.joke_files() == []
    j.mkdir(parents=True)
    (j / "joke_01.mp3").write_bytes(b"x")
    assert [p.name for p in poker_round.joke_files()] == ["joke_01.mp3"]       # not regenerated yet
    q.mkdir(parents=True)
    (q / "poker_02.mp3").write_bytes(b"x")
    (q / "poker_01.mp3").write_bytes(b"x")
    (q / "pressure_01.mp3").write_bytes(b"x")
    assert [p.name for p in poker_round.joke_files()] == ["poker_01.mp3", "poker_02.mp3"]
    assert [p.name for p in poker_round.question_files("pressure")] == ["pressure_01.mp3"]


# ------------------------------------------------------------------ Rounds 1 and 2 unchanged
# sha256 of "\n".join(main.mock_lines(30, 5, 0, round_id)), captured at c1be6f4 (before Round 5)
# with the shipped thresholds.
GOLDEN_MOCK = {
    1: "ef41d406675a44577c54d2abc9d32733ce9e4a10da908638aef650d5d61c2285",
    2: "94c3dec7a9cf7b048e2ab161b504c55420eaa968e5407a8edbc5ef6f777755fc",
}


@pytest.mark.parametrize("round_id", [1, 2])
def test_round_1_and_2_mock_output_is_byte_identical(monkeypatch, round_id):
    monkeypatch.setattr(config, "STEADY_BEST_MG", 25.0)
    monkeypatch.setattr(config, "STEADY_WORST_MG", 500.0)
    text = "\n".join(main.mock_lines(30, 5, 0, round_id))
    assert hashlib.sha256(text.encode()).hexdigest() == GOLDEN_MOCK[round_id]


def test_round_1_and_2_console_output_has_no_round_5_text(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    for rid in ("1", "2"):
        assert main.main(["--mock", "--legacy-rounds", "--round", rid, "--rounds", "3", "--seed", "1", "--mock-delay", "0",
                          "--no-audio", "--db", str(tmp_path / f"{rid}.db")]) == 0
    out = capsys.readouterr().out
    for word in ("Poker", "camera", "smile", "joke"):
        assert word not in out
