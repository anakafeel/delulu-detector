"""Straight Face Under Pressure (The Tell's Round 3, internal id 6): scoring, the
frame-difference tracker, the measurement loop, the round, the question barrage,
main.py wiring (mock, calibrate, serial), the UI bits, and --video on a tiny
generated clip. No webcam, no network."""
import itertools
import json
import threading

import pytest

import config
import elevenlabs_client as ec
import main
import straight_round
import ui_server
import vision
from camera_feed import CameraFeed
from scoring import ROUND_STRAIGHT, claim_to_seconds, held_s_to_performance, score_reading, score_straight_round
from session_log import SessionLog
from straight_round import QuestionBarrage, StraightRound, reading_from_straight
from vision import ExpressionTracker, FakeCamera, FakeDetector, FakeSignature, measure_straight_face

FPS = 15


def calm(level=20.0, face=True, smile=False):
    return {"face": face, "smile": smile, "sig": level}


def script(change_at_s=None, total_s=21.0, jump=25.0, smile_after=False, fps=FPS):
    """Dict frames: a neutral face (tiny alternating noise) that changes at change_at_s."""
    frames = []
    for i in range(int(total_s * fps)):
        t = (i + 1) / fps                               # FakeCamera's clock after this read
        changed = change_at_s is not None and t >= change_at_s
        noise = 0.3 if i % 2 else -0.3
        frames.append({"face": True, "smile": changed and smile_after,
                       "sig": 20.0 + noise + (jump if changed and not smile_after else 0.0)})
    return frames


def run_window(frames, max_s=20.0, **kw):
    cam = FakeCamera([frames], fps=FPS)
    cam.begin_window()
    return measure_straight_face(cam, FakeDetector(), FakeSignature(), max_s, clock=cam.now, **kw)


# ------------------------------------------------------------------ scoring
def test_claim_and_held_map_to_the_same_0_to_100_scale():
    assert config.STRAIGHT_MAX_S == 20.0
    assert claim_to_seconds(50) == 10.0 and claim_to_seconds(100) == 20.0 and claim_to_seconds(150) == 20.0
    assert held_s_to_performance(5.0) == 25.0 and held_s_to_performance(30.0) == 100.0
    assert claim_to_seconds(50, max_s=10) == 5.0 and held_s_to_performance(5, max_s=10) == 50.0
    with pytest.raises(ValueError):
        held_s_to_performance(1.0, max_s=0)


def test_score_straight_round_overconfident_and_validated():
    r = score_straight_round(claim=80, held_s=4.0, broke=True, trigger="expression",
                             face_frac=0.98, frames=70, fps=14.96)
    assert r.round_id == ROUND_STRAIGHT and r.unit == "s" and r.actual == 4.0 and r.actual_ms is None
    assert r.performance == 20.0 and r.gap == 60.0 and r.direction == "over" and r.tier == "delulu"
    assert r.extra == {"held_s": 4.0, "max_s": 20.0, "claim_s": 16.0, "broke": True,
                       "trigger": "expression", "face_frac": 0.98, "frames": 70, "fps": 15.0}
    v = score_straight_round(claim=50, held_s=10.0, broke=False)
    assert v.gap == 0 and v.tier == "validated" and v.score == 100
    assert score_straight_round(claim=10, held_s=99.0).actual == 20.0        # clamped to max_s
    with pytest.raises(ValueError):
        score_straight_round(claim=10, held_s=None)


def test_score_reading_accepts_the_round_6_result_dict():
    r = score_reading({"type": "result", "round_id": 6, "seq": 1, "claim": 40.0, "actual": 6.5,
                       "unit": "s", "held_s": 6.5, "max_s": 20.0, "broke": True, "trigger": "smile",
                       "face_frac": 0.9, "frames": 100, "fps": 15.0})
    assert r.round_id == 6 and r.actual == 6.5 and r.performance == 32.5 and r.extra["trigger"] == "smile"


