#!/usr/bin/env python3
"""Generate the pre-recorded fallback verdict mp3s in assets/ with ElevenLabs.

The app plays these when live TTS fails or runs past its 3 s budget (see
elevenlabs_client.fallback_audio_for). The lines live in
elevenlabs_client.FALLBACK_LINES and carry no names or numbers, and the file
names come from the same code the app uses to find them.

The key, voice and model are read like the app does: ELEVENLABS_API_KEY,
ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL_ID from the environment or .env.
The key is never printed.

Examples (from the repo root):
    python pi/make_fallbacks.py --dry-run                   # what would be generated
    python pi/make_fallbacks.py                             # generate missing files
    python pi/make_fallbacks.py --round 2                   # only what Round 2 can play
    python pi/make_fallbacks.py --only 'fallback_round2_*' --force   # regenerate some
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
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                    help=f"seconds per file (default {DEFAULT_TIMEOUT_S:g})")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    plan = ec.fallback_plan(args.round)
    if args.only:
        plan = [(path, text) for path, text in plan if fnmatch.fnmatchcase(path.name, args.only)]
        if not plan:
            known = ", ".join(p.name for p, _ in ec.fallback_plan(args.round))
            print(f"error: no fallback file matches --only {args.only!r}. Known files: {known}",
                  file=sys.stderr)
            return 1

    key = config.ELEVENLABS_API_KEY
    voice, model = config.ELEVENLABS_VOICE_ID, config.ELEVENLABS_MODEL_ID
    print(f"Fallback audio -> {_rel(config.ASSETS_DIR)}/ | voice {voice} | model {model} | "
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
