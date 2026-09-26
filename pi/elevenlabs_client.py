"""Verdict lines + ElevenLabs text-to-speech.

deliver_verdict() is the one call main.py makes:
  1. build the verdict text from the round numbers (template set picked by round
     type, line picked by gap tier, never the same line twice in a row for one
     player in a session),
  2. try ElevenLabs TTS (REST, `requests`) with a hard total time budget
     (config.ELEVENLABS_TIMEOUT_S, default 3 s, covering connect + download),
  3. on no key / timeout / HTTP error / no audio / mp3 write error: play nothing.
     The returned Verdict has source "unavailable" and error/reason set to why.
The verdict text is always printed so the audience can read it. Nothing is read
from assets/fallback_*.mp3.
The interview questions the face rounds play (the stimulus, not verdicts) live in
POKER_QUESTION_LINES / PRESSURE_QUESTION_LINES.

The narrator's voice (The Tell): a skeptical interviewer who is also your
brutally honest friend. Dry, specific, unimpressed by claims, fair about evidence.
"""
from __future__ import annotations

import random
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

import config
from scoring import RoundResult

# ---------------------------------------------------------------------------
# Verdict templates. Placeholders: {player} {claim} {perf} {gap}, plus the raw
# reading: {ms} (Round 1 reaction time), {mg} / {peak} (legacy Steady Hands
# tremor RMS / peak, in milli-g), {smile} / {secs} (Poker Face: percent of face
# frames with a smile / whole seconds until the first smile) or {held} /
# {claimsecs} (Straight Face: seconds the face held / seconds the dial claimed).
# "over" = claimed more than delivered, "under" = sandbagged.
# Voice: a skeptical interviewer who is also your brutally honest friend. Dry,
# specific, unimpressed by claims, fair about the evidence. Rules:
#   - at most MAX_VERDICT_WORDS words once filled in (tests render every line
#     with a 10-character name and 3-digit numbers), so the line stays short to
#     say and quick to synthesize inside the 3 s budget,
#   - press hardest on "over", needle "under" (why lowball?), grudgingly
#     validate "validated",
#   - party-friendly: PG-13 at most, never about appearance or identity,
#   - at least 4 lines per key, so repeat plays don't sound canned.
# Lines that use a raw placeholder are skipped when that reading is missing
# ({secs} is missing whenever the player never smiled).
# ---------------------------------------------------------------------------
MAX_VERDICT_WORDS = 18

