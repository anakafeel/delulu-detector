# Hyperframes Composition Brief: What the Hill

## Objective
Create a short launch-style brag video for What the Hill. The picture is the real Poker Face camera take. The type is drawn by Hyperframes in the booth fonts, loaded locally.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 20.5 seconds

## Source Material
- Project root: `/home/saim/linuxworkspace/delulu-detector`
- Primary files read: `README.md`, `frontend/index.html`, `frontend/src/index.css`
- Footage: `brag-output/composition/assets/take.mp4` (21s live booth screencast). The camera window used in the cut is cropped from that file (source 1.90s–7.90s) into `assets/face.mp4`, plus a still at 6.40s (`assets/face.jpg`). Do not use `brag-output/brag.mp4`, `npm run dev:preview`, or `?preview=1`.
- Product name: What the Hill
- Tagline / strongest claim: Your face gives you away.
- Key UI or visual moment to recreate: the live webcam with the face box, then claim 68 against composure 0.
- Copy that must appear verbatim:
  - What would your mom say if she saw your For You page?
  - 68 points of pure aura loss, anakafeel. Your face folded instantly.
  - anakafeel
  - Poker Face
  - claim 68, composure 0, gap 68, score 32
  - WHAT THE HILL

## Creative Direction
- Tone preset: default
- Creative direction: booth game-show roast, camera on the face, booth fonts
- Interpretation: fast entrances, long holds. The joke is the gap, not a caption about the gap.
- Angle: the dial said 68 and the camera said 0. Show the face the whole way through the verdict.
- Hook: WHAT THE HILL, then anakafeel claimed 68.
- Outro / punchline: the verdict, then WHAT THE HILL.
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals
  - A full-screen replay of the fontless booth UI
  - Type laid on top of the camera
  - Google Fonts at render time
  - Voiceover

## Visual Identity
- Background: #0a0a0f
- Text: #f5f4f0
- Accent: #22e5ff claim, #c58bff composure
- Display font: Bungee, file `assets/fonts/Bungee-Regular.ttf`, `@font-face` with `font-display: block`. Used for WHAT THE HILL, the question, the verdict, the player name, and the big numbers.
- Body font: JetBrains Mono, `assets/fonts/JetBrainsMono-Regular.otf` and `JetBrainsMono-Bold.otf`, `font-display: block`. Used for labels (CLAIM, COMPOSURE, GAP, SCORE, POKER FACE).
- Visual references from the project: void field, claim cyan, reality purple, the webcam with the OpenCV face box.

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. Hook — 2.65s — WHAT THE HILL, anakafeel claimed 68
2. Face — 6.0s — live camera, claim 68, the question in Bungee
3. Numbers — 4.0s — 68 vs 0, gap 68, score 32, camera still visible
4. Verdict — 5.26s — the verdict sentence held, camera still visible
5. Outro — 2.59s — WHAT THE HILL

## Audio
- Audio role: warm bed
- Audio arc: bed from the top, hits on the title, the camera, the question, the reveal, and the logo, fade under the outro
- Music: `happy-beats-business-moves-vol-11-by-ende-dot-app.mp3`
- Music treatment: volume 0.34, fade-in 0.4s, fade-out 1.8s, no ducking
- Music cue guidance: bundled preset at `/home/saim/tools/brag/skills/brag/assets/music/cues/happy-beats-business-moves-vol-11-by-ende-dot-app.music-cues.md` (also the matching JSON). Tempo 114.84 BPM. Locks: question 3.70s, 68 vs 0 at 8.96s, logo 17.91s. Stat beat grid: gap 10.01s, score 11.06s. Verdict entrance 12.65s then a reading hold.
- Audio-reactive treatment: subtle. Official hyperframes-creative `extract-audio-data.py` is not in this install. Local ffmpeg RMS (0.25s steps, normalized) is `assets/energy.js` and drives only the progress bar opacity. No waveform.
- Audio-coupled moments:
  - question — beat reveal
  - 68 vs 0 — beat reveal
  - gap, then score — beat grid
  - logo — final cue
- SFX selection guidance: low and medium HF risk only. `impact/impactSoft_medium_001.ogg` on the title, `interface/click_003.ogg` as the camera opens, `interface/drop_002.ogg` on the question, `impact/impactBell_heavy_000.ogg` on the reveal, `impact/impactBell_heavy_003.ogg` on the logo. See `/home/saim/tools/brag/skills/brag/assets/sfx/sfx-analysis.md`.
- SFX analysis guidance: `/home/saim/tools/brag/skills/brag/assets/sfx/sfx-analysis.md`
- Exact SFX choice: the five files above, timed to the entrance of each motion.
- Audio files: copied into `brag-output/composition/assets/music/` and `assets/sfx/`.

## Hyperframes Instructions
Load the composition-building Hyperframes domain skills — `hyperframes-core` (composition contract + `data-*` timing), `hyperframes-animation` (motion), `hyperframes-creative` (design spec, beats, audio-reactive), `hyperframes-keyframes` (seek-safe keyframes), and `hyperframes-cli` (lint/check/render). /brag is its own workflow: do not enter the `hyperframes` entry-point intent interview and do not route into its generic promo / launch-video workflow. Prefer native Hyperframes conventions over anything in `/brag`.

Requirements:
- Show the real camera from the take. Keep it visible through the verdict.
- Render the question and the verdict in Bungee via local `@font-face`. Do not depend on fonts.googleapis.com.
- Keep all text readable, on void, not on the camera.
- Keep the video within 15-25 seconds (20.5s).
- Include the music and the five SFX.
- Treat music cues as optional timing hints. The three beat-locked tweens are marked in the composition.
- Run `hyperframes check` before render.
