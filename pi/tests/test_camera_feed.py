"""Round 5 browser camera: latest-frame hand-off, MJPEG endpoint, idle preview, main.py wiring.

No real camera anywhere: FakeCamera / scripted frames, and a fake renderer so
most tests don't need OpenCV (the real encoder is checked at the end with
synthetic numpy frames, skipped without cv2).
"""
import http.client
import json
import threading
import time
from pathlib import Path

import pytest

import camera_feed
import config
import main
import poker_round
import ui_server
import vision
from camera_feed import CameraFeed
from ui_server import GameState, UIServer
from vision import Observation


def fake_renderer(calls=None):
    def render(frame, obs, info):
        if calls is not None:
            calls.append((frame, info))
        return f"JPEG:{frame}:{info['mode']}".encode()
    return render


def feed_with(calls=None, **kw):
    kw.setdefault("renderer", fake_renderer(calls))
    kw.setdefault("placeholder_renderer", lambda: b"PAUSED")
    return CameraFeed(**kw)


FACE = Observation(face=True, face_box=(10, 10, 50, 50))
SMILE = Observation(face=True, smile=True, face_box=(10, 10, 50, 50), smile_box=(20, 40, 20, 10))
NOFACE = Observation(face=False)


# ------------------------------------------------------------------ latest-frame slot
def test_only_the_newest_frame_is_encoded_no_queue():
    calls = []
    feed = feed_with(calls)
    feed.begin("measuring", 6.0)
    for i in range(50):
        feed.offer(f"f{i}", FACE, False, i / 15)
    seq, jpeg = feed.wait_jpeg(0, timeout=1.0)
    assert jpeg == b"JPEG:f49:measuring"
    assert len(calls) == 1                         # the 49 older frames were simply replaced
    assert feed.wait_jpeg(seq, timeout=0.05) is None   # nothing newer yet


def test_several_browsers_share_one_jpeg_per_frame():
    calls = []
    feed = feed_with(calls)
    feed.begin("measuring", 6.0)
    feed.offer("a", FACE, False)
    assert feed.wait_jpeg(0, 1.0) == feed.wait_jpeg(0, 1.0)
    assert len(calls) == 1


def test_offer_outside_a_mode_is_ignored_and_end_drops_the_frame():
    feed = feed_with()
    feed.offer("early", FACE, False)
    assert feed.wait_jpeg(0, 0.05) is None
    feed.begin("preview")
    feed.offer("x", FACE, False)
    assert feed.wait_jpeg(0, 0.5)[1] == b"JPEG:x:preview"
    feed.end()
    assert feed._frame is None and feed._jpeg is None       # nothing kept after the window
    assert feed.wait_jpeg(0, 0.05) is None
    assert feed.mode is None


def test_end_for_another_mode_is_a_no_op():
    feed = feed_with()
    feed.begin("measuring", 6.0)
    feed.end("preview")                            # a late preview stop can't end a window
    assert feed.mode == "measuring"
    feed.end("measuring")
    assert feed.mode is None


def test_begin_never_shows_a_frame_from_the_previous_mode():
    feed = feed_with()
    feed.begin("preview")
    feed.offer("preview-frame", FACE, False)
    feed.begin("measuring", 6.0)
    assert feed.wait_jpeg(0, 0.05) is None


def test_live_smile_pct_matches_the_round_formula():
    feed = feed_with()
    feed.begin("measuring", 6.0)
    assert feed.public_state() == {"available": True, "mode": "measuring", "face": False,
                                   "smiling": False, "smilePct": None, "remainingS": 6.0, "windowS": 6.0}
    assert feed.summary() == {"available": True, "mode": "measuring", "kind": "poker"}
    for obs, smiling in ((FACE, False), (SMILE, True), (NOFACE, False), (SMILE, True)):
        feed.offer("f", obs, smiling)
    st = feed.public_state()
    assert st["smilePct"] == 67 and st["smiling"] is True and st["face"] is True   # 2 of 3 face frames
    feed.offer("f", NOFACE, False)
    assert feed.public_state()["face"] is False and feed.public_state()["smiling"] is False