# Round 1: Reflex.
TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} called {claim}, hit {perf}. I checked twice. You actually know yourself. Rare.",
        "Claim {claim}, reality {perf}. {player}, I came to roast you and you gave me nothing.",
        "{ms} milliseconds, exactly as advertised. Fine, {player}. Your self-assessment survives cross-examination.",
        "{player} said {claim}, the button said {perf}. No notes. I hate that.",
        "Honest answer, honest reflexes. {player}, you'd pass a reference check. Validated.",
    ],
    "mild_over": [
        "{player} said {claim}. Their thumb said {perf}. Let's call that a generous self-review.",
        "Claimed {claim}, delivered {perf}. {player}, as a friend: you rounded up.",
        "{ms} milliseconds. Decent, {player}. Just not {claim} decent. Noted for the file.",
        "{gap} points over. {player}, your resume is slightly ahead of your reflexes.",
        "{player} claimed {claim}, scored {perf}. Close. But I did notice the rounding.",
    ],
    "spicy_over": [
        "You claimed {claim}. You took {ms} milliseconds. I'm going to need you to explain that gap.",
        "{player}, a {claim}? Reality says {perf}. Walk me through your thinking there.",
        "{ms} milliseconds, {player}. Be honest. Were you even looking at the light?",
        "Claimed {claim}, delivered {perf}. {player}, I say this as a friend: no.",
        "{player} dialed {claim}, then reacted like it was Monday morning. Reality: {perf}. Explain.",
    ],
    "delulu_over": [
        "{claim} out of 100? {ms} milliseconds. {player}, I'm not writing that down. Delulu.",
        "{player} claimed {claim}, delivered {perf}. That's not confidence, that's fiction with a dial.",
        "{gap} points of pure fiction. {player}, the cue came and went. So did your credibility.",
        "{ms} milliseconds after claiming {claim}? {player}, your friends were too polite to tell you.",
        "Claimed {claim}, scored {perf}. {player}, we need to talk about how you see yourself.",
    ],
    "mild_under": [
        "{player} claimed only {claim} and hit {perf}. Humble. Also wrong.",
        "{player}, you said {claim}, you did {perf}. Stop underselling. It's not a cute look.",
        "{ms} milliseconds from someone who dialed {claim}. Suspiciously modest, {player}.",
        "{gap} points under. {player} is quicker than they admit. Why hide it?",
    ],
    "spicy_under": [
        "You said {claim}, you delivered {perf}. {gap} points of sandbagging, {player}. What are you hiding?",
        "{player} dialed {claim}, then reacted in {ms} milliseconds. Who taught you to lowball?",
        "Claimed {claim}, scored {perf}. {player}, that's not humility, that's a negotiating tactic.",
        "{perf} from a self-declared {claim}? {player}, fire whoever writes your self-reviews.",
    ],
    "delulu_under": [
        "{player} claimed {claim}, then posted a {perf}. Reverse delulu. I don't trust it.",
        "{claim}? You reacted in {ms} milliseconds, {player}. Stop sandbagging, we can all see you.",
        "{gap} points in the wrong direction. {player}, you're either modest or running a hustle.",
        "{player} dialed {claim} and hit {perf}. Nobody lowballs that hard by accident. Reverse delulu.",
    ],
    "false_start": [
        "{player} locked in {claim} and jumped the gun. Eager. Wrong. Zero points.",
        "False start! {player} claimed {claim} and couldn't wait for the light. Zero.",
        "{player} claimed {claim} and pressed before the cue. Answering before the question. Zero.",
        "Whoa, {player}. {claim} confidence, zero patience. False start, zero points.",
    ],
    "timeout": [
        "{player} claimed {claim}, then never pressed the button. Zero. Take your time. Actually, don't.",
        "Timeout! {player} dialed {claim}, then went quiet. I'll take that as no comment. Zero.",
        "{player} claimed {claim}, and the light is still waiting. Timeout. Zero.",
        "{claim} out of 100, {player}? You didn't even press. Bold strategy. Zero.",
    ],
    # Safety net for any tier without its own lines (not produced by scoring
    # today). Line 0 is also the last resort when no line fits the reading.
    "void": [
        "That round didn't count, {player}. Reset and try again.",
        "{player}, that one's void. Shake it off and go again.",
        "No verdict this time, {player}. Reset and run it back.",
        "That round is void, {player}. I'll allow a second interview.",
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

# Poker Face (The Tell's Round 2, id 5). Claim = how unreadable their face is;
# perf 100 = never cracked a smile, 0 = smiled through the whole question.
# "over" = claimed a stone face and cracked, "under" = doubted themselves and
# stayed stony. No false starts or timeouts in this round.
POKER_TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} claimed {claim}, held a {perf}. You know exactly how readable you are. Unsettling.",
        "Claim {claim}, reality {perf}. {player}, tough question, straight answer. Validated.",
        "{player} predicted {claim} and the camera agrees. I have no follow-up questions.",
        "Smiled {smile} percent of the time, just as {player} predicted. Validated. Great in negotiations.",
        "{player} dialed {claim}, delivered {perf}. The camera has no notes. Neither do I.",
    ],
    "mild_over": [
        "{player} said {claim}. The camera said {perf}. A small tell. I saw it.",
        "Claimed {claim}, held a {perf}. Composed-ish, {player}. The ish is doing heavy lifting.",
        "{smile} percent smile from a claimed {claim}. Close, {player}. But the camera noticed.",
        "{gap} points over, {player}. Your mouth answered before you did.",
        "Cracked after {secs} seconds, {player}. Claimed {claim}. Nearly a poker face. Nearly.",
    ],
    "spicy_over": [
        "{player}, a {claim}? You smiled {smile} percent of the time. That's not a poker face, that's a tell.",
        "Claimed {claim}, cracked in {secs} seconds. {player}, please never negotiate your own salary.",
        "{player} dialed {claim}, then grinned at an interview question. Reality: {perf}. Explain yourself.",
        "Claimed {claim}, held a {perf}. {player}, your face answered the question for you.",
        "{gap} points of bluffing, {player}. The camera called it. So did I.",
    ],
    "delulu_over": [
        "{claim} for poker face? You smiled {smile} percent of the time. Certified delulu. Next candidate.",
        "{player} claimed {claim}, cracked in {secs} seconds. That's not a poker face, that's a billboard.",
        "{gap} points of pure fiction, {player}. Your face folded before the question even finished.",
        "{player} said {claim}. The camera said {perf}. As your friend: you have a tell. Several.",
        "Claimed {claim}, scored {perf}. {player}, your face keeps secrets like a group chat.",
    ],
    "mild_under": [
        "{player} claimed only {claim} and held a {perf}. More composed than you think.",
        "{gap} points under, {player}. Your face is calmer than your inner monologue.",
        "Only {smile} percent smile, {player}? You dialed {claim}. Give your poker face some credit.",
        "Claimed {claim}, held a {perf}. {player}, modest and unreadable. I'm suspicious.",
    ],
    "spicy_under": [
        "You said {claim}, you delivered {perf}. {gap} points of sandbagging, {player}. Stone cold. Own it.",
        "{player} dialed {claim}, then took that question like a seasoned diplomat. Why lowball?",
        "Claimed {claim}, scored {perf}. {player}, the camera believes in your poker face more than you do.",
        "Only {smile} percent smile from a self-declared {claim}? {player}, go negotiate something.",
    ],
    "delulu_under": [
        "{player} claimed {claim}, then gave the camera absolutely nothing. {perf}. Reverse delulu. Are you okay?",
        "{gap} points in the wrong direction. {player}, you're a card shark pretending to be a goldfish.",
        "{claim}? {smile} percent smile. {player}, stop sandbagging. The camera sees everything.",
        "{player} dialed {claim} and scored {perf}. Either deep humility or a hustle. I'm leaning hustle.",
    ],
    "void": [
        "That round didn't count, {player}. Reset and try again.",
        "{player}, that window didn't count. Face the camera and go again.",
        "No verdict this time, {player}. Reset and keep a straight face for real.",
        "That one's void, {player}. I'll allow a second interview.",
    ],
}

