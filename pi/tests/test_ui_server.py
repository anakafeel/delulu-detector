"""Browser UI bridge: state transitions, crash safety, HTTP/SSE server, main.py hooks."""
import http.client
import json
import socket

import pytest

import config
import main
import ui_server
from scoring import score_reflex_round, score_steady_round
from session_log import SessionLog
from ui_server import GameState, UIServer


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state(clock):
    s = GameState(clock=clock, reveal_hold_s=10, idle_after_s=60, history_limit=50)
    s.session_started("Saim", 1, "sess-1")
    return s


def status(state_name, **extra):
    return {"type": "status", "state": state_name, **extra}


# ------------------------------------------------------------------ transitions
def test_starts_idle_with_frontend_shape(state):
    snap = state.snapshot()
    assert snap["screen"] == "idle"
    for key in ("player", "activeRound", "liveClaim", "latestResult", "history"):
        assert key in snap
    assert snap["player"] == "Saim"
    assert snap["history"] == []
    assert snap["selectedRound"] == {"round_id": "reflex", "round_type_id": 1, "round_name": "Reflex",
                                   "round_label": 1}
    json.dumps(snap, allow_nan=False)


def test_mode_ack_arms_the_round(state):
    state.on_status(status("mode", round_id=1, accel="none"))
    snap = state.snapshot()
    assert snap["screen"] == "predicting"
    assert snap["activeRound"]["round_id"] == "reflex"
    assert snap["liveClaim"] is None
    assert snap["board"] == {"armed": True, "stage": "mode"}


def test_mode_ack_for_another_round_is_not_armed(state):
    state.on_status(status("mode", round_id=2, accel="none"))
    assert state.snapshot()["board"]["armed"] is False


@pytest.mark.parametrize("stage", ["locked", "cue", "countdown", "hold", "false_start"])
def test_round_activity_means_performing(state, stage):
    state.on_status(status("mode", round_id=1))
    state.on_status(status(stage))
    snap = state.snapshot()
    assert snap["screen"] == "performing"
    assert snap["board"]["stage"] == stage
    assert snap["activeRound"]["round_id"] == "reflex"


def test_claim_locked_shows_the_claim(clock):
    s = GameState(clock=clock)
    s.session_started("Saim", 5, "sess")
    s.on_status(status("locked"))
    s.claim_locked(5, 72.0)
    snap = s.snapshot()
    assert snap["screen"] == "performing"
    assert snap["liveClaim"] == 72
    assert snap["activeRound"]["round_id"] == "poker_face"


def test_result_reveal_then_verdict_then_back_to_predicting(state, clock, tmp_path):
    state.on_status(status("mode", round_id=1))
    state.on_status(status("locked"))
    result = score_reflex_round(80, 300)
    with SessionLog(tmp_path / "s.db") as log:
        n = log.log_round("sess-1", "Saim", result)
        state.round_result(result, "Saim", "sess-1", n, log)
    snap = state.snapshot()
    assert snap["screen"] == "reveal"
    r = snap["latestResult"]
    assert r["round_id"] == "reflex-1" and r["round_key"] == "reflex" and r["round_type_id"] == 1
    assert r["claim"] == 80 and r["actual"] == pytest.approx(result.performance)
    assert r["actual_raw"] == 300 and r["actual_unit"] == "ms"
    assert r["gap"] == pytest.approx(result.gap) and r["score"] == result.score
    assert r["tier"] == result.tier and r["direction"] == "over"
    assert r["player"] == "Saim" and r["scored"] is True and r["verdict_text"] is None
    assert snap["liveClaim"] == 80
    assert len(snap["history"]) == 1 and snap["history"][0]["round_id"] == "reflex-1"
    assert snap["leaderboard"][0]["player"] == "Saim"

    state.verdict_text("Delulu is not the solulu.")
    snap = state.snapshot()
    assert snap["latestResult"]["verdict_text"] == "Delulu is not the solulu."
    assert snap["history"][0]["verdict_text"] == "Delulu is not the solulu."

    state.on_status(status("ready"))           # arrives right after the result: reveal stays
    assert state.snapshot()["screen"] == "reveal"
    clock.t += 10.5                            # reveal hold over
    assert state.snapshot()["screen"] == "predicting"
    clock.t += 61                              # nobody playing -> attract screen
    assert state.snapshot()["screen"] == "idle"