# ------------------------------------------------------------------ tracker
def test_tracker_threshold_is_the_larger_of_min_diff_and_the_baseline_noise():
    t = ExpressionTracker(FakeSignature.distance, baseline_s=1.0, k=4.0, min_diff=9.0, hold_frames=3,
                          min_baseline_frames=5)
    for i in range(15):
        assert t.update(20.0 + (0.5 if i % 2 else -0.5), (i + 1) / 15) is None
    assert t.ready and t.reference == pytest.approx(20.0 - 0.5 / 15, abs=0.01)
    assert t.base_mean == pytest.approx(0.5, abs=0.05) and t.threshold == 9.0
    noisy = ExpressionTracker(FakeSignature.distance, baseline_s=1.0, k=4.0, min_diff=1.0,
                              hold_frames=3, min_baseline_frames=5)
    for i, v in enumerate([10, 14, 6, 12, 8, 13, 7, 10, 11, 9, 15, 5, 10, 10, 10]):
        noisy.update(float(v), (i + 1) / 15)
    assert noisy.threshold == pytest.approx(noisy.base_mean + 4 * noisy.base_std) and noisy.threshold > 1.0


def test_tracker_needs_consecutive_frames_and_reports_the_first_one():
    t = ExpressionTracker(FakeSignature.distance, baseline_s=0.2, k=4.0, min_diff=5.0, hold_frames=3,
                          min_baseline_frames=2)
    t.update(0.0, 0.1)
    t.update(0.0, 0.2)
    assert t.ready
    assert t.update(9.0, 0.3) is None and t.update(0.0, 0.4) is None      # one-frame blip ignored
    assert t.update(9.0, 0.5) is None and t.update(9.0, 0.6) is None
    assert t.update(9.0, 0.7) == 0.5                                        # time of the first frame
    assert t.peak == 9.0 and t.level == pytest.approx(9.0 / 5.0)


def test_tracker_waits_for_enough_baseline_frames():
    t = ExpressionTracker(FakeSignature.distance, baseline_s=0.1, min_baseline_frames=5)
    for i in range(4):
        t.update(1.0, 1.0 + i)
    assert not t.ready and t.baseline_frames == 4
    t.update(1.0, 9.0)
    assert t.ready and t.baseline_frames == 0                               # crops dropped


# ------------------------------------------------------------------ measurement loop
def test_change_is_timed_and_the_window_ends_after_the_tail():
    changes = []
    st = run_window(script(change_at_s=3.0), on_change=lambda t, why: changes.append((t, why)))
    assert st.broke and st.trigger == "expression" and st.baseline_ok and st.completed
    assert st.changed_at_s == pytest.approx(3.0, abs=1 / FPS) and st.held_s == st.changed_at_s
    assert changes == [(st.changed_at_s, "expression")]
    assert st.elapsed_s == pytest.approx(3.0 + 2 / FPS + config.STRAIGHT_TAIL_S, abs=0.15)
    assert st.threshold == 9.0 and st.peak_score > 20


def test_holding_to_the_end_scores_the_full_window():
    st = run_window(script(change_at_s=None))
    assert not st.broke and st.completed and st.held_s == 20.0 and st.trigger is None
    assert st.frames == 300 and st.face_frac == 1.0 and st.fps == pytest.approx(15.0)


def test_a_smoothed_smile_also_ends_the_hold():
    st = run_window(script(change_at_s=5.0, smile_after=True))
    assert st.broke and st.trigger == "smile"
    assert 5.0 <= st.changed_at_s <= 5.0 + 3 / FPS                          # 2 of 3 frames smoothing
    off = run_window(script(change_at_s=5.0, smile_after=True), smile_breaks=False)
    assert not off.broke and off.held_s == 20.0


def test_no_face_means_no_baseline_and_an_early_stop():
    st = run_window([calm(face=False)] * 400)
    assert not st.baseline_ok and not st.completed and st.face_frames == 0
    assert st.elapsed_s == pytest.approx(config.STRAIGHT_BASELINE_TIMEOUT_S, abs=0.1)
    assert reading_from_straight({"claim": 50, "seq": 3}, st)["error"] == "no_face"


def test_dead_camera_is_a_camera_read_error():
    st = run_window([])
    assert st.frames == 0 and st.read_failures == 25
    assert reading_from_straight({"claim": 50}, st)["error"] == "camera_read"
    cut = run_window(script(change_at_s=None, total_s=8.0))                 # camera died at 8 s
    assert cut.baseline_ok and not cut.completed
    assert reading_from_straight({"claim": 50}, cut)["error"] == "camera_read"