def test_preview_mode_has_no_smile_pct():
    feed = feed_with()
    feed.begin("preview")
    feed.offer("f", SMILE, True)
    st = feed.public_state()
    assert st["mode"] == "preview" and st["smilePct"] is None and st["smiling"] is True


def test_producer_never_waits_for_a_slow_encoder():
    gate = threading.Event()
    started = threading.Event()

    def slow_render(frame, obs, info):
        started.set()
        gate.wait(5)
        return b"late"

    feed = CameraFeed(renderer=slow_render)
    feed.begin("measuring", 6.0)
    feed.offer("first", FACE, False)
    t = threading.Thread(target=feed.wait_jpeg, args=(0, 5.0), daemon=True)
    t.start()
    assert started.wait(2)
    t0 = time.monotonic()
    for i in range(500):                           # the encoder is stuck; offers must not be
        feed.offer(i, FACE, False)
    assert time.monotonic() - t0 < 0.5
    gate.set()
    t.join(2)


def test_offer_never_raises(capsys):
    feed = feed_with()
    feed.begin("measuring", 6.0)
    feed._cond = None                              # break the internals on purpose
    feed.offer("f", FACE, True)
    feed.begin("measuring")
    feed.end()
    assert "[camera feed]" in capsys.readouterr().err


def test_placeholder_is_made_once_and_its_failure_is_harmless(capsys):
    n = []
    feed = CameraFeed(renderer=fake_renderer(), placeholder_renderer=lambda: n.append(1) or b"P")
    assert feed.placeholder() == b"P" and feed.placeholder() == b"P" and n == [1]

    def broken():
        raise RuntimeError("no cv2")

    feed2 = CameraFeed(renderer=fake_renderer(), placeholder_renderer=broken)
    assert feed2.placeholder() is None
    assert "placeholder" in capsys.readouterr().err


def test_notify_hook_is_throttled_and_forced_on_mode_change():
    t = [0.0]
    pokes = []
    feed = feed_with(clock=lambda: t[0])
    feed.set_notify(lambda full: pokes.append((t[0], full)))
    feed.begin("measuring", 6.0)
    assert pokes == [(0.0, True)]                  # mode change: full snapshot
    last = 0
    for i in range(10):                            # 10 frames within 0.1 s: at most one more poke
        t[0] += 0.01
        feed.offer(i, SMILE if i % 2 else FACE, bool(i % 2))
        last = feed.wait_jpeg(last, 1.0)[0]
    assert len(pokes) == 1                         # all within the 0.25 s throttle
    t[0] += 0.3
    feed.offer("later", SMILE, True)
    feed.wait_jpeg(last, 1.0)
    assert len(pokes) == 2 and pokes[1][1] is False   # numbers only, no full snapshot
    feed.end()
    assert len(pokes) == 3 and pokes[-1] == (t[0], True)


def test_source_never_writes_frames_to_disk():
    src = Path(camera_feed.__file__).read_text()
    for forbidden in ("imwrite", "open(", "tofile", "VideoWriter", "VideoCapture"):
        assert forbidden not in src


# ------------------------------------------------------------------ PokerRound hand-off
def make_round(frames_per_window, **kw):
    cam = vision.FakeCamera(frames_per_window)
    return poker_round.PokerRound(cam, vision.FakeDetector(), window_s=2.0, clock=cam.now,
                                  play_jokes=False, **kw)


def test_measured_frames_reach_the_feed_and_the_reading_is_unchanged():
    window = [(True, False)] * 20 + [(True, True)] * 10
    plain = make_round([window]).run({"claim": 50, "seq": 1})
    offered = []

    class SpyFeed(CameraFeed):
        def offer(self, frame, obs, smiling, elapsed_s=0.0):
            offered.append((frame, smiling, self.mode))
            super().offer(frame, obs, smiling, elapsed_s)

    rnd = make_round([window])
    feed = SpyFeed(renderer=fake_renderer())
    rnd.attach_feed(feed)
    assert rnd.run({"claim": 50, "seq": 1}) == plain
    assert len(offered) == 30 and all(m == "measuring" for _, _, m in offered)
    assert feed.mode is None and feed._frame is None      # released after the window


