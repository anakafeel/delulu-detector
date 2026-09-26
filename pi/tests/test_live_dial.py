"""Live dial ({"type":"dial","value":N}): parsing, other parsers ignoring it, UI state, main loop."""
import itertools
import json
import types

import pytest

import config
import main
import ui_server
from scoring import score_reflex_round
from ui_server import GameState


def dial_line(value):
    return json.dumps({"type": "dial", "value": value})


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize("line,expected", [
    ('{"type":"dial","value":57}', 57),
    ('{"type":"dial","value":0}', 0),
    ('{"type":"dial","value":100}', 100),
    ('{"type":"dial","value":42.6}', 43),
    ('{"type":"dial","value":-3}', 0),
    ('{"type":"dial","value":250}', 100),
    ('  {"type":"dial","value":12}\r\n', 12),
])
def test_parse_dial_accepts_and_clamps(line, expected):
    assert main.parse_dial(line) == expected


@pytest.mark.parametrize("line", [
    '{"type":"dial"}',
    '{"type":"dial","value":null}',
    '{"type":"dial","value":"57"}',
    '{"type":"dial","value":true}',
    '{"type":"dial","value":NaN}',
    '{"type":"dial","value":Infinity}',
    '{"type":"dial","value":[1]}',
    '{"type":"status","state":"ready"}',
    '{"type":"result","round_id":1,"claim":50,"actual":300}',
    '{"type":"dial","val',                      # half line
    'dial 57',
    '',
    '[1, 2]',
])
def test_parse_dial_rejects_everything_else(line):
    assert main.parse_dial(line) is None


def test_existing_parsers_ignore_dial_lines():
    line = dial_line(57)
    assert main.parse_line(line) is None
    assert main.parse_status(line) is None


def test_round_selector_ignores_dial_lines():
    sel = main.RoundSelector(2, clock=lambda: 0.0)
    sel.start()
    assert sel.on_line(dial_line(57)) is None
    assert sel.acked is False


def test_locked_status_with_claim_still_parses_as_status():
    status = main.parse_status('{"type":"status","state":"locked","claim":72}')
    assert status["state"] == "locked" and status["claim"] == 72
    assert main.parse_line('{"type":"status","state":"locked","claim":72}') is None


# ------------------------------------------------------------------ UI state
class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def armed(clock):
    s = GameState(clock=clock, reveal_hold_s=10, idle_after_s=60)
    s.session_started("Saim", 1, "sess")
    s.on_status({"type": "status", "state": "mode", "round_id": 1})
    return s


def test_dial_shows_as_live_claim_while_setting_the_claim(armed):
    assert armed.snapshot()["liveClaim"] is None          # old sketch: nothing yet
    armed.dial(57)
    snap = armed.snapshot()
    assert snap["screen"] == "predicting" and snap["liveClaim"] == 57
    armed.dial(58.4)
    assert armed.snapshot()["liveClaim"] == 58


def test_dial_clamps_and_ignores_garbage(armed, capsys):
    armed.dial(140)
    assert armed.snapshot()["liveClaim"] == 100
    armed.dial(None)
    armed.dial("abc")
    armed.dial(float("nan"))
    assert armed.snapshot()["liveClaim"] == 100
    json.dumps(armed.snapshot(), allow_nan=False)


def test_turning_the_knob_on_the_claim_screen_does_not_bump_the_version(armed):
    # Only the number moves: the event stream sends it as a small `dial` event instead.
    armed.dial(40)
    v = armed.snapshot()["version"]
    armed.dial(40)
    armed.dial(41)
    snap = armed.snapshot()
    assert snap["version"] == v and snap["liveClaim"] == 41


def test_turning_the_knob_to_a_new_screen_bumps_the_version(armed, clock):
    armed.dial(30)
    clock.t += 61                                    # idle timeout
    v = armed.snapshot()["version"]
    armed.dial(31)                                   # wakes the idle screen: a real change
    assert armed.snapshot()["version"] > v


def test_turning_the_knob_wakes_the_idle_screen(armed, clock):
    armed.dial(30)
    clock.t += 61
    assert armed.snapshot()["screen"] == "idle"
    armed.dial(31)
    snap = armed.snapshot()
    assert snap["screen"] == "predicting" and snap["liveClaim"] == 31
    clock.t += 59
    assert armed.snapshot()["screen"] == "predicting"   # the idle timeout restarted