def test_on_frame_gets_the_overlay_info_in_every_phase():
    phases = []
    run_window(script(change_at_s=3.0), on_frame=lambda f, o, info: phases.append(dict(info)))
    assert [p["phase"] for p in phases][0] == "baseline"
    assert {"baseline", "watching", "changed"} <= {p["phase"] for p in phases}
    last = phases[-1]
    assert last["changed_at_s"] is not None and last["held_s"] == last["changed_at_s"]
    assert last["trigger"] == "expression" and last["max_s"] == 20.0
    watching = [p for p in phases if p["phase"] == "watching"]
    assert watching[0]["level"] is None                                     # baseline just finished
    assert all(p["level"] is not None and p["level"] < 1 for p in watching[1:-3])


def test_a_failing_on_change_does_not_end_the_window(capsys):
    def boom(t, why):
        raise OSError("port gone")
    st = run_window(script(change_at_s=2.0), on_change=boom)
    assert st.broke and st.completed and "could not signal" in capsys.readouterr().err


# ------------------------------------------------------------------ reading
def test_reading_shape():
    st = run_window(script(change_at_s=6.0))
    r = reading_from_straight({"type": "claim", "round_id": 6, "seq": 4, "claim": 72}, st)
    assert r["round_id"] == 6 and r["seq"] == 4 and r["claim"] == 72.0 and r["unit"] == "s"
    assert r["actual"] == r["held_s"] == pytest.approx(6.0, abs=0.1) and r["broke"] is True
    assert r["trigger"] == "expression" and r["max_s"] == 20.0 and r["threshold"] == 9.0
    assert "error" not in r and r["false_start"] is False and r["timeout"] is False
    json.dumps(r, allow_nan=False)
    assert score_reading(r).performance == pytest.approx(30.0, abs=0.5)


# ------------------------------------------------------------------ barrage
class FakeProc:
    def __init__(self, path, finished=True):
        self.path, self.finished, self.killed = path, finished, False

    def poll(self):
        return 0 if (self.finished or self.killed) else None


def test_barrage_plays_every_clip_shuffled_and_loops(tmp_path):
    files = [tmp_path / f"pressure_{i:02d}.mp3" for i in range(1, 4)]
    procs = []
    b = QuestionBarrage(files, lambda p: procs.append(FakeProc(p)) or procs[-1], lambda p: None,
                        gap_s=0.0, poll_s=0.001)
    b.start()
    for _ in range(200):
        if len(b.played) >= 7:
            break
        threading.Event().wait(0.005)
    b.join()
    assert len(b.played) >= 7 and set(b.played[:3]) == set(files)          # a full pass before repeats


def test_barrage_stop_kills_the_playing_clip_and_no_player_means_silence(tmp_path):
    started, stopped = [], []

    def start(p):
        started.append(FakeProc(p, finished=False))
        return started[-1]

    def stop(proc):
        proc.killed = True
        stopped.append(proc)

    b = QuestionBarrage([tmp_path / "pressure_01.mp3"], start, stop, gap_s=0.0, poll_s=0.001).start()
    for _ in range(200):
        if started:
            break
        threading.Event().wait(0.005)
    b.stop()
    b.join()
    assert started and started[0].killed and started[0] in stopped
    silent = QuestionBarrage([tmp_path / "x.mp3"], lambda p: None, lambda p: None).start()
    silent.join()
    assert silent.played == []
    assert QuestionBarrage([], lambda p: pytest.fail("no files"), lambda p: None).start()._thread is None


# ------------------------------------------------------------------ the round
def _round(windows, **kw):
    cam = FakeCamera(windows, fps=FPS)
    kw.setdefault("play_questions", False)
    return StraightRound(cam, FakeDetector(), FakeSignature(), 20.0, clock=cam.now, **kw), cam


def test_round_run_stops_the_questions_and_signals_the_change(tmp_path):
    q = tmp_path / "questions"
    q.mkdir()
    for i in (1, 2):
        (q / f"pressure_{i:02d}.mp3").write_bytes(b"x")
    procs = []
    changes = []
    rnd, cam = _round([script(change_at_s=4.0)], play_questions=True, questions_dir=q,
                      start_audio_fn=lambda p: procs.append(FakeProc(p, finished=False)) or procs[-1],
                      stop_audio_fn=lambda proc: setattr(proc, "killed", True),
                      on_change=lambda t, why: changes.append(why))
    r = rnd.run({"type": "claim", "round_id": 6, "seq": 1, "claim": 40})
    assert r["held_s"] == pytest.approx(4.0, abs=0.1) and changes == ["expression"]
    assert procs and all(p.killed for p in procs) and rnd.last_barrage._thread is None
    rnd.close()
    assert not cam.opened