def test_preview_window_and_stream_both_get_every_frame():
    shown = []

    class FakePreview:
        enabled = True

        def show(self, frame, obs, smiling, elapsed_s, window_s):
            shown.append(frame)

        def close(self):
            pass

    rnd = make_round([[(True, False)] * 12], preview=FakePreview())
    offered = []
    feed = feed_with()
    feed.offer = lambda frame, *a, **k: offered.append(frame)
    rnd.attach_feed(feed)
    rnd.run({"claim": 10, "seq": 1})
    assert len(shown) == 12 and offered == shown


def test_a_broken_feed_never_breaks_the_round(capsys):
    rnd = make_round([[(True, True)] * 15])
    feed = CameraFeed(renderer=lambda *a: 1 / 0)
    rnd.attach_feed(feed)
    feed._cond = None                              # every feed call now fails internally
    reading = rnd.run({"claim": 10, "seq": 1})
    assert reading["frames"] == 15 and "error" not in reading


class ThreadCheckingCamera:
    """Real-time fake camera that fails the test if two threads read at once."""

    def __init__(self):
        self.reads = 0
        self.busy = False
        self.overlap = False
        self.closed = False
        self.lock = threading.Lock()

    def begin_window(self):
        pass

    def read(self):
        with self.lock:
            if self.busy:
                self.overlap = True
            self.busy = True
        time.sleep(0.003)
        with self.lock:
            self.busy = False
            self.reads += 1
        return (True, self.reads % 5 == 0)

    def close(self):
        self.closed = True


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_idle_preview_reads_only_while_watched_and_yields_to_the_window():
    cam = ThreadCheckingCamera()
    rnd = poker_round.PokerRound(cam, vision.FakeDetector(), window_s=0.3, play_jokes=False)
    feed = feed_with()
    rnd.attach_feed(feed, idle_preview=True, idle_fps=50)
    try:
        time.sleep(0.3)
        assert cam.reads == 0 and feed.mode is None    # nobody watching: camera untouched
        feed.add_viewer()
        assert wait_until(lambda: feed.mode == "preview" and cam.reads > 3)
        modes = []
        real_offer = feed.offer

        def spy(frame, obs, smiling, elapsed_s=0.0):
            modes.append(feed.mode)
            real_offer(frame, obs, smiling, elapsed_s)

        feed.offer = spy
        reading = rnd.run({"claim": 40, "seq": 1})          # real clock, 0.3 s window
        assert reading["frames"] > 5 and not cam.overlap
        assert "measuring" in modes
        assert wait_until(lambda: feed.mode == "preview")    # preview resumes after the window
        feed.remove_viewer()
        assert wait_until(lambda: feed.mode is None)
        n = cam.reads
        time.sleep(0.3)
        assert cam.reads == n                               # released again
    finally:
        rnd.close()
    assert cam.closed and rnd._idle_thread is None and not cam.overlap


def test_idle_preview_errors_are_contained(capsys):
    class BadCamera(ThreadCheckingCamera):
        def read(self):
            raise OSError("usb gone")

    cam = BadCamera()
    rnd = poker_round.PokerRound(cam, vision.FakeDetector(), window_s=0.2, play_jokes=False)
    feed = feed_with()
    feed.add_viewer()
    rnd.attach_feed(feed, idle_preview=True, idle_fps=50)
    assert wait_until(lambda: "preview read failed" in capsys.readouterr().err)
    rnd.close()
    assert cam.closed


def test_window_start_is_not_held_up_by_the_preview():
    cam = ThreadCheckingCamera()
    rnd = poker_round.PokerRound(cam, vision.FakeDetector(), window_s=0.05, play_jokes=False)
    feed = feed_with()
    feed.add_viewer()
    rnd.attach_feed(feed, idle_preview=True, idle_fps=30)
    try:
        assert wait_until(lambda: feed.mode == "preview")
        t0 = time.monotonic()
        rnd.run({"claim": 1, "seq": 1})
        assert time.monotonic() - t0 < 0.5
    finally:
        rnd.close()


