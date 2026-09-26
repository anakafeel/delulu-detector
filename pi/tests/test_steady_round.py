"""Round 2 (Steady Hands): tremor -> performance, scoring, serial parsing, verdict text."""
import pytest

import config
import elevenlabs_client as ec
from main import is_sensor_error, parse_line
from scoring import (ROUND_STEADY, score_reading, score_reflex_round, score_steady_round,
                     tremor_mg_to_performance)

R2_LINE = ('{"type":"result","round_id":2,"seq":4,"claim":72,"actual":14.3,"unit":"mg_rms",'
           '"peak":61.2,"samples":500,"false_start":false,"timeout":false}')
R2_ERROR_LINE = ('{"type":"result","round_id":2,"seq":5,"claim":72,"actual":null,"unit":"mg_rms",'
                 '"peak":null,"samples":0,"false_start":false,"timeout":false,"error":"no_accel"}')


# ------------------------------------------------------------------ mapping
@pytest.mark.parametrize("mg,expected", [
    (2.0, 100.0),    # below the noise-floor bound clamps to 100
    (8.0, 100.0),
    (44.0, 50.0),    # midpoint of 8..80
    (80.0, 0.0),
    (500.0, 0.0),    # shakier than the worst bound clamps to 0
])
def test_tremor_mapping_bounds_and_linearity(mg, expected):
    assert tremor_mg_to_performance(mg) == pytest.approx(expected)


def test_tremor_mapping_uses_config_values():
    # conftest pins 8 / 80 so the mapping is checked against known bounds.
    assert config.STEADY_BEST_MG == 8.0
    assert config.STEADY_WORST_MG == 80.0
    assert tremor_mg_to_performance(22.4) == pytest.approx(80.0)


def test_tremor_mapping_follows_config_changes(monkeypatch):
    monkeypatch.setattr(config, "STEADY_BEST_MG", 5.0)
    monkeypatch.setattr(config, "STEADY_WORST_MG", 105.0)
    assert tremor_mg_to_performance(55.0) == pytest.approx(50.0)


def test_tremor_mapping_rejects_bad_bounds():
    with pytest.raises(ValueError):
        tremor_mg_to_performance(20, best_mg=80, worst_mg=8)


# ------------------------------------------------------------------ scoring
def test_steady_round_overconfident():
    r = score_steady_round(claim=90, tremor_mg=44.0, peak_mg=150.0, samples=500)
    assert r.round_id == ROUND_STEADY and r.unit == "mg_rms"
    assert r.actual == 44.0 and r.actual_ms is None
    assert r.performance == 50.0 and r.gap == 40.0 and r.score == 60
    assert r.tier == "spicy" and r.direction == "over"
    assert r.extra == {"peak": 150.0, "samples": 500}
    assert r.scored and not r.failed


def test_steady_round_validated_and_under():
    r = score_steady_round(claim=75, tremor_mg=22.4)             # perf 80
    assert r.gap == 5.0 and r.tier == "validated" and r.direction == "under"


def test_steady_round_same_scoring_rules_as_round_1():
    # Same performance -> same gap, score and tier, whatever the round.
    r1 = score_reflex_round(claim=30, actual_ms=375)               # perf 50
    r2 = score_steady_round(claim=30, tremor_mg=44.0)              # perf 50
    assert (r1.gap, r1.score, r1.tier, r1.direction) == (r2.gap, r2.score, r2.tier, r2.direction)


def test_perfectly_still_claim_100_is_a_perfect_score():
    r = score_steady_round(claim=100, tremor_mg=3.0)
    assert r.performance == 100.0 and r.gap == 0.0 and r.score == 100


def test_steady_round_without_a_value_is_not_scored():
    with pytest.raises(ValueError):
        score_steady_round(claim=50, tremor_mg=None)


def test_score_reading_dispatches_by_round():
    r2 = score_reading(parse_line(R2_LINE))
    assert r2.round_id == 2 and r2.actual == 14.3 and r2.extra["samples"] == 500
    r1 = score_reading(parse_line('{"type":"result","round_id":1,"claim":50,"actual":300}'))
    assert r1.round_id == 1 and r1.unit == "ms" and r1.actual_ms == 300
    with pytest.raises(ValueError):
        score_reading({"round_id": 9, "claim": 50, "actual": 1})


# ------------------------------------------------------------------ parsing
def test_parse_round_2_result():
    msg = parse_line(R2_LINE)
    assert msg["round_id"] == 2 and msg["claim"] == 72.0
    assert msg["actual"] == 14.3 and msg["unit"] == "mg_rms"
    assert msg["peak"] == 61.2 and msg["samples"] == 500
    assert msg["false_start"] is False and msg["timeout"] is False
    assert not is_sensor_error(msg)


def test_parse_round_2_sensor_error():
    msg = parse_line(R2_ERROR_LINE)
    assert msg is not None and msg["actual"] is None and msg["peak"] is None
    assert msg["error"] == "no_accel"
    assert is_sensor_error(msg)


