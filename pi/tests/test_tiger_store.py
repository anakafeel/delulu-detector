"""Tiger Data mirror: never breaks a round; curve/leaderboard endpoints. Live SQL only with TIGER_TEST_URL."""
import http.client
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import config
import tiger_store as t
from scoring import score_composure_round, score_reflex_round
from ui_server import GameState, UIServer


def test_row_for_maps_a_scored_round_and_skips_unscored():
    r = score_composure_round(5, 80, 55.0)
    ts = datetime.now(timezone.utc)
    row = t.row_for(r, "Ada", "20260927-010203-abcdef", 2, ts)
    assert row == (ts, t.session_uuid("20260927-010203-abcdef"), "Ada", 2, 5, 80.0, 55.0, None, None, 25.0)
    assert t.row_for(score_reflex_round(70, None, false_start=True), "Ada", "s", 1, ts) is None


def test_session_uuid_is_stable_per_session():
    assert t.session_uuid("a") == t.session_uuid("a") != t.session_uuid("b")
    assert isinstance(t.session_uuid("a"), uuid.UUID)


def test_writer_swallows_every_failure(capsys):
    def boom():
        raise t.TigerError("down")
    w = t.TigerWriter(connect_fn=boom).start()
    for _ in range(3):
        w.submit(("row",))
    w.submit(None)                                   # unscored rounds are ignored
    w.close()
    assert w.written == 0
    assert capsys.readouterr().err.count("[tiger]") == 1     # reported once


class FakeReader:
    def curve(self, player):
        return [{"round_number": 1, "avg_gap": 30.0, "rounds": 2}]

    def leaderboard(self, limit=10):
        return [{"player": "Ada", "avg_gap": 12.5, "rounds": 4, "best_gap": 3.0, "worst_gap": 30.0}]


def _get(srv, path):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


@pytest.mark.parametrize("reader,expect", [(None, 503), (FakeReader(), 200)])
def test_tiger_endpoints(tmp_path, reader, expect):
    srv = UIServer(GameState(), host="127.0.0.1", port=0, static_dir=tmp_path, tiger=reader)
    assert srv.start()
    try:
        status, body = _get(srv, "/api/tiger/curve?player=Ada")
        assert status == expect
        assert _get(srv, "/api/tiger/leaderboard")[0] == expect
        if reader is not None:
            assert json.loads(body)["curve"][0]["avg_gap"] == 30.0
            assert _get(srv, "/api/tiger/curve")[0] == 400
    finally:
        srv.stop()


LIVE_URL = os.environ.get("TIGER_TEST_URL")


@pytest.mark.skipif(not LIVE_URL, reason="set TIGER_TEST_URL to a scratch Timescale database")
def test_live_schema_insert_curve_and_leaderboard(monkeypatch):
    monkeypatch.setattr(config, "TIGER_DATA_URL", LIVE_URL)
    player = f"test-{uuid.uuid4().hex[:8]}"
    conn = t.connect()
    t.ensure_schema(conn)
    t.ensure_schema(conn)                            # idempotent
    now = datetime.now(timezone.utc)
    w = t.TigerWriter().start()
    for sess, gaps in (("s1", [(90, 40), (70, 60)]), ("s2", [(80, 50)])):
        for i, (claim, comp) in enumerate(gaps, start=1):
            w.submit(t.row_for(score_composure_round(5, claim, comp), player, sess, i, now - timedelta(minutes=5 - i)))
    w.close()
    assert w.written == 3
    reader = t.TigerReader()
    assert reader.curve(player) == [{"round_number": 1, "avg_gap": 40.0, "rounds": 2},
                                     {"round_number": 2, "avg_gap": 10.0, "rounds": 1}]
    assert any(r["player"] == player and r["rounds"] == 3 for r in reader.leaderboard(limit=1000))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM round_events WHERE player_id = %s", (player,))


def test_reader_backs_off_after_a_failure():
    calls = []
    now = [100.0]

    def down():
        calls.append(1)
        raise t.TigerError("unreachable")
    reader = t.TigerReader(connect_fn=down, backoff_s=30, clock=lambda: now[0])
    for _ in range(3):
        with pytest.raises(t.TigerError):
            reader.curve("Ada")
    assert len(calls) == 1                           # the 2nd and 3rd answered at once
    now[0] += 31
    with pytest.raises(t.TigerError):
        reader.curve("Ada")
    assert len(calls) == 2
