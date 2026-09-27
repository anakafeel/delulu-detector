"""Narrator: verdict line rules (word limit, variety, placeholders), the
no-repeat memory, and delivery when TTS fails or is slow.
No network: requests.post is faked everywhere. TTS failure never plays audio."""
import re
import string
import time

import pytest
import requests

import config
import elevenlabs_client as ec
from scoring import score_poker_round, score_reflex_round, score_steady_round

LONG_NAME = "Maximilian"            # 10 characters
assert len(LONG_NAME) == 10
# Longest realistic values: claim/perf/gap top out at 100, readings as 3 digits.
LONGEST_VALUES = dict(player=LONG_NAME, claim=100, perf=100, gap=100, ms=999, mg=999, peak=999,
                      smile=100, secs=999, held=999, claimsecs=999)
PLACEHOLDERS = {"player", "claim", "perf", "gap", "ms", "mg", "peak", "smile", "secs", "held", "claimsecs"}
# Raw-reading placeholders each round may use (the shared ones are always allowed).
ROUND_PLACEHOLDERS = {1: {"ms"}, 2: {"mg", "peak"}, 5: {"smile", "secs"}, 6: {"held", "claimsecs"}}
TEMPLATE_SETS = {1: ec.TEMPLATES, 2: ec.STEADY_TEMPLATES, 5: ec.POKER_TEMPLATES, 6: ec.STRAIGHT_TEMPLATES}
ALL_LINES = [(rid, key, line) for rid, t in TEMPLATE_SETS.items()
             for key, lines in t.items() for line in lines]
SCORED_KEYS = ["validated"] + [f"{t}_{d}" for t in ("mild", "spicy", "delulu") for d in ("over", "under")]


class _PickFirst:
    def choice(self, options):
        return options[0]


# ------------------------------------------------------------------ line rules
@pytest.mark.parametrize("round_id,key,line", ALL_LINES)
def test_every_line_fits_the_word_limit_with_long_name_and_numbers(round_id, key, line):
    text = line.format(**LONGEST_VALUES)
    assert ec.word_count(text) <= ec.MAX_VERDICT_WORDS, (round_id, key, text)


def test_word_limit_is_18():
    assert ec.MAX_VERDICT_WORDS == 18
    assert ec.word_count("one two  three\tfour") == 4


@pytest.mark.parametrize("round_id,key,line", ALL_LINES)
def test_every_line_uses_only_known_placeholders(round_id, key, line):
    names = {f for _, f, _, _ in string.Formatter().parse(line) if f is not None}
    assert names <= PLACEHOLDERS, line
    raw = PLACEHOLDERS - {"player", "claim", "perf", "gap"}
    assert not names & (raw - ROUND_PLACEHOLDERS[round_id]), line     # only this round's readings
    if key in ("false_start", "timeout", "void"):
        assert not names & (raw | {"perf", "gap"}), line                 # nothing was measured


@pytest.mark.parametrize("round_id", [1, 2, 5, 6])
def test_every_key_has_at_least_4_distinct_lines(round_id):
    templates = TEMPLATE_SETS[round_id]
    expected = SCORED_KEYS + ["void"] + (["false_start", "timeout"] if round_id == 1 else [])
    assert set(templates) == set(expected)
    for key, lines in templates.items():
        assert len(lines) >= 4, key
        assert len(set(lines)) == len(lines), key


def test_no_round_id_3_content():
    # Internal round id 3 (the parked Retreat idea) has no templates or name.
    # What the Hill's "Round 3" is Straight Face, internal id 6.
    assert set(ec.ROUND_TEMPLATES) == {1, 2, 5, 6}
    assert 3 not in config.ROUND_NAMES


def test_first_void_line_is_the_safe_last_resort():
    assert set(re.findall(r"{(\w+)}", ec.TEMPLATES["void"][0])) == {"player"}


# ------------------------------------------------------------------ no-repeat memory
def test_memory_never_repeats_a_line_back_to_back():
    r = score_reflex_round(95, 500)                                  # delulu_over
    memory = ec.LastLineMemory()
    texts = [ec.build_verdict_text(r, "Saim", rng=_PickFirst(), memory=memory) for _ in range(6)]
    assert all(a != b for a, b in zip(texts, texts[1:])), texts
    # without a memory the same rng keeps picking the same line
    assert ec.build_verdict_text(r, "Saim", rng=_PickFirst()) == ec.build_verdict_text(r, "Saim", rng=_PickFirst())