# Straight Face Under Pressure (The Tell's Round 3, id 6). Claim = how long they
# can keep a neutral face under rapid-fire questions (dial 100 = STRAIGHT_MAX_S);
# perf = seconds held on the same scale. "over" = cracked sooner than claimed.
STRAIGHT_TEMPLATES: dict[str, list[str]] = {
    "validated": [
        "{player} claimed {claimsecs} seconds, held {held}. Straight face, straight answer. Validated.",
        "Claim {claim}, reality {perf}. {player}, you know exactly when you crack. Unsettling.",
        "{held} seconds, as advertised. {player}, you even crack on schedule. Validated.",
        "{player} dialed {claim}, delivered {perf}. No follow-up questions. Validated.",
        "Held {held} seconds, just like {player} said. Nobody likes a self-aware person, but fine.",
    ],
    "mild_over": [
        "{player} promised {claimsecs} seconds and lasted {held}. Close. Your face blinked first.",
        "Claimed {claim}, held a {perf}. {player}, composed-ish. The ish is doing overtime.",
        "{held} seconds from a claimed {claimsecs}. Close, {player}. The camera caught the flinch.",
        "{gap} points over, {player}. The questions found a crack. A small one.",
    ],
    "spicy_over": [
        "{player} claimed {claimsecs} seconds. Your face gave up after {held}. Interesting answer.",
        "{held} seconds, {player}? You promised {claimsecs}. One hard question and there it was.",
        "Claimed {claim}, delivered {perf}. {player}, your tell showed up early and stayed.",
        "{gap} points over, {player}. Your face resigned before the questions got difficult.",
    ],
    "delulu_over": [
        "{claimsecs} seconds? You lasted {held}. {player}, that's not composure, that's a rumour about composure.",
        "{player} claimed {claimsecs} seconds and cracked in {held}. We'll keep your application on file.",
        "{gap} points of pure fiction, {player}. Your face folded on the first question. Delulu.",
        "Claimed {claim}, scored {perf}. {player}, your straight face has the shelf life of milk.",
    ],
    "mild_under": [
        "{player} claimed only {claimsecs} seconds and held {held}. Tougher than you think.",
        "{gap} points under, {player}. The questions bounced right off. Why so modest?",
        "Held {held} seconds from a claimed {claimsecs}. {player}, give your composure some credit.",
        "Claimed {claim}, held a {perf}. {player}, modest and unbothered. I'm suspicious.",
    ],
    "spicy_under": [
        "You said {claimsecs} seconds, you held {held}. {gap} points of sandbagging, {player}. Own it.",
        "{player} dialed {claim}, then sat through every question like a diplomat. Why lowball?",
        "Claimed {claim}, scored {perf}. {player}, the camera rates your composure higher than you do.",
        "{held} seconds of nothing from a self-declared {claimsecs}? {player}, you'd survive a press conference.",
    ],
    "delulu_under": [
        "{player} claimed {claimsecs} seconds, then held {held}. Reverse delulu. What else are you hiding?",
        "{gap} points in the wrong direction. {player}, stone-faced and pretending otherwise.",
        "{player} dialed {claim} and scored {perf}. Either deep humility or a hustle. I'm leaning hustle.",
        "{held} seconds of absolutely nothing. {player}, you claimed {claimsecs}. The camera sees you.",
    ],
    "void": [
        "That round didn't count, {player}. Reset and try again.",
        "{player}, that window didn't count. Face the camera and go again.",
        "No verdict this time, {player}. Reset and hold that straight face for real.",
        "That one's void, {player}. I'll allow a second interview.",
    ],
}

