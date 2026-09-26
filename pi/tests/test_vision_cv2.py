"""Optional smoke tests against the REAL OpenCV (skipped when cv2 isn't importable).

They check the real code path runs: the built-in Haar cascades load, synthetic
frames go through HaarDetector without errors (and contain no face), and a fake
VideoCapture drives Camera + HaarDetector + measure_window into a no_face
reading. Detecting faces or smiles in synthetic images would be meaningless, so
real detection quality is checked on the hardware with --calibrate / --preview.
No camera, no display, no network needed.
"""
import pytest

cv2 = pytest.importorskip("cv2", exc_type=ImportError)   # also a broken install (e.g. no libGL)
np = pytest.importorskip("numpy", exc_type=ImportError)

import poker_round  # noqa: E402
import vision  # noqa: E402


def test_opencv_is_4x_with_cascades():
    assert int(cv2.__version__.split(".")[0]) == 4
    assert hasattr(cv2, "CascadeClassifier")
    vision.import_cv2()


def test_builtin_cascades_load():
    d = vision.HaarDetector()
    assert not d.face.empty() and not d.smile.empty()
    assert vision.cascade_path("haarcascade_smile.xml", cv2).is_file()


def test_synthetic_frames_have_no_face_and_do_not_crash():
    d = vision.HaarDetector()
    blank = np.full((480, 640, 3), 128, np.uint8)
    noise = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    gray = np.zeros((240, 320), np.uint8)
    for frame in (blank, noise, gray):
        obs = d.detect(frame)
        assert obs.face is False and obs.smile is False


def test_detector_rejects_unknown_parameters():
    with pytest.raises(TypeError):
        vision.HaarDetector(smile_min_neighbours=20)
    d = vision.HaarDetector(smile_min_neighbors=25, smile_scale_factor=1.6)
    assert d.params["SMILE_MIN_NEIGHBORS"] == 25 and d.params["SMILE_SCALE_FACTOR"] == 1.6


class _FakeCapture:
    """Stands in for cv2.VideoCapture: 640x480 grey frames, no device."""

    def __init__(self, index):
        self.index = index
        self.released = False

    def isOpened(self):
        return True

    def set(self, *a):
        return True

    def grab(self):
        return True

    def read(self):
        return True, np.full((480, 640, 3), 90, np.uint8)

    def release(self):
        self.released = True


def test_camera_and_detector_end_to_end_with_a_fake_capture(monkeypatch):
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    cam = vision.Camera(3).open()
    assert cam.size == (640, 480) and cam._cap.index == 3
    t = {"now": 0.0}

    def clock():
        t["now"] += 0.1
        return t["now"]

    pr = poker_round.PokerRound(cam, vision.HaarDetector(), window_s=1.0, clock=clock, play_jokes=False)
    reading = pr.run({"claim": 70, "seq": 1})
    assert reading["frames"] > 0 and reading["face_frac"] == 0.0 and reading["error"] == "no_face"
    cap = cam._cap
    pr.close()
    assert cap.released and cam._cap is None


def test_camera_uses_config_index_by_default(monkeypatch):
    import config
    monkeypatch.setattr(config, "POKER_CAMERA_INDEX", 2)
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    cam = vision.Camera().open()
    assert cam.index == 2 and cam._cap.index == 2
    cam.close()


def test_camera_that_will_not_open_is_a_clear_error(monkeypatch):
    class Closed(_FakeCapture):
        def isOpened(self):
            return False

    monkeypatch.setattr(cv2, "VideoCapture", Closed)
    with pytest.raises(vision.VisionUnavailable, match="could not open camera index 7"):
        vision.Camera(7).open()