def test_round_feeds_the_straight_overlay_to_the_browser_stream():
    rnd, _ = _round([script(change_at_s=4.0)])
    seen = []
    feed = CameraFeed(renderer=lambda f, o, info: b"jpeg", clock=lambda: 0.0)
    orig = feed.offer

    def spy(frame, obs, smiling, elapsed_s=0.0, extra=None):
        orig(frame, obs, smiling, elapsed_s, extra)
        seen.append(feed.live_state())
    feed.offer = spy
    rnd.attach_feed(feed)
    rnd.run({"claim": 40})
    assert feed.mode is None and feed.summary()["kind"] == "straight"      # ended after the window
    assert seen[0]["phase"] == "baseline" and seen[0]["heldS"] is not None
    last = seen[-1]
    assert last["phase"] == "changed" and last["changedAtS"] == pytest.approx(4.0, abs=0.1)
    assert last["trigger"] == "expression" and last["mode"] == "measuring"
    assert set(last) == {"mode", "face", "smiling", "smilePct", "phase", "heldS", "changedAtS",
                         "trigger", "level"}


def test_poker_live_state_has_no_straight_keys():
    feed = CameraFeed(renderer=lambda f, o, info: b"jpeg")
    feed.begin("measuring", 6.0)
    feed.offer(object(), vision.Observation(True, False), False, 1.0, extra={"phase": "watching"})
    assert set(feed.live_state()) == {"mode", "face", "smiling", "smilePct", "remainingS", "windowS"}


def test_straight_overlay_renders_every_phase():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    feed = CameraFeed()
    frame = np.zeros((240, 320, 3), np.uint8)
    obs = vision.Observation(True, False, face_box=(100, 60, 100, 100))
    feed.begin("measuring", 20.0, kind="straight")
    for info in ({"phase": "baseline", "held_s": 0.5, "level": None},
                 {"phase": "watching", "held_s": 3.0, "level": 0.4},
                 {"phase": "watching", "held_s": 3.2, "level": 1.3},
                 {"phase": "changed", "held_s": 3.1, "changed_at_s": 3.1, "trigger": "smile", "level": 2.0}):
        feed.offer(frame, obs, False, info["held_s"], extra=info)
        got = feed.wait_jpeg(0, timeout=1.0)
        assert got is not None and got[1][:2] == b"\xff\xd8"


# ------------------------------------------------------------------ main.py
MOCK_R6 = ["--mock", "--round", "6", "--mock-delay", "0", "--no-audio"]


def test_mock_round_6_end_to_end_logs_seconds(monkeypatch, tmp_path, capsys):
    verdicts = []
    monkeypatch.setattr(main, "deliver_verdict", lambda r, p, play=True: verdicts.append(r))
    db = tmp_path / "s.db"
    assert main.main(MOCK_R6 + ["--rounds", "20", "--seed", "4", "--db", str(db)]) == 0
    out, err = capsys.readouterr()
    assert "Round 3: Straight Face" in out and "mock camera + fake detector" in out
    assert "claim" in out and "= " in out and "s locked" in out
    with SessionLog(db) as log:
        rows = log.rounds()
    errors = err.count("sensor error 'no_face'")
    assert len(rows) == len(verdicts) == 20 - errors and len(rows) >= 10
    for row in rows:
        extra = json.loads(row["extra"])
        assert row["round_id"] == 6 and row["unit"] == "s" and row["actual_ms"] is None
        assert 0 <= row["actual"] <= 20.0 and extra["held_s"] == pytest.approx(row["actual"])
        assert extra["max_s"] == 20.0 and extra["claim_s"] == pytest.approx(row["claim"] / 5, abs=0.1)
        assert row["performance"] == pytest.approx(row["actual"] * 5, abs=0.1)
    assert any(json.loads(r["extra"]).get("broke") for r in rows)


def test_round_6_verdicts_use_the_straight_templates():
    r = score_straight_round(claim=90, held_s=3.0, broke=True)
    text = ec.build_verdict_text(r, "Saim", rng=type("P", (), {"choice": lambda self, o: o[0]})())
    assert text == ec.STRAIGHT_TEMPLATES["delulu_over"][0].format(claimsecs=18, held=3, player="Saim")
    assert ec.templates_for(6) is ec.STRAIGHT_TEMPLATES


