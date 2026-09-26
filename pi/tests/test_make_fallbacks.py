"""pi/make_fallbacks.py: dry run, skip/force, --only/--round, the (faked) HTTP call, errors.
Never touches the network or the real assets/ folder (except a read-only --dry-run)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

import config
import elevenlabs_client as ec
import make_fallbacks as mf

KEY = "sk-test-SECRET-1234"
VOICE = "voice-under-test"
MODEL = "eleven_flash_v2_5"
ALL_FILES = [p.name for p, _ in ec.fallback_plan()]


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


@pytest.fixture
def env(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.setattr(config, "ASSETS_DIR", assets)
    monkeypatch.setattr(config, "FALLBACK_AUDIO", assets / "fallback_verdict.mp3")
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(config, "ELEVENLABS_VOICE_ID", VOICE)
    monkeypatch.setattr(config, "ELEVENLABS_MODEL_ID", MODEL)
    calls = []

    def fake_post(url, **kw):
        calls.append({"url": url, **kw})
        return _FakeResponse([b"ID3", kw["json"]["text"].encode()])

    monkeypatch.setattr(ec.requests, "post", fake_post)
    return assets, calls


def _run(capsys, *argv):
    code = mf.main(list(argv))
    out, err = capsys.readouterr()
    assert KEY not in out and KEY not in err
    return code, out, err


def test_dry_run_lists_every_file_and_text_and_writes_nothing(env, capsys, monkeypatch):
    assets, calls = env
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "")          # no key needed
    code, out, _ = _run(capsys, "--dry-run")
    assert code == 0 and calls == []
    assert list(assets.iterdir()) == []
    for path, text in ec.fallback_plan():
        assert f'would generate {path.name}: "{text}"' in out
    assert f"Dry run: {len(ALL_FILES)} to generate, 0 skipped" in out
    assert "NOT set" in out


def test_dry_run_with_key_says_set_but_never_prints_it(env, capsys):
    code, out, _ = _run(capsys, "--dry-run")
    assert code == 0 and "ELEVENLABS_API_KEY set" in out


def test_round_and_only_filters(env, capsys):
    _, out, _ = _run(capsys, "--dry-run", "--round", "2")
    assert "fallback_round2_delulu.mp3" in out and "fallback_delulu.mp3" in out
    assert "fallback_false_start.mp3" not in out
    _, out, _ = _run(capsys, "--dry-run", "--round", "1")
    assert "fallback_false_start.mp3" in out and "fallback_round2_" not in out
    _, out, _ = _run(capsys, "--dry-run", "--only", "fallback_round2_*")
    assert out.count("would generate") == 4 and "fallback_verdict.mp3" not in out


def test_only_matching_nothing_is_an_error(env, capsys):
    code, _, err = _run(capsys, "--only", "nope*")
    assert code == 1 and "no fallback file matches" in err and "fallback_verdict.mp3" in err


def test_generates_with_the_right_url_voice_model_and_writes_files(env, capsys):
    assets, calls = env
    code, out, _ = _run(capsys, "--only", "fallback_delulu.mp3")
    assert code == 0 and len(calls) == 1
    call = calls[0]
    assert call["url"] == f"{config.ELEVENLABS_BASE_URL}/v1/text-to-speech/{VOICE}"
    assert call["json"] == {"text": ec.FALLBACK_LINES[(None, "delulu")], "model_id": MODEL}
    assert call["headers"]["xi-api-key"] == KEY
    assert call["params"] == {"output_format": config.ELEVENLABS_OUTPUT_FORMAT}
    written = assets / "fallback_delulu.mp3"
    assert written.read_bytes() == b"ID3" + ec.FALLBACK_LINES[(None, "delulu")].encode()
    assert sorted(p.name for p in assets.iterdir()) == ["fallback_delulu.mp3"]   # no .part left
    assert "wrote" in out and "Listen to each new file once" in out


def test_generic_file_goes_to_config_fallback_audio(env, capsys):
    assets, calls = env
    code, _, _ = _run(capsys, "--only", "fallback_verdict.mp3")
    assert code == 0 and config.FALLBACK_AUDIO.is_file()
    assert calls[0]["json"]["text"] == ec.FALLBACK_LINES[(None, None)]


def test_skips_existing_files(env, capsys):
    assets, calls = env
    (assets / "fallback_delulu.mp3").write_bytes(b"hand-picked take")
    code, out, _ = _run(capsys)
    assert code == 0
    assert (assets / "fallback_delulu.mp3").read_bytes() == b"hand-picked take"
    assert "skip           fallback_delulu.mp3" in out
    assert len(calls) == len(ALL_FILES) - 1
    assert sorted(p.name for p in assets.iterdir()) == sorted(ALL_FILES)
    calls.clear()
    code, out, _ = _run(capsys)                                    # second run: nothing to do
    assert code == 0 and calls == [] and "Nothing to do" in out


def test_force_regenerates_existing_files(env, capsys):
    assets, calls = env
    (assets / "fallback_delulu.mp3").write_bytes(b"old")
    code, _, _ = _run(capsys, "--only", "fallback_delulu.mp3", "--force")
    assert code == 0 and len(calls) == 1
    assert (assets / "fallback_delulu.mp3").read_bytes().startswith(b"ID3")


def test_http_error_exits_nonzero_with_clear_message_and_no_key(env, capsys, monkeypatch):
    assets, _ = env
    calls = []

    def unauthorized(url, **kw):
        calls.append(url)
        return _FakeResponse([], 401, f'{{"detail":"invalid api key {KEY}"}}')

    monkeypatch.setattr(ec.requests, "post", unauthorized)
    code, out, err = _run(capsys)                                  # _run asserts the key is hidden
    assert code == 1 and len(calls) == 1                           # stops at the first failure
    assert "could not generate fallback_verdict.mp3" in err and "HTTP 401" in err
    assert "***" in err
    assert list(assets.iterdir()) == []                            # nothing half-written


def test_network_error_exits_nonzero(env, capsys, monkeypatch):
    assets, _ = env

    def boom(url, **kw):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(ec.requests, "post", boom)
    code, _, err = _run(capsys, "--only", "fallback_mild.mp3")
    assert code == 1 and "ConnectionError" in err and not (assets / "fallback_mild.mp3").exists()


def test_missing_key_exits_nonzero_without_network(env, capsys, monkeypatch):
    assets, calls = env
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "")
    code, _, err = _run(capsys)
    assert code == 2 and calls == [] and "ELEVENLABS_API_KEY is not set" in err
    assert list(assets.iterdir()) == []


def test_uses_its_own_timeout_not_the_live_budget(env, capsys, monkeypatch):
    seen = {}

    def fake_synthesize(text, out_path, **kw):
        seen.update(kw)
        out_path.write_bytes(b"ID3")
        return out_path

    monkeypatch.setattr(ec, "synthesize", fake_synthesize)
    code, _, _ = _run(capsys, "--only", "fallback_mild.mp3", "--timeout", "12")
    assert code == 0 and seen["timeout_s"] == 12.0
    assert seen["voice_id"] == VOICE and seen["model_id"] == MODEL and seen["api_key"] == KEY


def test_cli_dry_run_runs_from_the_repo_root():
    repo = Path(mf.__file__).resolve().parent.parent
    env = {**os.environ, "ELEVENLABS_API_KEY": ""}
    proc = subprocess.run([sys.executable, "pi/make_fallbacks.py", "--dry-run"], cwd=repo,
                          env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert "fallback_verdict.mp3" in proc.stdout and "Nothing was written" in proc.stdout
