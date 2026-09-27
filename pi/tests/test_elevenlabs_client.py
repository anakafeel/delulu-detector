"""Verdict text and the ElevenLabs time budget. No network: requests.post is faked."""
import time

import pytest
import requests

import config
import elevenlabs_client as ec
from scoring import score_reflex_round


class _PickEach:
    """rng stand-in whose choice() returns option i."""

    def __init__(self, i):
        self.i = i

    def choice(self, options):
        return options[self.i % len(options)]


@pytest.mark.parametrize("result,tier", [
    (score_reflex_round(0, None, timeout=True), "timeout"),
    (score_reflex_round(90, None, timeout=True), "timeout"),
    (score_reflex_round(0, None, false_start=True), "false_start"),
    (score_reflex_round(85, None, false_start=True), "false_start"),
])
def test_verdict_text_for_failed_rounds(result, tier):
    assert ec.template_key(result) == tier
    for i in range(len(ec.TEMPLATES[tier])):
        text = ec.build_verdict_text(result, "Saim", rng=_PickEach(i))
        assert "Saim" in text
        assert "unknown" not in text and "{" not in text
        assert str(result.claim) in text


def test_verdict_text_for_scored_round_still_works():
    r = score_reflex_round(90, 375)
    text = ec.build_verdict_text(r, "Saim")
    assert "unknown" not in text and "{" not in text


class _FakeResponse:
    def __init__(self, chunks, status_code=200, chunk_delay_s=0.0):
        self.status_code = status_code
        self.text = ""
        self._chunks = chunks
        self._delay = chunk_delay_s

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            time.sleep(self._delay)
            yield c


def test_synthesize_passes_connect_read_tuple_within_budget(monkeypatch, tmp_path):
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return _FakeResponse([b"ID3", b"audio"])

    monkeypatch.setattr(ec.requests, "post", fake_post)
    out = ec.synthesize("hi", tmp_path / "v.mp3", api_key="k", timeout_s=3.0)
    assert out.read_bytes() == b"ID3audio"
    connect_s, read_s = seen["timeout"]
    assert connect_s > 0 and read_s > 0
    assert connect_s + read_s <= 3.0
    assert seen["stream"] is True


@pytest.mark.parametrize("speed,expected", [(1.15, {"speed": 1.15}), (1.0, None)])
def test_speed_goes_in_voice_settings_only_when_not_1(monkeypatch, tmp_path, speed, expected):
    seen = {}
    monkeypatch.setattr(ec.requests, "post",
                        lambda url, **kw: seen.update(kw) or _FakeResponse([b"audio"]))
    monkeypatch.setattr(config, "ELEVENLABS_SPEED", speed)
    ec.synthesize("hi", tmp_path / "v.mp3", api_key="k", timeout_s=3.0)
    assert seen["json"].get("voice_settings") == expected
    assert seen["json"]["text"] == "hi"


def test_slow_first_byte_cannot_exceed_budget(monkeypatch, tmp_path):
    # requests.post blocks (slow DNS/connect/first byte) far past the budget.
    def slow_post(url, **kw):
        time.sleep(2.0)
        return _FakeResponse([b"late"])

    monkeypatch.setattr(ec.requests, "post", slow_post)
    t0 = time.monotonic()
    with pytest.raises(ec.TTSError, match="budget"):
        ec.synthesize("hi", tmp_path / "v.mp3", api_key="k", timeout_s=0.3)
    assert time.monotonic() - t0 < 0.8
    assert not (tmp_path / "v.mp3").exists()


def test_slow_stream_cannot_exceed_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(ec.requests, "post",
                        lambda url, **kw: _FakeResponse([b"x"] * 50, chunk_delay_s=0.05))
    t0 = time.monotonic()
    with pytest.raises(ec.TTSError, match="budget"):
        ec.synthesize("hi", tmp_path / "v.mp3", api_key="k", timeout_s=0.3)
    assert time.monotonic() - t0 < 0.8


def test_request_exception_becomes_tts_error(monkeypatch, tmp_path):
    def boom(url, **kw):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(ec.requests, "post", boom)
    with pytest.raises(ec.TTSError, match="ConnectionError"):
        ec.synthesize("hi", tmp_path / "v.mp3", api_key="k", timeout_s=1.0)


def test_mp3_write_failure_is_unavailable_and_plays_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([b"audio"]))
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("file where the tts folder should be")
    monkeypatch.setattr(config, "TTS_OUTPUT_DIR", blocker / "tts")
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "k")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fallback_spicy.mp3").write_bytes(b"ID3")
    (assets / "fallback_verdict.mp3").write_bytes(b"ID3")
    monkeypatch.setattr(config, "ASSETS_DIR", assets)
    monkeypatch.setattr(config, "FALLBACK_AUDIO", assets / "fallback_verdict.mp3")
    played = []
    monkeypatch.setattr(ec, "play_audio", lambda path: played.append(path) or True)
    v = ec.deliver_verdict(score_reflex_round(90, 375), "Saim", play=True)
    assert v.source == "unavailable"
    assert v.audio_path is None and played == []
    assert v.error and "could not write" in v.error and v.error == v.reason


def test_no_key_is_unavailable_without_network_or_playback(monkeypatch, tmp_path):
    def fail_post(url, **kw):
        raise AssertionError("must not call the network without a key")

    monkeypatch.setattr(ec.requests, "post", fail_post)
    monkeypatch.setattr(ec, "play_audio", lambda path: pytest.fail(f"played {path}"))
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "")
    (tmp_path / "fallback_timeout.mp3").write_bytes(b"ID3")
    (tmp_path / "fallback_verdict.mp3").write_bytes(b"ID3")
    monkeypatch.setattr(config, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(config, "FALLBACK_AUDIO", tmp_path / "fallback_verdict.mp3")
    v = ec.deliver_verdict(score_reflex_round(0, None, timeout=True), "Saim", play=True)
    assert v.source == "unavailable" and v.audio_path is None
    assert v.error and "not set" in v.error and v.error == v.reason
