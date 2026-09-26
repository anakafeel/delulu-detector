"""Verdict lines + ElevenLabs text-to-speech, with a fallback that never blocks the demo.

deliver_verdict() is the one call main.py makes:
  1. build the verdict text from the round numbers (template set picked by round
     type, line picked by gap tier),
  2. try ElevenLabs TTS (REST, `requests`) with a hard total time budget
     (config.ELEVENLABS_TIMEOUT_S, default 3 s, covering connect + download),
  3. on no key / timeout / HTTP error / no audio / mp3 write error: play the pre-recorded fallback
     (assets/fallback_round<N>_<tier>.mp3, else assets/fallback_<tier>.mp3, else
     assets/fallback_verdict.mp3), and if
     that is missing too, just print the verdict text.
The verdict text is always printed so the audience can read it.
"""
from __future__ import annotations

import random
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

import config
from scoring import RoundResult

# ---------------------------------------------------------------------------
# Verdict templates. Placeholders: {player} {claim} {perf} {gap}, plus the raw
# reading: {ms} (Round 1 reaction time) or {mg} / {peak} (Round 2 tremor RMS /
# peak, in milli-g). "over" = claimed more than delivered, "under" = sandbagged.
# This is where the comedy lives; iterate freely.
# ---------------------------------------------------------------------------
# Round 1: Reflex.
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
        "False start! {player} claimed {claim} and couldn't even wait for the light. Score: zero.",
    ],
    "timeout": [
        "{player} claimed {claim}, then never pressed the button. Score: zero. Are you still with us?",
    ],
    # Safety net for any tier without its own lines (not produced by scoring today).
    "void": [
        "That round didn't count, {player}. Reset and try again.",
    ],
}

# Round 2: Steady Hands. Claim = how steady they think they are; perf 100 = rock
# still, 0 = maximum wobble. No false starts or timeouts in this round.
STEADY_TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} claimed {claim} for steadiness and delivered {perf}. A gap of {gap}. Validated. Steady as a surgeon, and self-aware about it.",
        "Claim {claim}, reality {perf}. {player}, your hands and your ego agree. Validated. Suspiciously calm.",
        "{gap} points off. {player} knows exactly how shaky they are. Calibrated. Nobody likes a know-it-all, but the accelerometer doesn't lie.",
    ],
    "mild_over": [
        "{player} said {claim}. The accelerometer said {perf}. A {gap} point gap. A little wobblier than advertised.",
        "Claimed {claim}, held a {perf}. Slightly delulu, {player}. Steady-ish. Heavy emphasis on the ish.",
    ],
    "spicy_over": [
        "You claimed {claim}. Your hands wobbled {mg} milli-g, which is a {perf}. That's a {gap} point gap. Your confidence is steady. Your hands are not.",
        "{player}, a {claim}? Reality scored your steadiness {perf}. {gap} points of caffeine and vibes.",
    ],
    "delulu_over": [
        "{claim} out of 100 for steadiness? {mg} milli-g of tremor. That is a {gap} point gap. Hands like a leaf in a hurricane. Certified delulu.",
        "{player} claimed {claim} and delivered {perf}. A {gap} point gap. Please never become a bomb disposal technician.",
    ],
    "mild_under": [
        "{player} claimed only {claim} and held a {perf}. Underconfident by {gap}. Steadier than you think.",
    ],
    "spicy_under": [
        "You said {claim}, you delivered {perf}. {gap} points of sandbagging, {player}. Those are surgeon hands. Own it.",
    ],
    "delulu_under": [
        "{player} claimed {claim} and then held still like a statue for a {perf}. A {gap} point gap in the wrong direction. Reverse delulu. Are you even breathing?",
    ],
    "void": [
        "That round didn't count, {player}. Reset and try again.",
    ],
}

# round_id -> templates. Unknown round types fall back to the Round 1 set.
ROUND_TEMPLATES: dict[int, dict[str, list[str]]] = {
    1: TEMPLATES,
    2: STEADY_TEMPLATES,
}

# Placeholders that need the raw reading; lines using them are skipped when it is missing.
_RAW_PLACEHOLDERS = ("{ms}", "{mg}", "{peak}")


def templates_for(round_id: int) -> dict[str, list[str]]:
    return ROUND_TEMPLATES.get(round_id, TEMPLATES)


def _fmt(x: Optional[float]) -> str:
    return "unknown" if x is None else str(int(round(x)))


def template_key(result: RoundResult) -> str:
    if result.tier in ("validated", "false_start", "timeout", "void"):
        return result.tier
    direction = "under" if result.direction == "under" else "over"
    return f"{result.tier}_{direction}"


def _needs_missing_value(line: str, values: dict) -> bool:
    return any(p in line and values[p[1:-1]] is None for p in _RAW_PLACEHOLDERS)