def test_round_2_without_actual_is_a_sensor_error_even_without_error_field():
    msg = parse_line('{"type":"result","round_id":2,"claim":50,"actual":null}')
    assert is_sensor_error(msg)


def test_round_1_failed_rounds_are_not_sensor_errors():
    msg = parse_line('{"type":"result","round_id":1,"claim":50,"actual":null,"false_start":true}')
    assert not is_sensor_error(msg)


def test_bad_optional_extras_are_dropped_not_fatal():
    msg = parse_line('{"type":"result","round_id":2,"claim":50,"actual":12.5,"peak":"x","samples":[1]}')
    assert msg["actual"] == 12.5 and msg["peak"] is None and msg["samples"] is None


@pytest.mark.parametrize("line", [
    '{"type":"status","state":"mode","round_id":2,"accel":"LIS3DH@0x19"}',
    '{"type":"status","state":"ready","accel":"none"}',
    '{"type":"status","state":"hold"}',
    '{"type":"result","round_id":2,"claim":72,"actual":14.',
])
def test_round_2_status_and_half_lines_are_ignored(line):
    assert parse_line(line) is None


# ------------------------------------------------------------------ verdicts
class _PickEach:
    def __init__(self, i):
        self.i = i

    def choice(self, options):
        return options[self.i % len(options)]


ROUND_1_ONLY_WORDS = ("millisecond", "react", "cue", "pressed", "thumb", "nervous system", "button")

@pytest.mark.parametrize("claim,mg,key", [
    (80, 22.4, "validated"),     # perf 80, gap 0
    (95, 22.4, "mild_over"),     # gap 15
    (85, 44.0, "spicy_over"),    # perf 50, gap 35
    (100, 62.0, "delulu_over"),  # perf 25, gap 75
    (65, 22.4, "mild_under"),    # gap 15
    (45, 22.4, "spicy_under"),   # gap 35
    (5, 22.4, "delulu_under"),   # gap 75
])
def test_every_round_2_tier_has_clean_lines(claim, mg, key):
    r = score_steady_round(claim, mg, peak_mg=90.0, samples=500)
    assert ec.template_key(r) == key
    options = ec.STEADY_TEMPLATES[key]
    assert options, key
    for i in range(len(options)):
        text = ec.build_verdict_text(r, "Saim", rng=_PickEach(i))
        assert "unknown" not in text and "{" not in text and "}" not in text
        assert str(r.claim) in text or f"{r.gap:.0f} points" in text
        assert not any(w in text.lower() for w in ROUND_1_ONLY_WORDS), text


def test_round_2_templates_cover_every_scored_tier_and_use_known_placeholders():
    for tier in ("validated", "mild", "spicy", "delulu"):
        for key in ((tier,) if tier == "validated" else (f"{tier}_over", f"{tier}_under")):
            assert ec.STEADY_TEMPLATES.get(key), key
    allowed = {"player", "claim", "perf", "gap", "ms", "mg", "peak"}
    import string
    for lines in ec.STEADY_TEMPLATES.values():
        for line in lines:
            names = {f for _, f, _, _ in string.Formatter().parse(line) if f}
            assert names <= allowed and "ms" not in names, line


def test_round_2_line_mentions_the_mg_value():
    r = score_steady_round(100, 62.0)                            # delulu_over
    texts = {ec.build_verdict_text(r, "Saim", rng=_PickEach(i))
             for i in range(len(ec.STEADY_TEMPLATES["delulu_over"]))}
    assert any("62 milli-g" in t for t in texts)
    assert any("leaf in a hurricane" in t for t in texts)


def test_round_1_still_uses_round_1_templates():
    r = score_reflex_round(100, 600)                             # delulu_over
    assert ec.templates_for(r.round_id) is ec.TEMPLATES
    text = ec.build_verdict_text(r, "Saim", rng=_PickEach(0))
    assert text == ec.TEMPLATES["delulu_over"][0].format(claim=100, ms=600, gap=100)


def test_round_specific_fallback_audio_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(config, "FALLBACK_AUDIO", tmp_path / "fallback_verdict.mp3")
    (tmp_path / "fallback_delulu.mp3").write_bytes(b"x")
    assert ec.fallback_audio_for("delulu", 2).name == "fallback_delulu.mp3"
    (tmp_path / "fallback_round2_delulu.mp3").write_bytes(b"x")
    assert ec.fallback_audio_for("delulu", 2).name == "fallback_round2_delulu.mp3"
    assert ec.fallback_audio_for("delulu", 1).name == "fallback_delulu.mp3"
    assert ec.fallback_audio_for("delulu").name == "fallback_delulu.mp3"


def test_shipped_calibration_is_sane():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("shipped_config", pathlib.Path(config.__file__))
    shipped = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shipped)
    assert 0 < shipped.STEADY_BEST_MG < shipped.STEADY_WORST_MG