# round_id -> templates. Unknown round types fall back to the Round 1 set.
ROUND_TEMPLATES: dict[int, dict[str, list[str]]] = {
    1: TEMPLATES,
    2: STEADY_TEMPLATES,
    5: POKER_TEMPLATES,
    6: STRAIGHT_TEMPLATES,
}

# Placeholders that need the raw reading; lines using them are skipped when it is missing.
_RAW_PLACEHOLDERS = ("{ms}", "{mg}", "{peak}", "{smile}", "{secs}", "{held}", "{claimsecs}")


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
    first_smile_ms = result.extra.get("first_smile_ms") if result.extra else None
    raw = {
        "ms": result.actual_ms,
        "mg": result.actual if result.unit == "mg_rms" else None,
        "peak": result.extra.get("peak") if result.extra else None,
        "smile": result.actual if result.unit == "smile_pct" else None,
        "secs": first_smile_ms / 1000.0 if result.unit == "smile_pct" and first_smile_ms is not None else None,
        "held": result.actual if result.unit == "s" else None,
        "claimsecs": result.extra.get("claim_s") if result.unit == "s" and result.extra else None,
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
        smile=_fmt(raw["smile"]),
        secs=_fmt(raw["secs"]),
        held=_fmt(raw["held"]),
        claimsecs=_fmt(raw["claimsecs"]),
    )


# ---------------------------------------------------------------------------
# The face rounds' stimulus: interview questions (not verdicts, so no word
# limit, but short). Clips, when a machine has them, are
#   assets/questions/poker_XX.mp3     Poker Face: one per window, it has 6 s
#   assets/questions/pressure_XX.mp3  Straight Face: rapid fire, back to back
# Party-safe: pressure, not cruelty; never about appearance or identity.
# ---------------------------------------------------------------------------
POKER_QUESTION_LINES: list[str] = [
    "So. Why should we hire you, and not literally anyone else?",
    "What was your biggest failure? Take your time. We're recording.",
    "Your last manager described you as 'a lot'. What do you think they meant?",
    "Where do you see yourself in five years? Be honest. Is it here?",
    "What's your greatest weakness? And please don't say perfectionism.",
    "Your references didn't call us back. Any idea why?",
    "On a scale of one to ten, how much of your resume is actually true?",
    "When were you last wrong about something? A recent one, please.",
    "We found your old social media posts. Would you like to explain first?",
    "Why did you leave your last job? The real reason.",
]