def test_memory_is_per_player():
    r = score_steady_round(100, 62.0)                               # delulu_over
    memory = ec.LastLineMemory()
    a = ec.build_verdict_text(r, "Saim", rng=_PickFirst(), memory=memory)
    b = ec.build_verdict_text(r, "Alex", rng=_PickFirst(), memory=memory)
    assert a.replace("Saim", "X") == b.replace("Alex", "X")          # Alex may hear Saim's line
    assert ec.build_verdict_text(r, "Saim", rng=_PickFirst(), memory=memory) != a
    memory.clear()
    assert ec.build_verdict_text(r, "Saim", rng=_PickFirst(), memory=memory) == a


def test_memory_allows_a_repeat_when_only_one_line_fits(monkeypatch):
    monkeypatch.setitem(ec.TEMPLATES, "timeout", ["{player} timed out at {claim}."])
    r = score_reflex_round(40, None, timeout=True)
    memory = ec.LastLineMemory()
    first = ec.build_verdict_text(r, "Saim", memory=memory)
    assert ec.build_verdict_text(r, "Saim", memory=memory) == first == "Saim timed out at 40."


def test_memory_respects_missing_readings():
    # No peak -> the {peak} lines are never picked, memory or not.
    r = score_steady_round(90, 44.0)                                # spicy_over, no peak
    memory = ec.LastLineMemory()
    for _ in range(20):
        text = ec.build_verdict_text(r, "Saim", memory=memory)
        assert "unknown" not in text and "{" not in text


def test_deliver_verdict_uses_the_session_memory(monkeypatch, tmp_path):
    _no_key_no_assets(monkeypatch, tmp_path)
    ec.SESSION_LINES.clear()
    r = score_reflex_round(95, 500)
    texts = [ec.deliver_verdict(r, "Saim", play=False).text for _ in range(25)]
    assert all(a != b for a, b in zip(texts, texts[1:]))
    assert len(set(texts)) > 1
    ec.SESSION_LINES.clear()


# ------------------------------------------------------------------ delivery when TTS fails
# Present on disk during failure tests so a reintroduced lookup would be audible.
_IGNORED_FALLBACK_FILES = (
    "fallback_verdict.mp3",
    "fallback_validated.mp3", "fallback_mild.mp3", "fallback_spicy.mp3", "fallback_delulu.mp3",
    "fallback_false_start.mp3", "fallback_timeout.mp3",
    "fallback_round2_validated.mp3", "fallback_round2_mild.mp3",
    "fallback_round2_spicy.mp3", "fallback_round2_delulu.mp3",
    "fallback_round5_validated.mp3", "fallback_round5_mild.mp3",
    "fallback_round5_spicy.mp3", "fallback_round5_delulu.mp3",
    "fallback_round6_validated.mp3", "fallback_round6_mild.mp3",
    "fallback_round6_spicy.mp3", "fallback_round6_delulu.mp3",
)


class _FakeResponse:
    def __init__(self, chunks, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=8192):
        yield from self._chunks


def _no_key_no_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(config, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(config, "FALLBACK_AUDIO", tmp_path / "assets" / "fallback_verdict.mp3")
    monkeypatch.setattr(config, "TTS_OUTPUT_DIR", tmp_path / "tts")
    monkeypatch.setattr(ec.requests, "post", lambda *a, **k: pytest.fail("network call without a key"))


@pytest.fixture
def live(monkeypatch, tmp_path):
    """A key is set, assets/ is a temp dir, playback is recorded instead of run."""
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(config, "ASSETS_DIR", assets)
    monkeypatch.setattr(config, "FALLBACK_AUDIO", assets / "fallback_verdict.mp3")
    monkeypatch.setattr(config, "TTS_OUTPUT_DIR", tmp_path / "tts")
    played = []
    monkeypatch.setattr(ec, "play_audio", lambda path: played.append(path) or True)
    ec.SESSION_LINES.clear()
    yield assets, played
    ec.SESSION_LINES.clear()


def _plant_fallbacks(assets):
    for name in _IGNORED_FALLBACK_FILES:
        (assets / name).write_bytes(b"ID3")


def _assert_unavailable(v, played, needle):
    assert v.source == "unavailable"
    assert v.audio_path is None and played == []
    assert v.error and needle in v.error and v.error == v.reason


def test_budget_overrun_plays_nothing_and_prints_text(live, monkeypatch, capsys):
    assets, played = live
    _plant_fallbacks(assets)
    monkeypatch.setattr(config, "ELEVENLABS_TIMEOUT_S", 0.3)

    def slow_post(url, **kw):
        time.sleep(1.5)
        return _FakeResponse([b"late"])

    monkeypatch.setattr(ec.requests, "post", slow_post)
    t0 = time.monotonic()
    v = ec.deliver_verdict(score_steady_round(100, 62.0), "Saim", play=True)
    assert time.monotonic() - t0 < 1.0
    _assert_unavailable(v, played, "budget")
    captured = capsys.readouterr()
    assert f'NARRATOR: "{v.text}"' in captured.out
    assert "[fallback]" not in captured.out and "fallback_" not in captured.out
    assert "TTS unavailable" in captured.err and "budget" in captured.err


def test_http_error_plays_nothing(live, monkeypatch, capsys):
    assets, played = live
    _plant_fallbacks(assets)
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([], 503, "busy"))
    v = ec.deliver_verdict(score_reflex_round(85, 375), "Saim", play=True)   # spicy_over
    _assert_unavailable(v, played, "HTTP 503")
    captured = capsys.readouterr()
    assert f'NARRATOR: "{v.text}"' in captured.out
    assert "fallback_" not in captured.out and "HTTP 503" in captured.err


