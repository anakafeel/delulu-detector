"""Verdict lines + ElevenLabs text-to-speech, with a fallback that never blocks the demo.

deliver_verdict() is the one call main.py makes:
  1. build the verdict text from the round numbers (template set picked by round
     type, line picked by gap tier, never the same line twice in a row for one
     player in a session),
  2. try ElevenLabs TTS (REST, `requests`) with a hard total time budget
     (config.ELEVENLABS_TIMEOUT_S, default 3 s, covering connect + download),
  3. on no key / timeout / HTTP error / no audio / mp3 write error: play the pre-recorded fallback
     (assets/fallback_round<N>_<tier>.mp3, else assets/fallback_<tier>.mp3, else
     assets/fallback_verdict.mp3), and if
     that is missing too, just print the verdict text.
The verdict text is always printed so the audience can read it.
The fallback lines live in FALLBACK_LINES; pi/make_fallbacks.py turns them into mp3s.
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
# This is where the comedy lives; iterate freely, within these rules:
#   - at most MAX_VERDICT_WORDS words once filled in (tests render every line
#     with a 10-character name and 3-digit numbers), so the line stays short to
#     say and quick to synthesize inside the 3 s budget,
#   - roast "over", gently tease "under", validate "validated",
#   - party-friendly: PG-13 at most, never about appearance or identity,
#   - at least 4 lines per key, so repeat plays don't sound canned.
# Lines that use {ms} / {mg} / {peak} are skipped when that reading is missing.
# ---------------------------------------------------------------------------
MAX_VERDICT_WORDS = 18

# Round 1: Reflex.
TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} called {claim}, hit {perf}. Validated. Annoyingly self-aware.",
        "Claim {claim}, reality {perf}. {player} actually knows themselves. Validated. Rare.",
        "{player} predicted {claim} and nailed it. Calibrated. Nobody likes a know-it-all, but here we are.",
        "{ms} milliseconds, exactly as advertised. Validated, {player}. Your ego and your reflexes agree.",
        "{player} said {claim}, the button said {perf}. Validated. Frankly, a little boring.",
    ],
    "mild_over": [
        "{player} said {claim}. Their thumb said {perf}. Light delusion. We've all been there.",
        "Claimed {claim}, delivered {perf}. Slightly delulu, {player}. Nothing a little humility can't fix.",
        "{ms} milliseconds. Decent, {player}, just not {claim} decent. Mildly delulu.",
        "{gap} points over. {player}, your confidence is jogging slightly ahead of your reflexes.",
        "{player} claimed {claim}, scored {perf}. Close. Your ego rounded up.",
    ],
    "spicy_over": [
        "You claimed {claim}. You took {ms} milliseconds. Your confidence wrote a check your reflexes can't cash.",
        "{player}, a {claim}? Reality says {perf}. That's {gap} points of pure vibes.",
        "{ms} milliseconds, {player}? Even a sloth said hurry up. Spicy delulu.",
        "Claimed {claim}, delivered {perf}. {player}, that wasn't a reflex, that was a slow-motion replay.",
        "{player} dialed {claim}, then reacted like it was Monday morning. Reality: {perf}. Spicy.",
    ],
    "delulu_over": [
        "{claim} out of 100? {ms} milliseconds. Certified delulu. Please step away from the dial.",
        "{player} claimed {claim}, delivered {perf}. A psychology textbook just gained a new example.",
        "{gap} points of pure fiction. {player}, the cue came and went. So did your credibility.",
        "{ms} milliseconds after claiming {claim}? {player}, glaciers have better reflexes. Delulu.",
        "Claimed {claim}, scored {perf}. {player}, that confidence should be studied. By scientists. Delulu.",
    ],
    "mild_under": [
        "{player} claimed only {claim} and hit {perf}. Humble, but wrong.",
        "{player}, you said {claim}, you did {perf}. Give yourself some credit. Not too much.",
        "{ms} milliseconds from someone who dialed {claim}. Sneaky modest, {player}.",
        "{gap} points under. {player} is quicker than they think. Mildly humble.",
    ],
    "spicy_under": [
        "You said {claim}, you delivered {perf}. {gap} points of sandbagging, {player}. Believe in yourself.",
        "{player} dialed {claim}, then reacted in {ms} milliseconds. Who hurt you?",
        "Claimed {claim}, scored {perf}. {player}, that's not humility, that's a hustle.",
        "{perf} from a self-declared {claim}? {player}, your reflexes deserve a better publicist.",
    ],
    "delulu_under": [
        "{player} claimed {claim}, then posted a {perf}. Reverse delulu. Suspicious.",
        "{claim}? You reacted in {ms} milliseconds, {player}. Stop sandbagging, we see you.",
        "{gap} points in the wrong direction. {player}, you're a secret speed demon.",
        "{player} dialed {claim} and hit {perf}. Classic hustler move. Reverse delulu.",
    ],
    "false_start": [
        "{player} locked in {claim} and jumped the gun. Confidence so high it time-travelled.",
        "False start! {player} claimed {claim} and couldn't wait for the light. Score: zero.",
        "{player} claimed {claim} and pressed before the cue. Bold. Wrong. Zero points.",
        "Whoa, {player}! {claim} confidence, zero patience. False start, zero points.",
    ],
    "timeout": [
        "{player} claimed {claim}, then never pressed the button. Zero. Are you still with us?",
        "Timeout! {player} dialed {claim}, then forgot the button exists. Zero points.",
        "{player} claimed {claim}, and the light is still waiting for you. Timeout. Zero.",
        "{claim} out of 100, {player}? You didn't even press. Bold strategy. Zero.",
    ],
    # Safety net for any tier without its own lines (not produced by scoring
    # today). Line 0 is also the last resort when no line fits the reading.
    "void": [
        "That round didn't count, {player}. Reset and try again.",
        "{player}, that one's void. Shake it off and go again.",
        "No verdict this time, {player}. Reset and run it back.",
        "That round is void, {player}. The narrator demands a rematch.",
    ],
}

# Round 2: Steady Hands. Claim = how steady they think they are; perf 100 = rock
# still, 0 = maximum wobble. No false starts or timeouts in this round.
STEADY_TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} claimed {claim}, held a {perf}. Validated. Steady as a surgeon, and self-aware.",
        "Claim {claim}, reality {perf}. {player}, your hands and your ego agree. Validated.",
        "{player} predicted {claim} and knows exactly how shaky they are. Calibrated.",
        "{mg} milli-g, right where {player} said. Claimed {claim}. Validated. Suspiciously calm.",
        "{player} dialed {claim} and delivered {perf}. The accelerometer has no notes. Validated.",
    ],
    "mild_over": [
        "{player} said {claim}. The accelerometer said {perf}. A little wobblier than advertised.",
        "Claimed {claim}, held a {perf}. Steady-ish, {player}. Heavy emphasis on the ish.",
        "{mg} milli-g of wobble from a claimed {claim}. Close, {player}. Slightly delulu.",
        "{gap} points over, {player}. Your hands took a small creative liberty.",
        "{player} claimed {claim}, got {perf}. Mostly steady. One espresso too many.",
    ],
    "spicy_over": [
        "You claimed {claim}. Your hands wobbled {mg} milli-g. Your confidence is steady. Your hands are not.",
        "{player}, a {claim}? The accelerometer says {perf}. {gap} points of caffeine and vibes.",
        "Claimed {claim}, held a {perf}. {player}, that wasn't holding still, that was light jazz.",
        "{player} dialed {claim}, then vibrated like a phone on silent. Reality: {perf}. Spicy.",
        "Peak wobble {peak} milli-g, {player}. Claimed {claim}. Your hands were doing interpretive dance.",
    ],
    "delulu_over": [
        "{claim} for steadiness? {mg} milli-g of tremor. Hands like a leaf in a hurricane. Delulu.",
        "{player} claimed {claim}, delivered {perf}. Please never become a bomb disposal technician.",
        "{gap} points of pure fiction, {player}. That wasn't a hold, that was an earthquake drill.",
        "{player} said {claim}. The accelerometer said {perf}, then asked for a lawyer. Delulu.",
        "Claimed {claim}, peaked at {peak} milli-g. {player}, were you holding it or blending it?",
    ],
    "mild_under": [
        "{player} claimed only {claim} and held a {perf}. Steadier than you think.",
        "{gap} points under, {player}. Those hands are calmer than your inner monologue.",
        "Claimed {claim}, held a {perf}. {player}, modest and steady. Suspiciously well-adjusted.",
        "Only {mg} milli-g, {player}? You dialed {claim}. Give your hands some credit.",
    ],
    "spicy_under": [
        "You said {claim}, you delivered {perf}. {gap} points of sandbagging, {player}. Surgeon hands. Own it.",
        "{player} dialed {claim}, then held stiller than a museum statue. Were you hustling us?",
        "Claimed {claim}, scored {perf}. {player}, the accelerometer believes in you more than you do.",
        "Only {mg} milli-g from a self-declared {claim}? {player}, your hands deserve a raise.",
    ],
    "delulu_under": [
        "{player} claimed {claim}, then held like a statue for a {perf}. Reverse delulu. Are you breathing?",
        "{gap} points in the wrong direction. {player}, you're a bomb-squad natural pretending to wobble.",
        "{claim}? {mg} milli-g. {player}, stop sandbagging. The accelerometer sees everything.",
        "{player} dialed {claim} and scored {perf}. Either deep humility or a hustle. Reverse delulu.",
    ],
    "void": [
        "That round didn't count, {player}. Reset and try again.",
        "{player}, that hold didn't count. Take a breath and go again.",
        "No verdict this time, {player}. Reset and hold still for real.",
        "That one's void, {player}. The narrator demands a rematch.",
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


def word_count(text: str) -> int:
    """Words as the MAX_VERDICT_WORDS rule counts them: whitespace-separated tokens."""
    return len(text.split())


class LastLineMemory:
    """Remembers the last template spoken to each player, so the same line never
    plays twice in a row for them (as long as their tier has another line).

    Memory only, nothing persisted. main.py runs one session per process, so the
    module-level SESSION_LINES used by deliver_verdict() lasts exactly one session.
    """

    def __init__(self) -> None:
        self._last: dict[str, str] = {}

    def last(self, player: str) -> Optional[str]:
        return self._last.get(player)

    def remember(self, player: str, template: str) -> None:
        self._last[player] = template

    def clear(self) -> None:
        self._last.clear()


SESSION_LINES = LastLineMemory()


def build_verdict_text(result: RoundResult, player: str, rng: Optional[random.Random] = None,
                       memory: Optional[LastLineMemory] = None) -> str:
    """Pick a line for the result's round and tier and fill in the numbers.

    With a memory, the player's previous line is left out of the draw (unless it
    is the only line that fits) and the new pick is remembered.
    """
    rng = rng or random
    templates = templates_for(result.round_id)
    options = templates.get(template_key(result)) or templates.get("void") or TEMPLATES["void"]
    raw = {
        "ms": result.actual_ms,
        "mg": result.actual if result.unit == "mg_rms" else None,
        "peak": result.extra.get("peak") if result.extra else None,
    }
    # never say "unknown milliseconds" (or milli-g) out loud
    usable = [t for t in options if not _needs_missing_value(t, raw)] or [TEMPLATES["void"][0]]
    if memory is not None:
        fresh = [t for t in usable if t != memory.last(player)]
        usable = fresh or usable
    line = rng.choice(usable)
    if memory is not None:
        memory.remember(player, line)
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
# Pre-recorded fallback lines (played when TTS is down or too slow, so they
# carry no names and no numbers). Generate the mp3s before a demo with
#     python pi/make_fallbacks.py --dry-run     # then without --dry-run
# Key: (round_id, tier). round_id None = round-neutral file, tier None = the
# generic file. fallback_path() turns a key into the file name the app plays.
# Tier lines must fit both directions (the file is picked by tier only).
# ---------------------------------------------------------------------------
FALLBACK_LINES: dict[tuple[Optional[int], Optional[str]], str] = {
    (None, None): "The verdict is in, and it's on the screen. Read it and weep, or gloat.",
    (None, "validated"): "Validated. Your confidence and your performance actually agree. Annoyingly self-aware.",
    (None, "mild"): "A little off. Close enough to be proud, far enough to be humbled.",
    (None, "spicy"): "Spicy. Your confidence and reality just had a very public disagreement.",
    (None, "delulu"): "Certified delulu. Your confidence and reality are not on speaking terms.",
    (None, "false_start"): "False start! Confidence so high it time-travelled. No points this round.",
    (None, "timeout"): "Timeout. We waited, and waited, and waited. No points this round.",
    (2, "validated"): "Validated. Steady as a surgeon, and honest about it.",
    (2, "mild"): "Close, but not quite. Your hands and your ego almost agree.",
    (2, "spicy"): "Spicy. Your hands and your confidence told very different stories.",
    (2, "delulu"): "Certified delulu. Your hands and your self-image live in different universes.",
}

# Tiers each round can produce (and so needs a fallback for).
_FAILED_TIERS = {1: ("false_start", "timeout")}


def round_tiers(round_id: int) -> list[str]:
    return [name for _, name in config.GAP_TIERS] + list(_FAILED_TIERS.get(round_id, ()))


def fallback_path(tier: Optional[str], round_id: Optional[int] = None) -> Path:
    """File name for a fallback: generic (tier None), per tier, or per round and tier."""
    if tier is None:
        return config.FALLBACK_AUDIO
    if round_id is None:
        return config.ASSETS_DIR / f"fallback_{tier}.mp3"
    return config.ASSETS_DIR / f"fallback_round{round_id}_{tier}.mp3"


def fallback_candidates(tier: str, round_id: Optional[int] = None) -> list[Path]:
    """Where fallback_audio_for() looks, in order."""
    candidates = [fallback_path(tier), fallback_path(None)]
    if round_id is not None:
        candidates.insert(0, fallback_path(tier, round_id))
    return candidates


def fallback_plan(round_id: Optional[int] = None) -> list[tuple[Path, str]]:
    """(file, text) for every fallback line, in FALLBACK_LINES order.

    With round_id, only the files that round can ever play (its own files, the
    round-neutral files for its tiers and the generic one).
    """
    keys = list(FALLBACK_LINES)
    if round_id is not None:
        playable = {(None, None)}
        for tier in round_tiers(round_id):
            playable |= {(None, tier), (round_id, tier)}
        keys = [k for k in keys if k in playable]
    return [(fallback_path(tier, rid), FALLBACK_LINES[(rid, tier)]) for rid, tier in keys]


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
    for candidate in fallback_candidates(tier, round_id):
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


def deliver_verdict(result: RoundResult, player: str, play: bool = True,
                    memory: Optional[LastLineMemory] = None) -> Verdict:
    """Print the verdict, then speak it (ElevenLabs, else fallback audio, else text only).

    memory defaults to SESSION_LINES, so a player doesn't hear the same line twice in a row.
    """
    text = build_verdict_text(result, player, memory=SESSION_LINES if memory is None else memory)
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