def test_next_round_ends_the_reveal_early(state):
    state.on_status(status("mode", round_id=1))
    state.round_result(score_reflex_round(50, 300), "Saim", "sess-1", 1)
    state.on_status(status("locked"))
    assert state.snapshot()["screen"] == "performing"
    assert state.snapshot()["liveClaim"] is None     # R1/R2 claims only arrive with the result


def test_predicting_times_out_to_idle(state, clock):
    state.on_status(status("mode", round_id=1))
    clock.t += 59
    assert state.snapshot()["screen"] == "predicting"
    clock.t += 2
    assert state.snapshot()["screen"] == "idle"


def test_false_start_result_has_no_gap(state):
    result = score_reflex_round(90, None, false_start=True)
    state.round_result(result, "Saim", "sess-1", 1)
    r = state.snapshot()["latestResult"]
    assert r["false_start"] is True and r["scored"] is False
    assert r["gap"] is None and r["actual"] is None and r["score"] == 0
    json.dumps(state.snapshot(), allow_nan=False)


def test_steady_result_keeps_raw_mg_and_extras(state):
    result = score_steady_round(60, 40.0, peak_mg=120.5, samples=500)
    state.round_result(result, "Saim", "sess-1", 1)
    r = state.snapshot()["latestResult"]
    assert r["round_key"] == "steady_hands" and r["actual_unit"] == "mg_rms"
    assert r["actual_raw"] == 40.0 and r["extra"] == {"peak": 120.5, "samples": 500}


def test_rejected_round_shows_a_notice_and_rearms(state):
    state.on_status(status("mode", round_id=1))
    state.on_status(status("locked"))
    state.round_rejected("Sensor error (no_accel)")
    snap = state.snapshot()
    assert snap["screen"] == "predicting"
    assert snap["notice"]["message"] == "Sensor error (no_accel)"
    state.on_status(status("locked"))
    assert state.snapshot()["notice"] is None


def test_boot_banner_goes_idle_until_the_mode_ack(state):
    state.on_status(status("mode", round_id=1))
    state.on_status(status("ready", accel="none"))
    snap = state.snapshot()
    assert snap["screen"] == "idle" and snap["board"] == {"armed": False, "stage": "booting"}
    state.on_status(status("mode", round_id=1))
    assert state.snapshot()["screen"] == "predicting"


def test_performing_then_ready_without_result_returns_to_predicting(state):
    state.on_status(status("mode", round_id=1))
    state.on_status(status("locked"))
    state.on_status(status("ready"))
    assert state.snapshot()["screen"] == "predicting"


def test_history_comes_from_sqlite_with_limit(clock, tmp_path):
    with SessionLog(tmp_path / "s.db") as log:
        for i in range(5):
            log.log_round("old", "Alex", score_reflex_round(50 + i, 300))
        s = GameState(clock=clock, history_limit=3)
        s.refresh_from_log(log)
    snap = s.snapshot()
    assert [h["round_id"] for h in snap["history"]] == ["reflex-3", "reflex-4", "reflex-5"]
    assert snap["leaderboard"][0]["total_rounds"] == 5    # leaderboard covers everything
    assert snap["mostDelulu"]["player"] == "Alex"


def test_sqlite_trouble_keeps_the_round_on_screen(state, capsys):
    class BrokenLog:
        def rounds(self):
            raise RuntimeError("database is locked")

    state.round_result(score_reflex_round(50, 300), "Saim", "sess-1", 1, BrokenLog())
    snap = state.snapshot()
    assert snap["screen"] == "reveal" and len(snap["history"]) == 1
    assert "[ui]" in capsys.readouterr().err


def test_event_methods_never_raise(state, capsys):
    state.on_status(None)                          # garbage in
    state.round_result(object(), "p", "s", 1)
    state.claim_locked(5, "not a number")
    state.round_result(object(), "p", "s", 2)      # same failure reported only once
    err = capsys.readouterr().err
    assert err.count("round_result failed") == 1
    json.dumps(state.snapshot())