def build_verdict_text(result: RoundResult, player: str, rng: Optional[random.Random] = None) -> str:
    rng = rng or random
    templates = templates_for(result.round_id)
    options = templates.get(template_key(result)) or templates.get("void") or TEMPLATES["void"]
    raw = {
        "ms": result.actual_ms,
        "mg": result.actual if result.unit == "mg_rms" else None,
        "peak": result.extra.get("peak") if result.extra else None,
    }
    line = rng.choice(options)
    if _needs_missing_value(line, raw):
        # never say "unknown milliseconds" (or milli-g) out loud
        line = next((t for t in options if not _needs_missing_value(t, raw)), TEMPLATES["void"][0])
    return line.format(
        player=player,
        claim=_fmt(result.claim),
        perf=_fmt(result.performance),
        gap=_fmt(result.gap),
        ms=_fmt(raw["ms"]),
        mg=_fmt(raw["mg"]),
        peak=_fmt(raw["peak"]),
    )


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
class TTSError(Exception):
    pass


def _socket_timeouts(remaining_s: float) -> tuple[float, float]:
    """(connect, read) timeouts for requests, carved out of the remaining budget.

    They add up to remaining_s, so connecting plus waiting for the first byte
    can't outrun the budget at the socket level either. The read timeout is
    per socket read, so synthesize() also enforces the deadline on the wall
    clock.
    """
    connect_s = remaining_s / 2.0
    return connect_s, remaining_s - connect_s


def _fetch_audio(url: str, params: dict, headers: dict, payload: dict,
                 deadline: float, timeout_s: float, cancel: threading.Event) -> bytes:
    """Do the HTTP request and download. Runs in a worker thread (see synthesize)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TTSError(f"no time left in the {timeout_s}s budget")
    try:
        resp = requests.post(url, params=params, headers=headers, json=payload,
                             timeout=_socket_timeouts(remaining), stream=True)
        with resp:
            if resp.status_code != 200:
                raise TTSError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            chunks = []
            for chunk in resp.iter_content(chunk_size=8192):
                if cancel.is_set() or time.monotonic() > deadline:
                    raise TTSError(f"download exceeded {timeout_s}s budget")
                chunks.append(chunk)
    except requests.RequestException as exc:
        raise TTSError(f"{type(exc).__name__}: {exc}") from exc
    return b"".join(chunks)


def synthesize(
    text: str,
    out_path: Path,
    api_key: Optional[str] = None,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    timeout_s: Optional[float] = None,
) -> Path:
    """Call ElevenLabs TTS and write an mp3. Raises TTSError on any failure.

    Arguments left as None are read from config at call time.

    timeout_s (default config.ELEVENLABS_TIMEOUT_S) is a TOTAL wall-clock
    budget for DNS, connect, waiting for the first byte and the download:
      - requests gets (connect, read) socket timeouts split from the budget,
      - the deadline is checked between streamed chunks,
      - the request runs in a daemon worker thread and we stop waiting for it
        when the budget runs out, so a slow DNS lookup, a slow first byte or a
        server that trickles bytes can't hold up the verdict. An abandoned
        worker is told to stop and dies on its own socket timeouts.
    """
    api_key = config.ELEVENLABS_API_KEY if api_key is None else api_key
    voice_id = voice_id or config.ELEVENLABS_VOICE_ID
    model_id = model_id or config.ELEVENLABS_MODEL_ID
    timeout_s = config.ELEVENLABS_TIMEOUT_S if timeout_s is None else timeout_s
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY not set")

    url = f"{config.ELEVENLABS_BASE_URL}/v1/text-to-speech/{voice_id}"
    params = {"output_format": config.ELEVENLABS_OUTPUT_FORMAT}
    headers = {"xi-api-key": api_key, "Content-Type": "application/json",
               "Accept": "audio/mpeg"}
    payload = {"text": text, "model_id": model_id}
    deadline = time.monotonic() + timeout_s
    cancel = threading.Event()
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["audio"] = _fetch_audio(url, params, headers, payload,
                                            deadline, timeout_s, cancel)
        except BaseException as exc:  # handed to the caller below
            outcome["error"] = exc

    thread = threading.Thread(target=worker, name="elevenlabs-tts", daemon=True)
    thread.start()
    thread.join(max(0.0, deadline - time.monotonic()))
    if thread.is_alive():
        cancel.set()
        raise TTSError(f"TTS exceeded {timeout_s}s budget")

    error = outcome.get("error")
    if isinstance(error, TTSError):
        raise error
    if error is not None:
        raise TTSError(f"{type(error).__name__}: {error}") from error
    audio = outcome.get("audio", b"")
    if not audio:
        raise TTSError("empty audio response")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
    except OSError as exc:
        raise TTSError(f"could not write {out_path}: {exc}") from exc
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


def fallback_audio_for(tier: str, round_id: Optional[int] = None) -> Optional[Path]:
    candidates = [config.ASSETS_DIR / f"fallback_{tier}.mp3", config.FALLBACK_AUDIO]
    if round_id is not None:
        candidates.insert(0, config.ASSETS_DIR / f"fallback_round{round_id}_{tier}.mp3")
    for candidate in candidates:
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
    fallback = fallback_audio_for(result.tier, result.round_id)
    if fallback is not None:
        print(f"   [fallback] TTS unavailable ({reason}); playing {fallback.name}")
        if play:
            play_audio(fallback)
        return Verdict(text, "fallback_audio", fallback, reason, elapsed)
    print(f"   [fallback] TTS unavailable ({reason}); no fallback audio in assets/, text only")
    return Verdict(text, "text_only", None, reason, elapsed)