def test_stuck_preview_read_makes_the_window_a_vision_error_not_a_hang():
    rnd = make_round([[]])
    rnd.cam_lock_timeout_s = 0.05
    rnd._cam_lock.acquire()                        # as if a preview read hung
    try:
        with pytest.raises(vision.VisionUnavailable):
            rnd.measure()
    finally:
        rnd._cam_lock.release()
    assert not rnd._measuring.is_set()


# ------------------------------------------------------------------ HTTP endpoint + state
@pytest.fixture
def state():
    s = GameState()
    s.session_started("Saim", 5, "sess-cam")
    return s


@pytest.fixture
def server(state, tmp_path):
    srv = UIServer(state, host="127.0.0.1", port=0, static_dir=tmp_path)
    assert srv.start()
    yield srv
    srv.stop()


def test_camera_is_unavailable_without_a_feed(server, state):
    assert state.snapshot()["camera"] == {"available": False}
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/camera.mjpg")
    resp = conn.getresponse()
    assert resp.status == 503 and b"no camera feed" in resp.read()
    assert resp.getheader("Access-Control-Allow-Origin") == "*"


def read_part(resp):
    boundary = resp.readline()
    assert boundary.strip() == f"--{ui_server.MJPEG_BOUNDARY}".encode()
    headers = {}
    while True:
        line = resp.readline().strip()
        if not line:
            break
        k, v = line.decode().split(":", 1)
        headers[k.strip().lower()] = v.strip()
    assert headers["content-type"] == "image/jpeg"
    body = resp.read(int(headers["content-length"]))
    assert resp.read(2) == b"\r\n"
    return body


def test_mjpeg_stream_serves_live_frames_then_the_placeholder(server, state):
    feed = feed_with(fps=50)
    state.attach_camera(feed)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/camera.mjpg")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == f"multipart/x-mixed-replace; boundary={ui_server.MJPEG_BOUNDARY}"
    assert read_part(resp) == b"PAUSED"            # not measuring yet
    assert wait_until(lambda: feed.viewers == 1)
    feed.begin("measuring", 6.0)
    feed.offer("frame1", SMILE, True)
    assert read_part(resp) == b"JPEG:frame1:measuring"
    feed.offer("frame2", FACE, False)
    assert read_part(resp) == b"JPEG:frame2:measuring"
    assert state.snapshot(live=True)["camera"]["smilePct"] == 50
    feed.end()
    assert read_part(resp) == b"PAUSED"
    resp.close()                                   # the browser tab goes away
    conn.close()
    assert wait_until(lambda: feed.viewers == 0, 3)   # EOF noticed within about a second


def test_mjpeg_head_and_encoder_crash_only_end_the_stream(server, state, capsys):
    feed = CameraFeed(fps=50, renderer=lambda *a: 1 / 0, placeholder_renderer=lambda: b"P")
    state.attach_camera(feed)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("HEAD", "/api/camera.mjpg")
    resp = conn.getresponse()
    assert resp.status == 200 and "multipart" in resp.getheader("Content-Type")
    conn.close()
    feed.begin("measuring", 6.0)
    feed.offer("x", FACE, False)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/camera.mjpg")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.read() == b""                      # stream ended cleanly, server still fine
    assert wait_until(lambda: feed.viewers == 0)
    assert "camera stream" in capsys.readouterr().err
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/health")
    assert conn.getresponse().status == 200