def test_dial_before_the_board_is_armed_does_not_leave_idle(clock):
    s = GameState(clock=clock)
    s.session_started("Saim", 1, "sess")
    s.dial(20)
    assert s.snapshot()["screen"] == "idle"
    s.on_status({"type": "status", "state": "mode", "round_id": 1})
    snap = s.snapshot()
    assert snap["screen"] == "predicting" and snap["liveClaim"] is None   # cleared by the ack
    s.dial(20)                                       # the sketch re-sends it right after the ack
    assert s.snapshot()["liveClaim"] == 20


def test_locked_uses_the_claim_on_the_status_line(armed):
    armed.dial(55)
    armed.on_status({"type": "status", "state": "locked", "claim": 56})
    snap = armed.snapshot()
    assert snap["screen"] == "performing" and snap["liveClaim"] == 56


def test_locked_without_claim_falls_back_to_the_last_dial_value(armed):
    armed.dial(44)
    armed.on_status({"type": "status", "state": "locked"})
    assert armed.snapshot()["liveClaim"] == 44


def test_locked_with_an_old_sketch_has_no_claim(armed):
    armed.on_status({"type": "status", "state": "locked"})
    assert armed.snapshot()["liveClaim"] is None


def test_dial_during_reveal_keeps_the_result_for_the_minimum_time(armed, clock):
    armed.dial(60)
    armed.round_result(score_reflex_round(60, 300), "Saim", "sess", 1)
    armed.on_status({"type": "status", "state": "ready"})
    armed.dial(61)                                   # knob nudged right after the result
    snap = armed.snapshot()
    assert snap["screen"] == "reveal" and snap["liveClaim"] == 60
    clock.t += config.UI_REVEAL_MIN_S + 0.5
    armed.dial(70)                                   # turning it now means: next claim
    snap = armed.snapshot()
    assert snap["screen"] == "predicting" and snap["liveClaim"] == 70


def test_unchanged_post_round_report_does_not_end_the_reveal(armed, clock):
    armed.dial(60)
    armed.round_result(score_reflex_round(60, 300), "Saim", "sess", 1)
    clock.t += config.UI_REVEAL_MIN_S + 1
    armed.on_status({"type": "status", "state": "ready"})
    armed.dial(60)                                   # the sketch re-sends the same value
    assert armed.snapshot()["screen"] == "reveal"
    clock.t += 10
    assert armed.snapshot()["screen"] == "predicting"   # normal hold expiry still works
    assert armed.snapshot()["liveClaim"] == 60


def test_dial_does_not_disturb_a_round_in_progress(armed):
    armed.on_status({"type": "status", "state": "locked", "claim": 50})
    armed.dial(90)                                    # can't happen with the sketch, but be safe
    snap = armed.snapshot()
    assert snap["screen"] == "performing" and snap["liveClaim"] == 50


@pytest.mark.parametrize("reset", [
    pytest.param(lambda s: s.on_status({"type": "status", "state": "ready", "accel": "none"}),
                 id="boot-banner"),
    pytest.param(lambda s: s.serial_opened(), id="serial-reconnect"),
    pytest.param(lambda s: s.session_started("Saim", 2, "sess2"), id="round-select"),
    pytest.param(lambda s: s.on_status({"type": "status", "state": "mode", "round_id": 1}),
                 id="mode-ack"),
])
def test_stale_dial_value_is_cleared(armed, reset):
    armed.dial(66)
    reset(armed)
    assert armed.dial_value is None
    # An older sketch answers from here on (no dial lines): "?" again, not the old 66.
    armed.on_status({"type": "status", "state": "mode", "round_id": armed.selected_round})
    assert armed.snapshot()["liveClaim"] is None
    armed.on_status({"type": "status", "state": "locked"})
    snap = armed.snapshot()
    assert snap["screen"] == "performing" and snap["liveClaim"] is None


def test_serial_reopen_disarms_like_a_board_reset(armed):
    armed.serial_opened()
    snap = armed.snapshot()
    assert snap["board"] == {"armed": False, "stage": "connecting"} and snap["screen"] == "idle"


