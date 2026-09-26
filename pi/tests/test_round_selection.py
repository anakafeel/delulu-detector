"""Pi -> Arduino round selection: the R1/R2 line, ack handling and resends."""
import itertools
import types

import pytest

import config
import main
from main import RoundSelector, selection_line

ACK_R2 = '{"type":"status","state":"mode","round_id":2,"accel":"LIS3DH@0x19"}\r\n'
ACK_R1 = '{"type":"status","state":"mode","round_id":1,"accel":"LIS3DH@0x19"}\r\n'
BOOT = '{"type":"status","state":"ready","accel":"LIS3DH@0x19"}\r\n'
READY = '{"type":"status","state":"ready"}\r\n'   # per-round ready (Round 1 format), not a boot


def test_selection_line_bytes():
    assert selection_line(1) == b"R1\n"
    assert selection_line(2) == b"R2\n"
    assert selection_line(5) == b"R5\n"
    with pytest.raises(ValueError):
        selection_line(3)                          # Round 3 is parked
    with pytest.raises(ValueError):
        selection_line(4)


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _selector(round_id=2, **kw):
    clock = _Clock()
    return RoundSelector(round_id, ack_timeout_s=3.0, max_sends=3, clock=clock, **kw), clock


def test_ack_stops_resends():
    sel, clock = _selector()
    assert sel.start() == b"R2\n"
    assert sel.on_line(ACK_R2) is None and sel.acked
    clock.t += 60
    assert sel.on_idle() is None


def test_no_ack_resends_after_timeout_then_gives_up(capsys):
    sel, clock = _selector()
    sel.start()
    clock.t += 2.9
    assert sel.on_idle() is None                   # still within the ack timeout
    clock.t += 0.2
    assert sel.on_idle() == b"R2\n"                # send #2
    clock.t += 3.0
    assert sel.on_idle() == b"R2\n"                # send #3 (max)
    clock.t += 3.0
    assert sel.on_idle() is None                   # gave up
    assert "never acknowledged 'R2'" in capsys.readouterr().err
    clock.t += 3.0
    assert sel.on_idle() is None


def test_boot_banner_means_reset_so_selection_is_resent():
    sel, clock = _selector()
    sel.start()
    sel.on_line(ACK_R2)
    assert sel.on_line(BOOT) == b"R2\n"            # board rebooted into Round 1
    assert not sel.acked
    assert sel.on_line(ACK_R2) is None and sel.acked


def test_per_round_ready_and_other_lines_do_not_trigger_a_resend():
    sel, _ = _selector()
    sel.start()
    for line in (READY, '{"type":"status","state":"hold"}\n',
                 '{"type":"result","round_id":2,"claim":1,"actual":9.0}\n', "boot noise\n"):
        assert sel.on_line(line) is None


def test_ack_for_the_wrong_round_is_corrected():
    sel, _ = _selector()
    sel.start()
    assert sel.on_line(ACK_R1) == b"R2\n"
    assert not sel.acked


class _FakeSerialPort:
    def __init__(self, lines):
        self.lines = [ln.encode() for ln in lines]
        self.writes = []
        self.reset_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def reset_input_buffer(self):
        self.reset_calls += 1

    def write(self, data):
        self.writes.append(bytes(data))

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def _fake_serial_module(port):
    class SerialException(Exception):
        pass

    return types.SimpleNamespace(Serial=lambda *a, **k: port, SerialException=SerialException)


@pytest.mark.parametrize("round_id", [1, 2])
def test_serial_lines_writes_the_selection_on_connect(monkeypatch, round_id):
    monkeypatch.setattr(config, "SERIAL_OPEN_SETTLE_S", 0)
    ack = ACK_R2 if round_id == 2 else ACK_R1
    port = _FakeSerialPort([ack, '{"type":"result","round_id":%d,"claim":5,"actual":9}\n' % round_id])
    gen = main.serial_lines("/dev/fake", 115200, round_id, serial_module=_fake_serial_module(port))
    got = list(itertools.islice(gen, 2))
    assert port.reset_calls == 1                   # stale boot output dropped before selecting
    assert port.writes == [f"R{round_id}\n".encode()]
    assert got[0].startswith('{"type":"status","state":"mode"')


def test_serial_lines_reselects_after_a_board_reset(monkeypatch):
    monkeypatch.setattr(config, "SERIAL_OPEN_SETTLE_S", 0)
    port = _FakeSerialPort([ACK_R2, BOOT, ACK_R2])
    gen = main.serial_lines("/dev/fake", 115200, 2, serial_module=_fake_serial_module(port))
    list(itertools.islice(gen, 3))
    assert port.writes == [b"R2\n", b"R2\n"]


def test_default_round_is_1():
    assert config.DEFAULT_ROUND == 1


# --------------------------------------------------------------- Round 5
ACK_R5 = '{"type":"status","state":"mode","round_id":5,"accel":"none"}\r\n'


def test_window_line():
    from poker_round import window_line
    assert window_line(6.0) == b"W6000\n"
    assert window_line(1) == b"W1000\n" and window_line(30) == b"W30000\n"
    assert window_line() == f"W{int(config.POKER_WINDOW_S * 1000)}\n".encode()
    for bad in (0.5, 31, -1):
        with pytest.raises(ValueError):
            window_line(bad)


def test_followup_is_sent_once_per_ack():
    sel, clock = _selector(5, followup=b"W6000\n")
    assert sel.start() == b"R5\n"
    assert sel.on_line(ACK_R5) == b"W6000\n" and sel.acked
    assert sel.on_line(ACK_R5) is None             # duplicate ack: no second W
    assert sel.on_line(BOOT) == b"R5\n"            # board reset
    assert sel.on_line(ACK_R5) == b"W6000\n"       # window re-sent after the new ack
    clock.t += 60
    assert sel.on_idle() is None


def test_rounds_1_and_2_have_no_followup():
    for rid, ack in ((1, ACK_R1), (2, ACK_R2)):
        sel, _ = _selector(rid)
        sel.start()
        assert sel.on_line(ack) is None


def test_serial_lines_round_5_selects_and_sets_the_window(monkeypatch):
    monkeypatch.setattr(config, "SERIAL_OPEN_SETTLE_S", 0)
    monkeypatch.setattr(config, "POKER_WINDOW_S", 4.5)
    claim = '{"type":"claim","round_id":5,"seq":1,"claim":72}\n'
    port = _FakeSerialPort([ACK_R5, '{"type":"status","state":"window","window_ms":4500}\n', claim,
                            BOOT, ACK_R5])
    gen = main.serial_lines("/dev/fake", 115200, 5, serial_module=_fake_serial_module(port))
    got = list(itertools.islice(gen, 5))
    assert port.writes == [b"R5\n", b"W4500\n", b"R5\n", b"W4500\n"]
    assert got[2] == claim


def test_round_flag_accepts_5_and_rejects_3():
    with pytest.raises(SystemExit):
        main.main(["--mock", "--round", "3"])
