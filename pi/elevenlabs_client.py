"""Verdict lines + ElevenLabs text-to-speech, with a fallback that never blocks the demo.

deliver_verdict() is the one call main.py makes:
  1. build the verdict text from the round numbers (template picked by gap tier),
  2. try ElevenLabs TTS (REST, `requests`) with a hard total timeout
     (config.ELEVENLABS_TIMEOUT_S, default 3 s),
  3. on no key / timeout / HTTP error / no audio: play the pre-recorded fallback
     (assets/fallback_<tier>.mp3, else assets/fallback_verdict.mp3), and if
     that is missing too, just print the verdict text.
The verdict text is always printed so the audience can read it.
"""
from __future__ import annotations

import random
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

import config
from scoring import RoundResult

# ---------------------------------------------------------------------------
# Verdict templates. Placeholders: {player} {claim} {perf} {gap} {ms}
# "over" = claimed more than delivered, "under" = sandbagged.
# This is where the comedy lives; iterate freely.
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} claimed {claim} and delivered {perf}. A gap of {gap}. Validated. Annoyingly self-aware.",
        "Claim {claim}, reality {perf}. {player}, you actually know yourself. Validated. Rare.",
        "{gap} points off. {player} is calibrated. Nobody likes a know-it-all, but the numbers don't lie.",
    ],
    "mild_over": [
        "{player} said {claim}. Their thumb said {perf}. A {gap} point gap. Light delusion. We've all been there.",
        "Claimed {claim}, delivered {perf}. Slightly delulu, {player}. Nothing a little humility can't fix.",
    ],
    "spicy_over": [
        "You claimed {claim}. You reacted in {ms} milliseconds, which is a {perf}. That's a {gap} point gap. Your confidence wrote a check your nervous system can't cash.",
        "{player}, a {claim}? Reality scored you {perf}. {gap} points of pure vibes.",
    ],
    "delulu_over": [
        "{claim} out of 100? {ms} milliseconds. That is a {gap} point gap. Certified delulu. Please step away from the dial.",
        "{player} claimed {claim} and delivered {perf}. A {gap} point gap. Somewhere a psychology textbook just gained a new example.",
    ],
    "mild_under": [
        "{player} claimed only {claim} and hit {perf}. Underconfident by {gap}. Humble, but wrong.",
    ],
    "spicy_under": [
        "You said {claim}, you delivered {perf}. {gap} points of sandbagging, {player}. Believe in yourself a little.",
    ],
    "delulu_under": [
        "{player} claimed {claim} and then posted a {perf}. A {gap} point gap in the wrong direction. Reverse delulu. Suspicious.",
    ],
    "false_start": [
        "{player} locked in {claim} and pressed before the cue. False start. Confidence so high it time travelled.",
        "False start! {player} claimed {claim} and couldn't even wait for the light. Gap: {gap}.",
    ],
    "timeout": [
        "{player} claimed {claim}, then never pressed the button. Performance zero. Are you still with us?",
    ],
    "void": [
        "That round didn't count, {player}. Reset and try again.",
    ],
}


def _fmt(x: Optional[float]) -> str:
    return "unknown" if x is None else str(int(round(x)))


def template_key(result: RoundResult) -> str:
    if result.tier in ("validated", "false_start", "timeout", "void"):
        return result.tier
    direction = "under" if result.direction == "under" else "over"
    return f"{result.tier}_{direction}"


def build_verdict_text(result: RoundResult, player: str, rng: Optional[random.Random] = None) -> str:
    rng = rng or random
    options = TEMPLATES.get(template_key(result)) or TEMPLATES["void"]
    line = rng.choice(options)
    if result.actual_ms is None and "{ms}" in line:
        # never say "unknown milliseconds" out loud
        line = next((t for t in options if "{ms}" not in t), TEMPLATES["void"][0])
    return line.format(
        player=player,
        claim=_fmt(result.claim),
        perf=_fmt(result.performance),
        gap=_fmt(result.gap),
        ms=_fmt(result.actual_ms),
    )


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
class TTSError(Exception):
    pass