def test_serial_lines_calls_on_open_each_time_the_port_opens(monkeypatch):
    monkeypatch.setattr(config, "SERIAL_OPEN_SETTLE_S", 0)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    opened = []

    class SerialException(Exception):
        pass

    class Port:
        def __init__(self):
            self.lines = [b'{"type":"status","state":"mode","round_id":1}\n']

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def reset_input_buffer(self):
            pass

        def write(self, data):
            pass

        def readline(self):
            if not self.lines:
                raise SerialException("unplugged")
            return self.lines.pop(0)

    fake = types.SimpleNamespace(Serial=lambda *a, **k: Port(), SerialException=SerialException)
    gen = main.serial_lines("/dev/fake", 115200, 1, serial_module=fake,
                            on_open=lambda: opened.append(True))
    list(itertools.islice(gen, 2))                   # one line, unplug, reopen, one line
    assert opened == [True, True]


def test_main_clears_the_dial_when_the_serial_port_reopens(monkeypatch, tmp_path):
    calls = []

    def fake_serial(port, baud, round_id, on_open=None, link=None):
        on_open()
        yield dial_line(40)
        on_open()                                    # reconnected (maybe a different sketch)
        yield '{"type":"status","state":"mode","round_id":1}'

    monkeypatch.setattr(main, "serial_lines", fake_serial)
    real = ui_server.GameState.serial_opened

    def spy(self):
        real(self)
        calls.append(self.dial_value)

    monkeypatch.setattr(ui_server.GameState, "serial_opened", spy)
    main.main(["--port", "/dev/fake", "--no-audio", "--db", str(tmp_path / "s.db"),
               "--ui", "--ui-host", "127.0.0.1", "--ui-port", "0"])
    assert calls == [None, None]


# ------------------------------------------------------------------ mock
def test_plain_mock_has_no_dial_lines():
    for rid in (1, 2):
        lines = list(main.mock_lines(5, 1, 0, rid))
        assert not any(main.parse_dial(ln) is not None for ln in lines)
        assert all("claim" not in json.loads(ln) for ln in lines if main.parse_status(ln))


@pytest.mark.parametrize("round_id", [1, 2])
def test_mock_with_dial_turns_the_knob_to_each_claim(round_id):
    lines = list(main.mock_lines(4, 3, 0, round_id, dial_step_s=0))
    plain = list(main.mock_lines(4, 3, 0, round_id))
    last_dial = None
    for ln in lines:
        d = main.parse_dial(ln)
        if d is not None:
            last_dial = d
            continue
        status = main.parse_status(ln)
        if status and status["state"] == "locked":
            assert status["claim"] == last_dial
        reading = main.parse_line(ln)
        if reading is not None:
            assert reading["claim"] == last_dial
    # same results as plain mock: the dial doesn't change the simulated rounds
    assert [main.parse_line(x) for x in lines if main.parse_line(x)] == \
           [main.parse_line(x) for x in plain if main.parse_line(x)]


# ------------------------------------------------------------------ main loop
def _lines_with_dial():
    return [
        '{"type":"status","state":"mode","round_id":1,"accel":"none"}',
        dial_line(10), dial_line(40), dial_line(80),
        '{"type":"status","state":"locked","claim":80}',
        '{"type":"result","round_id":1,"seq":1,"claim":80,"actual":300,"unit":"ms",'
        '"false_start":false,"timeout":false}',
        '{"type":"status","state":"ready"}',
        dial_line(80), dial_line(20),
    ]


def _console(monkeypatch, tmp_path, capsys, lines, name):
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    assert main.main(["--mock", "--no-audio", "--db", str(tmp_path / f"{name}.db")]) == 0
    out, err = capsys.readouterr()
    keep = [ln for ln in (out + err).splitlines() if "session" not in ln and ".db" not in ln]
    return keep