def test_version_bumps_on_change_only(state):
    v = state.snapshot()["version"]
    state.on_status(status("mode", round_id=1))
    assert state.snapshot()["version"] == v + 1
    state.on_status(status("something_unknown"))
    assert state.snapshot()["version"] == v + 1


def test_next_event_returns_new_state_or_none(state):
    kind, data, cursor = state.next_event(None, 0.1)
    assert kind == "state" and data == state.snapshot_json()
    assert state.next_event(cursor, 0.05) is None
    state.on_status(status("mode", round_id=1))
    kind, data, cursor = state.next_event(cursor, 0.5)
    assert kind == "state" and json.loads(data)["screen"] == "predicting"


def test_next_event_sends_knob_turns_as_small_dial_events(state):
    state.on_status(status("mode", round_id=1))
    _, _, cursor = state.next_event(None, 0.1)
    state.dial(41)
    kind, data, cursor = state.next_event(cursor, 0.5)
    assert kind == "dial" and json.loads(data) == {"liveClaim": 41}
    assert state.next_event(cursor, 0.05) is None
    state.on_status(status("locked", claim=41))     # a real change: the full state again
    kind, data, _ = state.next_event(cursor, 0.5)
    assert kind == "state" and json.loads(data)["screen"] == "performing"


def test_next_event_catches_time_based_screen_changes(state, clock):
    state.on_status(status("mode", round_id=1))
    _, _, cursor = state.next_event(None, 0.1)
    clock.t += 61                                    # idle timeout, no event method called
    kind, data, _ = state.next_event(cursor, 0.1)
    assert kind == "state" and json.loads(data)["screen"] == "idle"