def synthesize(
    text: str,
    out_path: Path,
    api_key: str = config.ELEVENLABS_API_KEY,
    voice_id: str = config.ELEVENLABS_VOICE_ID,
    model_id: str = config.ELEVENLABS_MODEL_ID,
    timeout_s: float = config.ELEVENLABS_TIMEOUT_S,
) -> Path:
    """Call ElevenLabs TTS and write an mp3. Raises TTSError on any failure.

    timeout_s is a TOTAL budget (connect + download), not just per socket read.
    """
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY not set")
    url = f"{config.ELEVENLABS_BASE_URL}/v1/text-to-speech/{voice_id}"
    deadline = time.monotonic() + timeout_s
    try:
        resp = requests.post(
            url,
            params={"output_format": config.ELEVENLABS_OUTPUT_FORMAT},
            headers={"xi-api-key": api_key, "Content-Type": "application/json",
                     "Accept": "audio/mpeg"},
            json={"text": text, "model_id": model_id},
            timeout=timeout_s,
            stream=True,
        )
        with resp:
            if resp.status_code != 200:
                raise TTSError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            chunks = []
            for chunk in resp.iter_content(chunk_size=8192):
                if time.monotonic() > deadline:
                    raise TTSError(f"download exceeded {timeout_s}s budget")
                chunks.append(chunk)
    except requests.RequestException as exc:
        raise TTSError(f"{type(exc).__name__}: {exc}") from exc
    audio = b"".join(chunks)
    if not audio:
        raise TTSError("empty audio response")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    return out_path


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------
_PLAYERS = [
    ["mpg123", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ["mpv", "--no-video", "--really-quiet"],
    ["cvlc", "--play-and-exit", "--quiet"],
]


def find_player_cmd() -> Optional[list[str]]:
    if config.AUDIO_PLAYER:
        return shlex.split(config.AUDIO_PLAYER)
    for cmd in _PLAYERS:
        if shutil.which(cmd[0]):
            return list(cmd)
    return None


def play_audio(path: Path) -> bool:
    cmd = find_player_cmd()
    if cmd is None:
        print(f"   (no audio player found; install mpg123. Audio file: {path})")
        return False
    try:
        subprocess.run(cmd + [str(path)], check=False, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"   (audio playback failed: {exc})")
        return False


def fallback_audio_for(tier: str) -> Optional[Path]:
    for candidate in (config.ASSETS_DIR / f"fallback_{tier}.mp3", config.FALLBACK_AUDIO):
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# One-call entry point
# ---------------------------------------------------------------------------
@dataclass
class Verdict:
    text: str
    source: str               # "elevenlabs" | "fallback_audio" | "text_only"
    audio_path: Optional[Path]
    reason: Optional[str]     # why we fell back, if we did
    elapsed_s: float


def deliver_verdict(result: RoundResult, player: str, play: bool = True) -> Verdict:
    text = build_verdict_text(result, player)
    print(f'   NARRATOR: "{text}"')
    t0 = time.monotonic()
    out = config.TTS_OUTPUT_DIR / f"verdict_{datetime.now():%Y%m%d_%H%M%S_%f}.mp3"
    try:
        path = synthesize(text, out)
        elapsed = time.monotonic() - t0
        if play:
            play_audio(path)
        return Verdict(text, "elevenlabs", path, None, elapsed)
    except TTSError as exc:
        reason = str(exc)
    elapsed = time.monotonic() - t0
    fallback = fallback_audio_for(result.tier)
    if fallback is not None:
        print(f"   [fallback] TTS unavailable ({reason}); playing {fallback.name}")
        if play:
            play_audio(fallback)
        return Verdict(text, "fallback_audio", fallback, reason, elapsed)
    print(f"   [fallback] TTS unavailable ({reason}); no fallback audio in assets/, text only")
    return Verdict(text, "text_only", None, reason, elapsed)
