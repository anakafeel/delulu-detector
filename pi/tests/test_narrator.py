"""Narrator: verdict line rules (word limit, variety, placeholders), the
no-repeat memory, the fallback lines, and delivery when TTS fails or is slow.
No network: requests.post is faked everywhere."""
import re
import string
import time

import pytest
import requests

import config
import elevenlabs_client as ec
from scoring import score_reflex_round, score_steady_round

LONG_NAME = "Maximilian"            # 10 characters
assert len(LONG_NAME) == 10
# Longest realistic values: claim/perf/gap top out at 100, readings as 3 digits.
LONGEST_VALUES = dict(player=LONG_NAME, claim=100, perf=100, gap=100, ms=999, mg=999, peak=999)
PLACEHOLDERS = {"player", "claim", "perf", "gap", "ms", "mg", "peak"}
TEMPLATE_SETS = {1: ec.TEMPLATES, 2: ec.STEADY_TEMPLATES}
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
    if round_id == 2:
        assert "ms" not in names, line
    else:
        assert not names & {"mg", "peak"}, line
    if key in ("false_start", "timeout", "void"):
        assert not names & {"ms", "mg", "peak", "perf", "gap"}, line   # nothing was measured


@pytest.mark.parametrize("round_id", [1, 2])
def test_every_key_has_at_least_4_distinct_lines(round_id):
    templates = TEMPLATE_SETS[round_id]
    expected = SCORED_KEYS + ["void"] + (["false_start", "timeout"] if round_id == 1 else [])
    assert set(templates) == set(expected)
    for key, lines in templates.items():
        assert len(lines) >= 4, key
        assert len(set(lines)) == len(lines), key


def test_no_round_3_content():
    assert set(ec.ROUND_TEMPLATES) == {1, 2}
    assert all(rid in (None, 1, 2) for rid, _ in ec.FALLBACK_LINES)


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


# ------------------------------------------------------------------ fallback lines
EXPECTED_FALLBACK_FILES = {
    "fallback_verdict.mp3",
    "fallback_validated.mp3", "fallback_mild.mp3", "fallback_spicy.mp3", "fallback_delulu.mp3",
    "fallback_false_start.mp3", "fallback_timeout.mp3",
    "fallback_round2_validated.mp3", "fallback_round2_mild.mp3",
    "fallback_round2_spicy.mp3", "fallback_round2_delulu.mp3",
}
NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                "ten", "hundred", "percent", "millisecond", "milli-g")


def test_fallback_files_match_what_the_app_looks_for():
    names = {path.name for path, _ in ec.fallback_plan()}
    assert names == EXPECTED_FALLBACK_FILES
    assert config.FALLBACK_AUDIO.name in names
    # every tier a round can produce has a file of its own in the chain before the generic one
    for rid in (1, 2):
        for tier in ec.round_tiers(rid):
            chain = [p.name for p in ec.fallback_candidates(tier, rid)[:-1]]
            assert set(chain) & names, (rid, tier)


@pytest.mark.parametrize("key,text", list(ec.FALLBACK_LINES.items()))
def test_fallback_lines_are_name_and_number_free_and_short(key, text):
    assert not re.search(r"\d", text), text
    assert "{" not in text and "}" not in text, text
    words = set(re.findall(r"[a-z-]+", text.lower()))
    assert not words & set(NUMBER_WORDS), text
    assert ec.word_count(text) <= ec.MAX_VERDICT_WORDS, text
    if key[0] == 2 or key[1] in ("validated", "mild", "spicy", "delulu", None):
        # tier files are picked by tier only, so they must not assume a direction
        assert not re.search(r"\b(over|under)\s?confident|sandbag", text.lower()), text


def test_fallback_plan_per_round():
    r1 = {p.name for p, _ in ec.fallback_plan(1)}
    r2 = {p.name for p, _ in ec.fallback_plan(2)}
    assert "fallback_false_start.mp3" in r1 and "fallback_round2_delulu.mp3" not in r1
    assert "fallback_false_start.mp3" not in r2 and "fallback_round2_delulu.mp3" in r2
    assert "fallback_verdict.mp3" in r1 & r2


# ------------------------------------------------------------------ delivery when TTS fails
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


def _make(assets, *names):
    for n in names:
        (assets / n).write_bytes(b"ID3")