def test_calibrate_round_6_prints_raw_numbers_and_never_scores(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise AssertionError("calibrate must not score, narrate or log")
    monkeypatch.setattr(main, "process_reading", boom)
    monkeypatch.setattr(main, "deliver_verdict", boom)
    db = tmp_path / "never.db"
    assert main.main(MOCK_R6 + ["--calibrate", "--rounds", "5", "--seed", "3", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "CALIBRATION (Round 3: Straight Face" in out and out.count("calib #") == 5
    assert "baseline" in out and "threshold 9.0" in out and "STRAIGHT_MIN_DIFF=9" in out
    assert not db.exists()


def test_round_6_claim_is_ignored_when_poker_face_is_selected(monkeypatch, tmp_path, capsys):
    line = '{"type":"claim","round_id":6,"seq":1,"claim":50}'
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter([line]))
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: pytest.fail("nothing to narrate"))
    assert main.main(["--mock", "--round", "5", "--no-audio", "--db", str(tmp_path / "s.db")]) == 0
    assert "ignoring a Round 3: Straight Face claim" in capsys.readouterr().out


def test_main_wires_the_change_to_the_serial_stop_line(monkeypatch, tmp_path):
    built = {}
    real_build = straight_round.build

    def spy(**kw):
        built["round"] = real_build(**kw)
        return built["round"]
    monkeypatch.setattr(straight_round, "build", spy)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    assert main.main(MOCK_R6 + ["--rounds", "1", "--seed", "1", "--db", str(tmp_path / "s.db")]) == 0
    cb = built["round"].on_change
    assert isinstance(cb.__self__, main.SerialLink) and cb.__func__ is main.SerialLink.stop_cue


def test_serial_link_writes_only_while_open():
    link = main.SerialLink()
    assert link.write(b"S\n") is False
    writes = []
    link.ser = type("P", (), {"write": lambda self, d: writes.append(d)})()
    link.stop_cue(3.2, "expression")
    assert writes == [b"S\n"] and link.sent == [b"S\n"]
    link.ser = type("P", (), {"write": lambda self, d: (_ for _ in ()).throw(OSError("gone"))})()
    assert link.write(b"S\n") is False


def test_serial_lines_round_6_sets_a_20_s_cue_and_hands_over_the_port(monkeypatch):
    from test_round_selection import BOOT, _FakeSerialPort, _fake_serial_module
    monkeypatch.setattr(config, "SERIAL_OPEN_SETTLE_S", 0)
    ack = '{"type":"status","state":"mode","round_id":6,"accel":"none"}\r\n'
    claim = '{"type":"claim","round_id":6,"seq":1,"claim":40}\n'
    port = _FakeSerialPort([ack, '{"type":"status","state":"window","window_ms":20000}\n', claim, BOOT, ack])
    link = main.SerialLink()
    gen = main.serial_lines("/dev/fake", 115200, 6, serial_module=_fake_serial_module(port), link=link)
    got = list(itertools.islice(gen, 3))
    assert got[2] == claim and link.ser is port
    link.stop_cue()
    list(itertools.islice(gen, 2))
    assert port.writes == [b"R6\n", b"W20000\n", b"S\n", b"R6\n", b"W20000\n"]
    assert main.selection_line(6) == b"R6\n"
    assert straight_round.straight_window_line(20) == b"W20000\n"


def test_max_seconds_outside_the_sketch_range_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "STRAIGHT_MAX_S", 45.0)
    with pytest.raises(SystemExit):
        main.main(["--mock", "--round", "6"])


def test_video_flag_is_only_for_the_face_rounds():
    with pytest.raises(SystemExit):
        main.main(["--mock", "--round", "1", "--video", "clip.mp4"])


def test_ui_active_round_carries_the_label_and_the_seconds_scale():
    info = ui_server.active_round(6)
    assert info == {"round_id": "straight_face", "round_type_id": 6,
                    "round_name": "Straight Face Under Pressure", "round_label": 3, "claim_max_s": 20.0}
    assert ui_server.active_round(5)["round_label"] == 2 and ui_server.active_round(2)["round_label"] is None


def test_ui_reveal_for_round_6():
    state = ui_server.GameState()
    state.session_started("Saim", 6, "sess", mock=True)
    state.claim_locked(6, 60)
    snap = state.snapshot()
    assert snap["screen"] == "performing" and snap["activeRound"]["claim_max_s"] == 20.0
    r = score_straight_round(claim=60, held_s=7.5, broke=True, trigger="expression")
    res = ui_server.result_from_round(r, "Saim", "sess", 1)
    assert res["round_key"] == "straight_face" and res["actual_unit"] == "s" and res["actual_raw"] == 7.5
    assert res["actual"] == 37.5 and res["round_label"] == 3 and res["extra"]["broke"] is True


