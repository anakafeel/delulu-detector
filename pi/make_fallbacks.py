#!/usr/bin/env python3
"""Generate the pre-recorded fallback verdict mp3s in assets/ with ElevenLabs.

The app plays these when live TTS fails or runs past its 3 s budget (see
elevenlabs_client.fallback_audio_for). The lines live in
elevenlabs_client.FALLBACK_LINES and carry no names or numbers, and the file
names come from the same code the app uses to find them.

With --questions it generates the face rounds' interview-question clips instead
(same voice, model and skip / --force / --only / --dry-run rules):
    elevenlabs_client.POKER_QUESTION_LINES    -> assets/questions/poker_01.mp3, ...
    elevenlabs_client.PRESSURE_QUESTION_LINES -> assets/questions/pressure_01.mp3, ...
(--round 5 / --round 6 narrows it to Poker Face / Straight Face; --jokes is the
old name of --questions.)

The key, voice and model are read like the app does: ELEVENLABS_API_KEY,
ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL_ID from the environment or .env.
The key is never printed.

Examples (from the repo root):
    python pi/make_fallbacks.py --dry-run                   # what would be generated
    python pi/make_fallbacks.py                             # generate missing files
    python pi/make_fallbacks.py --round 6                   # only what Straight Face (id 6) can play
    python pi/make_fallbacks.py --questions --dry-run       # the interview-question clips
    python pi/make_fallbacks.py --questions                 # -> assets/questions/*.mp3
    python pi/make_fallbacks.py --questions --round 6       # only the rapid-fire pressure questions
    python pi/make_fallbacks.py --only 'fallback_round5_*' --force   # regenerate some
Listen to every new file once before the demo.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import Optional

import config
import elevenlabs_client as ec

# Offline generation isn't latency-critical, so it gets more time per file than
# a live verdict (config.ELEVENLABS_TIMEOUT_S, which is not changed here).
DEFAULT_TIMEOUT_S = 30.0


def _redact(message: str, key: str) -> str:
    return message.replace(key, "***") if key else message


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(config.REPO_ROOT))
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Generate the fallback verdict mp3s in assets/ with ElevenLabs "
                    "(key, voice and model from the environment or .env).")
    ap.add_argument("--dry-run", action="store_true",
                    help="print each file and its text, generate nothing (no key needed)")
    ap.add_argument("--only", metavar="GLOB",
                    help="only files whose name matches, e.g. 'fallback_round2_*'")
    ap.add_argument("--force", action="store_true",
                    help="regenerate files that already exist (default: skip them)")
    ap.add_argument("--round", type=int, choices=sorted(config.ROUND_NAMES), default=None,
                    help="only the files this round can play (default: all)")
    ap.add_argument("--questions", "--jokes", dest="questions", action="store_true",
                    help="generate the interview-question clips (assets/questions/poker_XX.mp3 and "
                         "pressure_XX.mp3) instead of the fallback verdicts; with --round 5 or 6 only "
                         "that round's set (--jokes is the old name)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                    help=f"seconds per file (default {DEFAULT_TIMEOUT_S:g})")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    question_kinds = {None: None, 5: "poker", 6: "pressure"}
    if args.questions and args.round not in question_kinds:
        parser.error("--questions: only --round 5 (Poker Face) or --round 6 (Straight Face) have questions")
    full_plan = (ec.question_plan(question_kinds[args.round]) if args.questions
                 else ec.fallback_plan(args.round))
    kind = "question" if args.questions else "fallback"
    plan = full_plan
    if args.only:
        plan = [(path, text) for path, text in plan if fnmatch.fnmatchcase(path.name, args.only)]
        if not plan:
            known = ", ".join(p.name for p, _ in full_plan)
            print(f"error: no {kind} file matches --only {args.only!r}. Known files: {known}",
                  file=sys.stderr)
            return 1

    key = config.ELEVENLABS_API_KEY
    voice, model = config.ELEVENLABS_VOICE_ID, config.ELEVENLABS_MODEL_ID
    label, folder = (("Question clips", config.QUESTIONS_DIR) if args.questions
                     else ("Fallback audio", config.ASSETS_DIR))
    print(f"{label} -> {_rel(folder)}/ | voice {voice} | model {model} | "
          f"ELEVENLABS_API_KEY {'set' if key else 'NOT set'}")

    todo = []
    for path, text in plan:
        if path.exists() and not args.force:
            print(f"skip           {path.name} (exists; --force to regenerate)")
        else:
            todo.append((path, text))
    skipped = len(plan) - len(todo)

    if args.dry_run:
        for path, text in todo:
            print(f'would generate {path.name}: "{text}"')
        print(f"Dry run: {len(todo)} to generate, {skipped} skipped. Nothing was written.")
        return 0

    if not todo:
        print(f"Nothing to do: {skipped} file(s) already exist (use --force to regenerate).")
        return 0
    if not key:
        print("error: ELEVENLABS_API_KEY is not set (environment or .env at the repo root). "
              "Nothing generated. Use --dry-run to preview without a key.", file=sys.stderr)
        return 2

    done = 0
    for path, text in todo:
        part = path.with_name(path.name + ".part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            ec.synthesize(text, part, api_key=key, voice_id=voice, model_id=model,
                          timeout_s=args.timeout)
            part.replace(path)
        except (ec.TTSError, OSError) as exc:
            part.unlink(missing_ok=True)
            print(f"error: could not generate {path.name}: {_redact(str(exc), key)}", file=sys.stderr)
            print(f"Stopped after {done} generated, {skipped} skipped. Fix the problem and run "
                  "again; files already written are kept and skipped.", file=sys.stderr)
            return 1
        done += 1
        print(f'wrote          {path.name} ({path.stat().st_size} bytes): "{text}"')

    print(f"Done: {done} generated, {skipped} skipped. Listen to each new file once before the demo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