def test_fast_numbers_stay_out_of_the_snapshot(state):
    feed = feed_with()
    v = state.version
    state.attach_camera(feed)
    assert state.version == v + 1
    feed.begin("measuring", 6.0)                   # mode change: a new snapshot
    assert state.version == v + 2
    before = state.snapshot_json()
    feed.offer("f", SMILE, True)
    feed.wait_jpeg(0, 1.0)
    assert state.snapshot_json() == before         # the SSE snapshot didn't change...
    assert state.snapshot()["camera"] == {"available": True, "mode": "measuring", "kind": "poker"}
    assert state.snapshot(live=True)["camera"] == {"available": True, "mode": "measuring", "face": True,
                                                   "smiling": True, "smilePct": 100,
                                                   "remainingS": 6.0, "windowS": 6.0}   # ...polling sees it
    assert json.loads(state.live_json()) == {"camera": {"mode": "measuring", "face": True,
                                                        "smiling": True, "smilePct": 100, "remainingS": 6.0, "windowS": 6.0}}


def test_api_state_includes_the_live_numbers_for_polling(server, state):
    feed = feed_with()
    state.attach_camera(feed)
    feed.begin("measuring", 6.0)
    feed.offer("f", FACE, False)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/state")
    cam = json.loads(conn.getresponse().read())["camera"]
    assert cam == {"available": True, "mode": "measuring", "face": True, "smiling": False, "smilePct": 0,
                   "remainingS": 6.0, "windowS": 6.0}


def read_sse(resp):
    """One SSE message -> (event name, parsed data)."""
    event, data = "message", []
    while True:
        line = resp.readline().decode().rstrip("\n")
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data.append(line[6:])
        elif line == "" and data:
            return event, json.loads("\n".join(data))


def test_sse_sends_the_smile_pct_as_small_live_events(server, state):
    t = [0.0]
    feed = feed_with(clock=lambda: t[0])
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/events")
    resp = conn.getresponse()
    assert read_sse(resp)[0] == "message"
    state.attach_camera(feed)
    ev, snap = read_sse(resp)
    assert ev == "message" and snap["camera"] == {"available": True, "mode": None, "kind": "poker"}
    feed.begin("measuring", 6.0)                   # a mode change is a (rare) full snapshot
    ev, snap = read_sse(resp)
    assert ev == "message" and snap["camera"] == {"available": True, "mode": "measuring", "kind": "poker"}
    last = 0
    for i, (obs, smiling) in enumerate([(FACE, False), (SMILE, True), (SMILE, True), (FACE, False)]):
        t[0] += 0.3                                # past the 4 Hz throttle each time
        feed.offer(i, obs, smiling)
        last = feed.wait_jpeg(last, 1.0)[0]
        while True:
            ev, data = read_sse(resp)
            assert ev == "live", "the fast numbers must not re-send the whole state"
            if data["camera"]["face"] and data["camera"]["smilePct"] is not None:
                break
        assert set(data) == {"camera"} and "history" not in data
    assert data["camera"]["smilePct"] == 50
    resp.close()
    conn.close()


def test_a_broken_feed_state_does_not_break_the_snapshot(state, capsys):
    class Broken:
        def set_notify(self, fn):
            pass

        def public_state(self):
            raise RuntimeError("boom")

    state.attach_camera(Broken())
    assert state.snapshot()["camera"] == {"available": False}


# ------------------------------------------------------------------ main.py wiring
def test_mock_round5_has_no_camera_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    attached = []
    monkeypatch.setattr(main, "attach_camera_feed", lambda *a: attached.append(a))
    assert main.main(["--mock", "--round", "5", "--rounds", "1", "--seed", "1", "--mock-delay", "0",
                      "--no-audio", "--db", str(tmp_path / "s.db"), "--ui", "--ui-port", "0"]) == 0
    assert attached == []