# ------------------------------------------------------------------ --video (tiny generated clip)
def _make_clip(path, change_at_s=2.0, secs=4.0, fps=15):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 120))
    if not writer.isOpened():
        pytest.skip("this OpenCV build can't write MJPG .avi")
    rng = np.random.default_rng(0)
    for i in range(int(fps * secs)):
        img = np.full((120, 160, 3), 30, np.uint8)
        cv2.rectangle(img, (50, 20), (110, 100), (200, 200, 200), -1)             # the "face"
        cv2.circle(img, (65, 45), 5, (40, 40, 40), -1)
        cv2.circle(img, (95, 45), 5, (40, 40, 40), -1)
        if i / fps < change_at_s:
            cv2.rectangle(img, (72, 78), (88, 82), (40, 40, 40), -1)              # neutral mouth
        else:
            cv2.ellipse(img, (80, 80), (18, 10), 0, 0, 360, (40, 40, 40), -1)      # mouth opens
        img = np.clip(img.astype(int) + rng.integers(-3, 4, img.shape), 0, 255).astype(np.uint8)
        writer.write(img)
    writer.release()
    return path


class BlobDetector:
    """Bright rectangle = the face (the Haar cascade isn't meant for drawings)."""

    def detect(self, frame):
        import cv2
        import numpy as np
        ys, xs = np.nonzero(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) > 120)
        if len(xs) == 0:
            return vision.Observation(False, False)
        return vision.Observation(True, False, (int(xs.min()), int(ys.min()),
                                                int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))


def test_video_clip_expression_change_is_found_at_the_right_second(tmp_path):
    clip = _make_clip(tmp_path / "clip.avi", change_at_s=2.0)
    cam = vision.VideoFileCamera(clip, loop=False).open()
    assert cam.fps == 15.0 and cam.size == (160, 120) and cam.now() == 0.0
    st = measure_straight_face(cam, BlobDetector(), vision.FaceSignature(), 20.0, clock=cam.now,
                               smile_breaks=False)
    cam.close()
    assert st.baseline_ok and st.broke and st.trigger == "expression"
    assert st.changed_at_s == pytest.approx(2.0, abs=0.15)
    assert st.baseline_mean < 2.0 and st.threshold == 9.0 and st.peak_score > 20


def test_video_camera_loops_or_ends(tmp_path):
    clip = _make_clip(tmp_path / "c.avi", secs=1.0)
    once = vision.VideoFileCamera(clip, loop=False).open()
    frames = [once.read() for _ in range(15)]
    assert all(f is not None for f in frames) and once.read() is None and once.ended
    assert once.now() == pytest.approx(16 / 15)
    looped = vision.VideoFileCamera(clip, loop=True).open()
    assert all(looped.read() is not None for _ in range(40)) and not looped.ended
    once.close()
    looped.close()
    with pytest.raises(vision.VisionUnavailable):
        vision.VideoFileCamera(tmp_path / "missing.mp4").open()


def test_vision_cli_measures_a_clip(tmp_path, capsys):
    clip = _make_clip(tmp_path / "c.avi", secs=3.0)
    assert vision.main(["--video", str(clip), "--round", "straight", "--windows", "2",
                        "--window-s", "2", "--no-loop"]) == 0
    out = capsys.readouterr().out
    assert "straight | source" in out and "window 1:" in out
    assert vision.main(["--video", str(clip), "--round", "poker", "--window-s", "1"]) == 0
    assert "smile" in capsys.readouterr().out
    assert vision.main(["--video", str(tmp_path / "nope.mp4")]) == 2


@pytest.mark.parametrize("round_id", ["5", "6"])
def test_main_video_calibration_runs_both_face_rounds_on_the_clip(tmp_path, capsys, round_id):
    pytest.importorskip("cv2")
    clip = _make_clip(tmp_path / "c.avi", secs=3.0)
    assert main.main(["--mock", "--round", round_id, "--video", str(clip), "--calibrate", "--rounds", "2",
                      "--mock-delay", "0", "--no-audio"]) == 0
    out = capsys.readouterr().out
    assert f"video {clip}" in out and out.count("calib #") == 2