def test_dial_lines_are_silent_without_ui(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    with_dial = _console(monkeypatch, tmp_path, capsys, _lines_with_dial(), "a")
    without = _console(monkeypatch, tmp_path, capsys,
                       [ln for ln in _lines_with_dial() if main.parse_dial(ln) is None], "b")
    assert with_dial == without                      # the dial adds nothing to the terminal
    assert any("claim 80" in ln for ln in with_dial)


def test_dial_lines_reach_the_ui(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(_lines_with_dial()))
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    seen = []
    real = ui_server.GameState.dial

    def spy(self, value):
        real(self, value)
        seen.append((value, self.snapshot()["liveClaim"]))

    monkeypatch.setattr(ui_server.GameState, "dial", spy)
    main.main(["--mock", "--no-audio", "--db", str(tmp_path / "s.db"),
               "--ui", "--ui-host", "127.0.0.1", "--ui-port", "0"])
    assert [v for v, _ in seen] == [10, 40, 80, 80, 20]
    assert [c for _, c in seen[:3]] == [10, 40, 80]


def test_calibrate_ignores_dial_lines(monkeypatch, capsys):
    lines = [
        '{"type":"status","state":"mode","round_id":2,"accel":"LIS3DH@0x19"}',
        dial_line(30), dial_line(35),
        '{"type":"status","state":"locked","claim":35}',
        '{"type":"result","round_id":2,"seq":1,"claim":35,"actual":50.0,"unit":"mg_rms",'
        '"peak":120.0,"samples":500,"false_start":false,"timeout":false}',
        dial_line(36),
    ]
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    assert main.main(["--mock", "--calibrate", "--ui", "--legacy-rounds", "--round", "2"]) == 0
    out, err = capsys.readouterr()
    assert "calib #1" in out and "1 hold(s)" in out
    assert '"dial"' not in out + err and "ignoring" not in out + err
    assert "(--ui is not used with --calibrate; ignored)" in out


def test_mock_ui_passes_dial_step_only_with_ui(monkeypatch, tmp_path):
    calls = []

    def fake_mock(*args, **kwargs):
        calls.append(kwargs)
        return iter([])

    monkeypatch.setattr(main, "mock_lines", fake_mock)
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    main.main(["--mock", "--db", str(tmp_path / "a.db")])
    main.main(["--mock", "--db", str(tmp_path / "a.db"), "--ui", "--ui-host", "127.0.0.1", "--ui-port", "0"])
    assert calls == [{}, {"dial_step_s": config.UI_MOCK_DIAL_STEP_S}]


# ------------------------------------------------------------------ Round 5 (Poker Face)
def test_poker_claim_parser_ignores_dial_lines():
    from poker_round import parse_claim
    assert parse_claim(dial_line(57)) is None
    assert main.parse_dial('{"type":"claim","round_id":5,"seq":1,"claim":72}') is None


def test_plain_poker_mock_has_no_dial_lines():
    lines = list(main.mock_lines(4, 3, 0, 5))
    assert not any(main.parse_dial(ln) is not None for ln in lines)


def test_poker_mock_with_dial_turns_to_the_claim():
    from poker_round import parse_claim
    lines = list(main.mock_lines(3, 3, 0, 5, dial_step_s=0))
    plain = list(main.mock_lines(3, 3, 0, 5))
    last = None
    claims = []
    for ln in lines:
        d = main.parse_dial(ln)
        if d is not None:
            last = d
        c = parse_claim(ln)
        if c is not None:
            assert c["claim"] == last
            claims.append(c["claim"])
    assert claims == [parse_claim(x)["claim"] for x in plain if parse_claim(x)]


def test_poker_armed_dial_then_claim_line(clock):
    s = GameState(clock=clock)
    s.session_started("Saim", 5, "sess")
    s.on_status({"type": "status", "state": "mode", "round_id": 5})
    s.dial(66)
    assert s.snapshot()["activeRound"]["round_id"] == "poker_face"
    assert s.snapshot()["liveClaim"] == 66
    s.on_status({"type": "status", "state": "locked", "claim": 67})
    s.claim_locked(5, 67)
    snap = s.snapshot()
    assert snap["screen"] == "performing" and snap["liveClaim"] == 67


def test_poker_calibrate_ignores_dial_lines(monkeypatch, capsys):
    lines = [
        '{"type":"status","state":"mode","round_id":5,"accel":"none"}',
        dial_line(40), dial_line(70),
        '{"type":"status","state":"locked","claim":70}',
        '{"type":"claim","round_id":5,"seq":1,"claim":70}',
        dial_line(71),
    ]
    monkeypatch.setattr(main, "mock_lines", lambda *a, **k: iter(lines))
    assert main.main(["--mock", "--round", "5", "--calibrate", "--no-audio"]) == 0
    out, err = capsys.readouterr()
    assert '"dial"' not in out + err and "ignoring" not in out + err