def test_budget_overrun_plays_round_2_tier_fallback_and_prints_text(live, monkeypatch, capsys):
    assets, played = live
    _make(assets, "fallback_round2_delulu.mp3", "fallback_delulu.mp3", "fallback_verdict.mp3")
    monkeypatch.setattr(config, "ELEVENLABS_TIMEOUT_S", 0.3)

    def slow_post(url, **kw):
        time.sleep(1.5)
        return _FakeResponse([b"late"])

    monkeypatch.setattr(ec.requests, "post", slow_post)
    t0 = time.monotonic()
    v = ec.deliver_verdict(score_steady_round(100, 62.0), "Saim", play=True)
    assert time.monotonic() - t0 < 1.0
    assert v.source == "fallback_audio" and "budget" in v.reason
    assert v.audio_path.name == "fallback_round2_delulu.mp3"
    assert played == [v.audio_path]
    out = capsys.readouterr().out
    assert f'NARRATOR: "{v.text}"' in out
    assert "[fallback]" in out and "fallback_round2_delulu.mp3" in out


def test_http_error_in_round_1_uses_round_neutral_tier_file(live, monkeypatch, capsys):
    assets, played = live
    _make(assets, "fallback_round2_spicy.mp3", "fallback_spicy.mp3", "fallback_verdict.mp3")
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([], 503, "busy"))
    v = ec.deliver_verdict(score_reflex_round(85, 375), "Saim", play=True)   # spicy_over
    assert v.source == "fallback_audio" and "HTTP 503" in v.reason
    assert v.audio_path.name == "fallback_spicy.mp3" and played == [v.audio_path]
    assert f'NARRATOR: "{v.text}"' in capsys.readouterr().out


# Results are built inside the test: the Round 2 thresholds are pinned by an
# autouse fixture, which isn't active yet when parametrize arguments are evaluated.
@pytest.mark.parametrize("make_result,expected", [
    (lambda: score_reflex_round(90, None, false_start=True), "fallback_false_start.mp3"),
    (lambda: score_reflex_round(90, None, timeout=True), "fallback_timeout.mp3"),
    (lambda: score_steady_round(80, 22.4), "fallback_round2_validated.mp3"),     # perf 80
    (lambda: score_reflex_round(52, 375), "fallback_validated.mp3"),             # perf 50
    (lambda: score_reflex_round(35, 375), "fallback_mild.mp3"),                  # gap 15, under
    (lambda: score_steady_round(15, 44.0), "fallback_round2_spicy.mp3"),         # spicy, under
])
def test_network_failure_picks_the_right_file_for_every_generated_name(live, monkeypatch,
                                                                        make_result, expected):
    assets, played = live
    result = make_result()
    _make(assets, *EXPECTED_FALLBACK_FILES)

    def boom(url, **kw):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(ec.requests, "post", boom)
    v = ec.deliver_verdict(result, "Saim", play=True)
    assert v.source == "fallback_audio" and v.audio_path.name == expected
    assert played == [v.audio_path]


def test_missing_tier_file_falls_back_to_generic(live, monkeypatch):
    assets, played = live
    _make(assets, "fallback_verdict.mp3")
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([], 500))
    v = ec.deliver_verdict(score_steady_round(100, 62.0), "Saim", play=True)
    assert v.audio_path.name == "fallback_verdict.mp3" and played == [v.audio_path]


def test_no_audio_at_all_still_prints_the_verdict(live, monkeypatch, capsys):
    _, played = live
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([b""]))
    v = ec.deliver_verdict(score_reflex_round(95, 500), "Saim", play=True)
    assert v.source == "text_only" and v.audio_path is None and played == []
    out = capsys.readouterr().out
    assert f'NARRATOR: "{v.text}"' in out and "text only" in out


def test_success_prints_text_and_plays_the_synthesized_file(live, monkeypatch, capsys):
    assets, played = live
    _make(assets, *EXPECTED_FALLBACK_FILES)
    monkeypatch.setattr(ec.requests, "post", lambda url, **kw: _FakeResponse([b"ID3", b"audio"]))
    v = ec.deliver_verdict(score_reflex_round(95, 500), "Saim", play=True)
    assert v.source == "elevenlabs" and v.reason is None
    assert played == [v.audio_path] and v.audio_path.read_bytes() == b"ID3audio"
    out = capsys.readouterr().out
    assert f'NARRATOR: "{v.text}"' in out and "[fallback]" not in out


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