def test_real_camera_round5_with_ui_streams_the_measured_frames(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_server.GameState, "player_named", lambda self: True)   # name typed
    """--round 5 --ui on 'hardware': fake serial claim line + fake camera, real feed and server."""
    monkeypatch.setattr(config, "UI_CAMERA_IDLE_PREVIEW", False)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    cam = vision.FakeCamera([[(True, False)] * 40 + [(True, True)] * 10])
    cam.index = 2
    rnd = poker_round.PokerRound(cam, vision.FakeDetector(), window_s=4.0, clock=cam.now, play_jokes=False)
    monkeypatch.setattr(poker_round, "build", lambda **kw: rnd)
    monkeypatch.setattr(main, "serial_lines",
                        lambda *a, **k: iter(['{"type":"claim","round_id":5,"seq":1,"claim":30}']))
    feeds, offers = [], []
    real_attach = main.attach_camera_feed

    def spy_attach(ui, srv, poker):
        feed = real_attach(ui, srv, poker)
        feeds.append((ui, feed))
        real_offer = feed.offer
        feed.offer = lambda *a, **k: (offers.append(a[0]), real_offer(*a, **k))
        return feed

    monkeypatch.setattr(main, "attach_camera_feed", spy_attach)
    assert main.main(["--round", "5", "--port", "/dev/null", "--no-audio", "--db", str(tmp_path / "s.db"),
                      "--ui", "--ui-port", "0"]) == 0
    (ui, feed), = feeds
    assert isinstance(feed, CameraFeed) and ui.camera_feed is feed
    assert len(offers) == 50 and feed.mode is None
    assert ui.snapshot()["camera"]["available"] is True


def test_attach_camera_feed_failure_is_harmless(monkeypatch, capsys):
    monkeypatch.setattr(camera_feed, "CameraFeed", lambda: 1 / 0)
    assert main.attach_camera_feed(GameState(), None, make_round([[]])) is None
    assert "no browser camera" in capsys.readouterr().err


# ------------------------------------------------------------------ real OpenCV encoder
def test_real_encoder_scales_mirrors_and_leaves_the_frame_alone():
    cv2 = pytest.importorskip("cv2", exc_type=ImportError)
    np = pytest.importorskip("numpy", exc_type=ImportError)
    frame = np.zeros((720, 1280, 3), np.uint8)
    frame[:, :640] = (0, 0, 255)                   # left half red
    before = frame.copy()
    feed = CameraFeed(max_width=640, quality=60, mirror=True)
    feed.begin("measuring", 6.0)
    feed.offer(frame, SMILE, True, 1.0)
    _, jpeg = feed.wait_jpeg(0, 2.0)
    assert jpeg[:2] == b"\xff\xd8" and len(jpeg) < 200_000
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == (360, 640, 3)
    mid = img[180]
    assert mid[600][2] > 150 and mid[40][2] < 100  # mirrored: the red half is now on the right
    assert np.array_equal(frame, before)           # the measured frame was not drawn on
    feed.begin("preview")
    feed.offer(np.zeros((480, 640), np.uint8), NOFACE, False)   # grayscale frame
    assert feed.wait_jpeg(0, 2.0)[1][:2] == b"\xff\xd8"
    ph = CameraFeed().placeholder()
    assert ph is not None and ph[:2] == b"\xff\xd8"


def test_poker_live_state_counts_the_window_down():
    feed = feed_with()
    feed.begin("measuring", 6.0)
    feed.offer("f", FACE, False, 2.5)
    live = feed.live_state()
    assert live["remainingS"] == 3.5 and live["windowS"] == 6.0
    feed.end("measuring")
    assert "remainingS" not in feed.live_state()


def test_photo_is_taken_once_at_photo_at_s_only_when_wanted(monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    monkeypatch.setattr(config, "PHOTO_AT_S", 3.0)
    game = poker_round.PokerRound(camera=None, detector=None, window_s=6.0)
    frame = np.zeros((480, 1280, 3), np.uint8)
    game._on_frame(frame, None, False, 3.5)
    assert game.photo is None                              # nobody said yes
    game.want_photo = True
    game._on_frame(frame, None, False, 2.9)
    assert game.photo is None                              # too early
    game._on_frame(frame, None, False, 3.1)
    first = game.photo
    assert first and first[:2] == b"\xff\xd8"              # a JPEG
    game._on_frame(np.full((480, 1280, 3), 255, np.uint8), None, False, 4.0)
    assert game.photo is first                             # one per round
    assert camera_feed.photo_jpeg("not a frame") is None
