"""Presage bridge contract: real samples average, errors propagate, nothing is invented."""
import sys
import textwrap
import time

import numpy as np
import pytest

from presage_client import PresageError, PresageSession, pace_timestamp
from scoring import score_composure_round, score_reading


def _bridge(tmp_path, body: str):
    path = tmp_path / "bridge.py"
    path.write_text(textwrap.dedent(body))
    return [sys.executable, str(path)]


def test_timestamp_gap_stays_under_the_sdk_limit():
    assert pace_timestamp(None, 1_000) == 1_000
    assert pace_timestamp(1_000, 1_000) == 1_001
    assert pace_timestamp(1_000, 50_000) == 50_000
    # A 5s stall must not reach the SDK's 2s rejection line.
    assert pace_timestamp(1_000_000, 6_000_000) - 1_000_000 <= 1_000_000


def test_missing_key_raises_before_a_number(monkeypatch):
    monkeypatch.delenv("SMARTSPECTRA_API_KEY", raising=False)
    monkeypatch.delenv("PRESAGE_API_KEY", raising=False)
    session = PresageSession(ready_timeout_s=1)
    with pytest.raises(PresageError, match="SMARTSPECTRA_API_KEY"):
        session.start()


def test_sdk_error_is_not_turned_into_a_score(tmp_path):
    command = _bridge(tmp_path, """
        import json
        print(json.dumps({"type": "error", "message": "auth failed"}), flush=True)
    """)
    session = PresageSession(command=command, ready_timeout_s=2)
    with pytest.raises(PresageError, match="auth failed"):
        session.start()


def test_window_averages_only_real_samples(tmp_path):
    command = _bridge(tmp_path, """
        import json, sys, threading, time
        print(json.dumps({"type": "ready"}), flush=True)
        def drain():
            while sys.stdin.buffer.read(4096):
                pass
        threading.Thread(target=drain, daemon=True).start()
        print(json.dumps({"type": "sample", "composure": 40}), flush=True)
        print(json.dumps({"type": "sample", "composure": 80}), flush=True)
        time.sleep(30)
    """)
    session = PresageSession(command=command, ready_timeout_s=2)
    session.start()
    try:
        session.push(np.zeros((8, 8, 3), dtype=np.uint8))
        deadline = time.monotonic() + 2
        while session.latest() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert session.finish() == pytest.approx(60.0)
    finally:
        session.close()


def test_error_after_real_samples_keeps_those_samples(tmp_path):
    command = _bridge(tmp_path, """
        import json, time
        print(json.dumps({"type": "ready"}), flush=True)
        print(json.dumps({"type": "sample", "composure": 40}), flush=True)
        print(json.dumps({"type": "sample", "composure": 80}), flush=True)
        print(json.dumps({"type": "error", "code": 8, "message": "processing failed"}), flush=True)
        time.sleep(30)
    """)
    session = PresageSession(command=command, ready_timeout_s=2)
    session.start()
    try:
        deadline = time.monotonic() + 2
        while session.latest() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert session.finish() == pytest.approx(60.0)
        with pytest.raises(PresageError, match="no composure"):
            session.finish()
    finally:
        session.close()


def test_no_sample_raises(tmp_path):
    command = _bridge(tmp_path, """
        import json, time
        print(json.dumps({"type": "ready"}), flush=True)
        time.sleep(30)
    """)
    session = PresageSession(command=command, ready_timeout_s=2)
    session.start()
    try:
        with pytest.raises(PresageError, match="no composure"):
            session.finish()
    finally:
        session.close()


def test_composure_scores_against_the_claim():
    result = score_composure_round(5, claim=80, composure=50)
    assert result.unit == "composure"
    assert result.actual == 50
    assert result.gap == 30
    reading = score_reading({"round_id": 6, "claim": 40, "composure": 40, "false_start": False,
                             "timeout": False})
    assert reading.gap == 0
    with pytest.raises(ValueError):
        score_composure_round(5, claim=80, composure=None)