# Results are built inside the test: the Round 2 thresholds are pinned by an
# autouse fixture, which isn't active yet when parametrize arguments are evaluated.
@pytest.mark.parametrize("make_result", [
    lambda: score_reflex_round(90, None, false_start=True),
    lambda: score_reflex_round(90, None, timeout=True),
    lambda: score_steady_round(80, 22.4),
    lambda: score_reflex_round(52, 375),
    lambda: score_reflex_round(35, 375),
    lambda: score_steady_round(15, 44.0),
    lambda: score_poker_round(100, 0.40),
    lambda: score_poker_round(45, 0.25),
])
def test_network_failure_never_plays_a_fallback_file(live, monkeypatch, make_result):
    assets, played = live
    _plant_fallbacks(assets)

    def boom(url, **kw):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(ec.requests, "post", boom)
    v = ec.deliver_verdict(make_result(), "Saim", play=True)
    _assert_unavailable(v, played, "ConnectionError")


def test_http_500_ignores_a_generic_fallback_file(live, monkeypatch):
    assets, played = live
    _plant_fallbacks(assets)
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([], 500))
    v = ec.deliver_verdict(score_steady_round(100, 62.0), "Saim", play=True)
    _assert_unavailable(v, played, "HTTP 500")


def test_empty_audio_prints_the_verdict_and_plays_nothing(live, monkeypatch, capsys):
    assets, played = live
    _plant_fallbacks(assets)
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([b""]))
    v = ec.deliver_verdict(score_reflex_round(95, 500), "Saim", play=True)
    _assert_unavailable(v, played, "empty audio")
    captured = capsys.readouterr()
    assert f'NARRATOR: "{v.text}"' in captured.out
    assert "[fallback]" not in captured.out and "text only" not in captured.out
    assert "empty audio" in captured.err


def test_success_prints_text_and_plays_the_synthesized_file(live, monkeypatch, capsys):
    assets, played = live
    _plant_fallbacks(assets)
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([b"ID3", b"audio"]))
    v = ec.deliver_verdict(score_reflex_round(95, 500), "Saim", play=True)
    assert v.source == "elevenlabs" and v.reason is None and v.error is None
    assert played == [v.audio_path] and v.audio_path.read_bytes() == b"ID3audio"
    assert v.audio_path.parent == config.TTS_OUTPUT_DIR
    assert v.audio_path.name not in _IGNORED_FALLBACK_FILES
    out = capsys.readouterr().out
    assert f'NARRATOR: "{v.text}"' in out and "[fallback]" not in out and "[error]" not in out


def test_verdict_text_is_printed_before_synthesis_starts(live, monkeypatch, capsys):
    seen = {}

    def fake_synthesize(text, out, **kw):
        seen["printed"] = capsys.readouterr().out
        raise ec.TTSError("simulated")

    monkeypatch.setattr(ec, "synthesize", fake_synthesize)
    v = ec.deliver_verdict(score_reflex_round(95, 500), "Saim", play=False)
    assert f'NARRATOR: "{v.text}"' in seen["printed"]


def test_live_budget_default_is_still_3_seconds():
    from pathlib import Path
    source = Path(config.__file__).read_text()
    assert 'ELEVENLABS_TIMEOUT_S = _env_float("ELEVENLABS_TIMEOUT_S", 3.0)' in source