# ------------------------------------------------------------------------ HTTP
@pytest.fixture
def server(state, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>delulu app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    srv = UIServer(state, host="127.0.0.1", port=0, static_dir=dist)
    assert srv.start()
    yield srv
    srv.stop()


def get(srv, path, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request(method, path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


def test_api_state_json_with_cors(server, state):
    resp, body = get(server, "/api/state")
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "application/json"
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert json.loads(body)["screen"] == "idle"
    state.on_status(status("mode", round_id=1))
    assert json.loads(get(server, "/api/state")[1])["screen"] == "predicting"


def test_options_preflight_and_health(server):
    resp, _ = get(server, "/api/state", method="OPTIONS")
    assert resp.status == 204 and resp.getheader("Access-Control-Allow-Origin") == "*"
    assert json.loads(get(server, "/api/health")[1]) == {"ok": True}
    assert get(server, "/api/nope")[0].status == 404


def test_serves_the_built_frontend(server):
    resp, body = get(server, "/")
    assert resp.status == 200 and b"delulu app" in body
    assert resp.getheader("Content-Type").startswith("text/html")
    resp, body = get(server, "/assets/app.js")
    assert resp.status == 200 and body == b"console.log(1)"
    assert get(server, "/some/app/route")[1] == b"<html>delulu app</html>"   # SPA fallback
    assert get(server, "/assets/missing.js")[0].status == 404
    assert get(server, "/../secret.txt")[0].status in (400, 404)
    assert b"nope" not in get(server, "/%2e%2e/secret.txt")[1]


def test_without_dist_shows_instructions(state, tmp_path):
    srv = UIServer(state, host="127.0.0.1", port=0, static_dir=tmp_path / "missing")
    assert srv.start()
    try:
        resp, body = get(srv, "/")
        assert resp.status == 200 and b"npm run build" in body
        assert srv.serving_frontend is False
    finally:
        srv.stop()


def _read_sse(fp):
    """One SSE event -> (event name or None, raw data str)."""
    data, name = [], None
    while True:
        line = fp.readline()
        if not line:
            raise EOFError
        line = line.decode().rstrip("\r\n")
        if line.startswith("data: "):
            data.append(line[6:])
        elif line.startswith("event: "):
            name = line[7:]
        elif line == "" and data:
            return name, "\n".join(data)


def _read_sse_event(fp):
    name, data = _read_sse(fp)
    assert name is None                              # a full-state message
    return json.loads(data)


def test_sse_pushes_state_on_every_change(server, state):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/events")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"
    assert _read_sse_event(resp)["screen"] == "idle"
    state.on_status(status("mode", round_id=1))
    assert _read_sse_event(resp)["screen"] == "predicting"
    state.on_status(status("locked"))
    assert _read_sse_event(resp)["screen"] == "performing"
    conn.close()


def test_sse_dial_updates_do_not_resend_history(server, state, clock):
    for n in range(1, 31):                           # a real-sized history
        state.round_result(score_reflex_round(50 + n % 40, 250 + n), "Saim", "sess-1", n)
    state.on_status(status("ready"))
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/events")
    resp = conn.getresponse()
    first = _read_sse_event(resp)
    assert len(first["history"]) == 30 and first["screen"] == "reveal"
    clock.t += 11                                    # past the reveal hold: claim screen
    assert _read_sse_event(resp)["screen"] == "predicting"
    state.dial(39)                                   # first turn after a reveal: phase change, full state
    assert _read_sse_event(resp)["liveClaim"] == 39
    sizes = []
    for v in (40, 41, 42, 43):
        state.dial(v)
        name, data = _read_sse(resp)
        assert name == "dial" and json.loads(data) == {"liveClaim": v}
        assert "history" not in data and "leaderboard" not in data
        sizes.append(len(data))
    assert max(sizes) < 40                           # vs. the full state
    full = state.snapshot()
    assert full["liveClaim"] == 43 and len(full["history"]) == 30   # /api/state stays complete
    state.on_status(status("locked", claim=43))
    snap = _read_sse_event(resp)
    assert snap["screen"] == "performing" and len(snap["history"]) == 30
    conn.close()


def test_api_state_includes_the_live_dial(server, state):
    state.on_status(status("mode", round_id=1))
    state.dial(64)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/state")
    body = json.loads(conn.getresponse().read())
    assert body["liveClaim"] == 64 and "history" in body and "leaderboard" in body
    conn.close()


def test_port_in_use_does_not_raise(state, capsys):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        srv = UIServer(state, host="127.0.0.1", port=blocker.getsockname()[1])
        assert srv.start() is False
        srv.stop()                                   # harmless
    finally:
        blocker.close()
    assert "could not start the UI server" in capsys.readouterr().err


# ------------------------------------------------------------- main.py hooks
class RecordingUI:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.events.append((name, args))
        return record


def test_process_reading_feeds_result_and_verdict(monkeypatch, tmp_path):
    seen = {}

    def fake_verdict(result, player, play=True, on_text=None):
        on_text("nice try")
        seen["played"] = play

    monkeypatch.setattr(main, "deliver_verdict", fake_verdict)
    ui = RecordingUI()
    with SessionLog(tmp_path / "s.db") as log:
        reading = main.parse_line('{"type":"result","round_id":1,"claim":50,"actual":300}')
        assert main.process_reading(reading, "p", "s", log, play_audio=False, ui=ui) is True
    names = [e[0] for e in ui.events]
    assert names == ["round_result", "verdict_text"]
    assert ui.events[1][1] == ("nice try",)


def test_real_ui_state_through_process_reading(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "deliver_verdict",
                        lambda result, player, play=True, on_text=None: on_text("line"))
    ui = GameState()
    ui.session_started("p", 1, "s")
    with SessionLog(tmp_path / "s.db") as log:
        reading = main.parse_line('{"type":"result","round_id":1,"claim":50,"actual":300}')
        assert main.process_reading(reading, "p", "s", log, play_audio=False, ui=ui) is True
    r = ui.snapshot()["latestResult"]
    assert r["round_id"] == "reflex-1" and r["verdict_text"] == "line"


def test_main_mock_with_ui_updates_state_and_serves(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    captured = {}
    real_start = main.start_ui

    def spy_start(args, session_id, log):
        st, srv = real_start(args, session_id, log)
        captured["state"], captured["srv"] = st, srv
        return st, srv

    def fake_linger(srv):
        resp, body = get(srv, "/api/state")
        captured["http"] = json.loads(body)

    monkeypatch.setattr(main, "start_ui", spy_start)
    monkeypatch.setattr(main, "linger_for_ui", fake_linger)
    rc = main.main(["--mock", "--rounds", "3", "--seed", "1", "--mock-delay", "0", "--no-audio",
                    "--db", str(tmp_path / "s.db"), "--ui", "--ui-host", "127.0.0.1", "--ui-port", "0"])
    assert rc == 0
    snap = captured["http"]
    assert snap["source"] == "mock" and snap["player"] == "player1"
    assert snap["screen"] == "reveal"
    assert len(snap["history"]) == 3
    assert snap["latestResult"]["round_id"] == "reflex-3"
    assert captured["srv"].httpd is None                 # stopped on the way out


def test_main_mock_steady_sensor_error_reaches_the_ui(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    rejected = []
    monkeypatch.setattr(ui_server.GameState, "round_rejected",
                        lambda self, msg: rejected.append(msg))
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    # seed 1 on Round 2 includes an accelerometer hiccup (error result) within 4 rounds
    main.main(["--mock", "--legacy-rounds", "--round", "2", "--rounds", "4", "--seed", "1", "--mock-delay", "0",
               "--no-audio", "--db", str(tmp_path / "s.db"), "--ui", "--ui-host", "127.0.0.1",
               "--ui-port", "0"])
    assert rejected and all("accel_read" in m for m in rejected)


def test_main_without_ui_starts_no_server(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "deliver_verdict", lambda result, player, play=True: None)
    monkeypatch.setattr(ui_server.UIServer, "start",
                        lambda self: pytest.fail("server started without --ui"))
    assert main.main(["--mock", "--rounds", "1", "--mock-delay", "0", "--no-audio",
                      "--db", str(tmp_path / "s.db")]) == 0


# ------------------------------------------------------------- Round 5 (Poker Face)
def test_main_mock_poker_face_shows_claim_then_smile_result(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_server.GameState, "player_named", lambda self: True)   # name typed
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    claims, results = [], []
    real_claim, real_result = ui_server.GameState.claim_locked, ui_server.GameState.round_result

    def spy_claim(self, round_id, claim):
        real_claim(self, round_id, claim)
        claims.append(self.snapshot())

    def spy_result(self, *a, **k):
        real_result(self, *a, **k)
        results.append(self.snapshot())

    monkeypatch.setattr(ui_server.GameState, "claim_locked", spy_claim)
    monkeypatch.setattr(ui_server.GameState, "round_result", spy_result)
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    assert main.main(["--mock", "--round", "5", "--rounds", "2", "--seed", "3", "--mock-delay", "0",
                      "--no-audio", "--db", str(tmp_path / "s.db"), "--ui", "--ui-host", "127.0.0.1",
                      "--ui-port", "0"]) == 0
    assert claims and claims[0]["screen"] == "performing"
    assert claims[0]["activeRound"]["round_id"] == "poker_face"
    assert isinstance(claims[0]["liveClaim"], int)
    assert results, "no Round 5 result reached the UI"
    r = results[-1]["latestResult"]
    assert r["round_key"] == "poker_face" and r["round_type_id"] == 5
    assert r["actual_unit"] == "smile_pct" and 0 <= r["actual_raw"] <= 100
    assert results[-1]["screen"] == "reveal"


def test_poker_vision_failure_reaches_the_ui_as_a_notice(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_server.GameState, "player_named", lambda self: True)   # name typed
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    monkeypatch.setattr(main, "run_face_claim", lambda claim, poker, selected: None)
    rejected = []
    monkeypatch.setattr(ui_server.GameState, "round_rejected", lambda self, msg: rejected.append(msg))
    main.main(["--mock", "--round", "5", "--rounds", "1", "--mock-delay", "0", "--no-audio",
               "--db", str(tmp_path / "s.db"), "--ui", "--ui-host", "127.0.0.1", "--ui-port", "0"])
    assert rejected and "Camera / vision error" in rejected[0]


# ------------------------------------------------------------- Poker Face name entry
@pytest.mark.parametrize("raw,expected", [
    ("  Ada  ", "Ada"), ("Ada\nLovelace", "Ada Lovelace"), ("x" * 40, "x" * config.UI_PLAYER_NAME_MAX),
    ("", None), ("   ", None), ("\t\x00", None), (None, None), (42, None),
])
def test_clean_player_name(raw, expected):
    assert ui_server.clean_player_name(raw) == expected


def test_typed_name_is_the_round_player_until_the_rig_goes_idle(clock):
    s = GameState(clock=clock, reveal_hold_s=10, idle_after_s=60)
    s.session_started("Guest", 5, "sess", name_entry=True)
    snap = s.snapshot()
    assert snap["nameEntry"] is True and snap["player"] == "Guest" and snap["playerNamed"] is False
    assert s.set_player("  Ada ") == "Ada"
    assert s.round_player() == "Ada" and s.snapshot()["playerNamed"] is True
    s.on_status(status("mode", round_id=5))
    clock.t += 50
    s.dial(40)                                   # still playing: the name stays
    clock.t += 59
    assert s.round_player() == "Ada"
    clock.t += 2                                 # idle timeout, attract screen: the next person
    assert s.snapshot()["screen"] == "idle"
    assert s.round_player() == "Guest" and s.snapshot()["playerNamed"] is False
    assert s.set_player("") is None and s.round_player() == "Guest"


def post_json(srv, path, payload):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def test_post_player_sets_the_name(server, state):
    resp, body = post_json(server, "/api/player", {"name": " Grace  Hopper "})
    assert resp.status == 200 and json.loads(body) == {"ok": True, "player": "Grace Hopper"}
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert json.loads(get(server, "/api/state")[1])["player"] == "Grace Hopper"
    assert post_json(server, "/api/player", {"name": "  "})[0].status == 400
    assert post_json(server, "/api/player", b"not json")[0].status == 400
    assert post_json(server, "/api/player", {"name": "x" * 2000})[0].status == 400    # body too big
    assert post_json(server, "/api/nope", {"name": "a"})[0].status == 404
    assert state.round_player() == "Grace Hopper"


def test_main_poker_face_logs_the_typed_name(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    real_start = main.start_ui

    def start_and_type_a_name(args, session_id, log):
        st, srv = real_start(args, session_id, log)
        assert st.snapshot()["player"] == config.UI_DEFAULT_PLAYER and st.snapshot()["nameEntry"]
        st.set_player("Ada")
        return st, srv

    monkeypatch.setattr(main, "start_ui", start_and_type_a_name)
    db = tmp_path / "s.db"
    assert main.main(["--mock", "--round", "5", "--rounds", "2", "--seed", "3", "--mock-delay", "0",
                      "--no-audio", "--db", str(db), "--ui", "--ui-host", "127.0.0.1",
                      "--ui-port", "0"]) == 0
    with SessionLog(db) as log:
        assert {r["player"] for r in log.rounds()} == {"Ada"}
        assert [r["round_number"] for r in log.rounds()] == [1, 2]


def test_name_entry_is_poker_face_with_ui_only(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    db = tmp_path / "s.db"
    assert main.main(["--mock", "--round", "5", "--rounds", "2", "--seed", "3", "--mock-delay", "0",
                      "--no-audio", "--db", str(db)]) == 0
    with SessionLog(db) as log:
        assert {r["player"] for r in log.rounds()} == {"player1"}      # no --ui: unchanged


def test_typing_a_name_on_the_attract_screen_wakes_the_dial(clock):
    s = GameState(clock=clock, reveal_hold_s=10, idle_after_s=60)
    s.session_started("Guest", 5, "sess", name_entry=True)
    s.set_player("Early")                        # board not armed yet: stays on the attract screen
    assert s.snapshot()["screen"] == "idle"
    s.on_status(status("mode", round_id=5))
    clock.t += 61                                # idle again
    assert s.snapshot()["screen"] == "idle"
    s.set_player("Bo")
    snap = s.snapshot()
    assert snap["screen"] == "predicting" and snap["player"] == "Bo"
    assert snap["activeRound"]["round_id"] == "poker_face"


def test_poker_claim_before_a_name_is_refused_without_measuring(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UI_MOCK_PAUSE_S", 0)
    monkeypatch.setattr(config, "UI_MOCK_DIAL_STEP_S", 0)
    monkeypatch.setattr(main, "deliver_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "linger_for_ui", lambda srv: None)
    monkeypatch.setattr(main, "run_face_claim", lambda *a: pytest.fail("camera ran before a name"))
    rejected = []
    monkeypatch.setattr(ui_server.GameState, "round_rejected", lambda self, msg: rejected.append(msg))
    db = tmp_path / "s.db"
    assert main.main(["--mock", "--round", "5", "--rounds", "2", "--seed", "3", "--mock-delay", "0",
                      "--no-audio", "--db", str(db), "--ui", "--ui-host", "127.0.0.1",
                      "--ui-port", "0"]) == 0
    assert len(rejected) == 2 and all("Type your name first" in m for m in rejected)
    with SessionLog(db) as log:
        assert log.rounds() == []


def test_presage_sample_count_reaches_the_logged_extras():
    import poker_round
    from scoring import score_reading

    class FakeSession:
        last_sample_count = None

        def finish(self):
            self.last_sample_count = 41
            return 62.5

    reading = {"type": "result", "round_id": 5, "claim": 70.0, "actual": 10.0, "unit": "smile_pct",
               "frames": 90, "fps": 15.0, "face_frac": 1.0}
    reading = poker_round._apply_presage(FakeSession(), reading)
    result = score_reading(reading)
    assert result.actual == 62.5 and result.extra["presage_samples"] == 41
    assert ui_server.result_from_round(result, "Ada", "s", 1)["extra"]["presage_samples"] == 41


def test_cue_length_ack_at_boot_is_not_a_round(clock):
    s = GameState(clock=clock, reveal_hold_s=10, idle_after_s=60)
    s.session_started("Guest", 5, "sess", name_entry=True)
    s.on_status(status("mode", round_id=5))
    s.on_status(status("window", window_ms=6000))        # reply to W6000, sent right after the ack
    assert s.snapshot()["screen"] == "predicting"         # the dial, not the camera


# ------------------------------------------------------------- opt-in leaderboard photo
def test_photo_needs_a_yes_and_lives_in_memory_per_player(clock, tmp_path):
    s = GameState(clock=clock, reveal_hold_s=10, idle_after_s=60)
    s.session_started("Guest", 5, "sess", name_entry=True)
    s.set_player("Ada")                                  # no photo answer = no
    assert s.photo_ok() is False
    s.set_player("Ada", photo=True)
    assert s.photo_ok() is True
    s.store_photo("Ada", b"\xff\xd8one")
    s.store_photo("Ada", b"\xff\xd8two")                 # latest round wins
    assert s.photo("Ada") == b"\xff\xd8two" and s.snapshot()["photos"] == ["Ada"]
    s.set_player("Bo", photo=False)
    assert s.photo_ok() is False and s.photo("Bo") is None
    srv = UIServer(s, host="127.0.0.1", port=0, static_dir=tmp_path)
    assert srv.start()
    try:
        resp, body = get(srv, "/api/photo?player=Ada")
        assert resp.status == 200 and resp.getheader("Content-Type") == "image/jpeg" and body == b"\xff\xd8two"
        assert get(srv, "/api/photo?player=Bo")[0].status == 404
        r, _ = post_json(srv, "/api/player", {"name": "Cy", "photo": True})
        assert r.status == 200 and s.photo_ok() is True
    finally:
        srv.stop()


def test_photo_cap_drops_the_oldest(clock, monkeypatch):
    monkeypatch.setattr(config, "UI_PHOTO_MAX", 2)
    s = GameState(clock=clock)
    for name in ("a", "b", "c"):
        s.store_photo(name, b"x")
    assert s.snapshot()["photos"] == ["b", "c"]