PRESSURE_QUESTION_LINES: list[str] = [
    "Name your worst habit.",
    "Quick. Biggest lie you told this week?",
    "Who in this room do you trust least?",
    "Last thing you searched online?",
    "Are you smarter than your friends? Yes or no.",
    "Salary expectation? Lower.",
    "What would your ex say about you?",
    "When did you last cry?",
    "Is this really your best effort?",
    "Are you smiling? Why are you smiling?",
    "Describe yourself in one word. Not that one.",
    "Who's the favourite child in your family?",
    "What are you hiding right now?",
    "Did you lie on your application?",
    "Which friend would you leave behind?",
    "Is that your final answer?",
    "Most embarrassing app on your phone?",
    "Say something nice about yourself. Go.",
]

QUESTION_SETS: dict[str, list[str]] = {"poker": POKER_QUESTION_LINES, "pressure": PRESSURE_QUESTION_LINES}


def question_path(kind: str, number: int) -> Path:
    """assets/questions/poker_01.mp3 for ("poker", 1), and so on."""
    return config.QUESTIONS_DIR / f"{kind}_{number:02d}.mp3"


def question_plan(kind: Optional[str] = None) -> list[tuple[Path, str]]:
    """(file, text) for every question clip (both sets, or one kind), in list order."""
    kinds = [kind] if kind else list(QUESTION_SETS)
    return [(question_path(k, i), text) for k in kinds
            for i, text in enumerate(QUESTION_SETS[k], start=1)]


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


# ---------------------------------------------------------------------------
# One-call entry point
# ---------------------------------------------------------------------------
@dataclass
class Verdict:
    text: str
    source: str               # "elevenlabs" | "unavailable"
    audio_path: Optional[Path]
    reason: Optional[str]     # why TTS failed, if it did
    elapsed_s: float
    error: Optional[str] = None

    def __post_init__(self) -> None:
        # `error` is the same failure string as `reason` (None when TTS worked).
        if self.error is None:
            self.error = self.reason
        elif self.reason is None:
            self.reason = self.error


def deliver_verdict(result: RoundResult, player: str, play: bool = True,
                    memory: Optional[LastLineMemory] = None,
                    on_text: Optional[Callable[[str], None]] = None) -> Verdict:
    """Print the verdict, then speak it with ElevenLabs.

    A missing key, timeout, HTTP error, empty audio, or mp3 write error does
    not play a file and does not look in assets/. The returned Verdict has
    source "unavailable" and error/reason set. This function does not raise
    on those failures. memory defaults to SESSION_LINES, so a player doesn't
    hear the same line twice in a row. on_text (optional, e.g. the browser UI)
    gets the line before any TTS; an error in it is reported and ignored.
    """
    text = build_verdict_text(result, player, memory=SESSION_LINES if memory is None else memory)
    print(f'   NARRATOR: "{text}"')
    t0 = time.monotonic()
    out = config.TTS_OUTPUT_DIR / f"verdict_{datetime.now():%Y%m%d_%H%M%S_%f}.mp3"
    try:
        path = synthesize(text, out)
    except TTSError as exc:
        elapsed = time.monotonic() - t0
        reason = str(exc)
        print(f"   [error] TTS unavailable ({reason})", file=sys.stderr)
        return Verdict(text, "unavailable", None, reason, elapsed)
    elapsed = time.monotonic() - t0
    if on_text is not None:
        try:
            on_text(text)
        except Exception as exc:  # noqa: BLE001 - a display hook must never cost the verdict
            print(f"   [warn] verdict text hook failed: {exc}", file=sys.stderr)
    if play:
        play_audio(path)
    return Verdict(text, "elevenlabs", path, None, elapsed)
