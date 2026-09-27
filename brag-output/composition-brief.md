# Hyperframes Composition Brief: What the Hill

## Objective
A 21s landscape brag of one real Poker Face round. The picture is the live booth recording. Do not recreate the UI and do not cover the camera.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 21 seconds

## Source Material
- Project root: `/home/saim/linuxworkspace/delulu-detector`
- Primary files read: README.md, frontend/src/App.jsx, frontend/src/index.css, frontend/index.html
- Product name: What the Hill
- Tagline / strongest claim: Your face gives you away.
- Key UI or visual moment to recreate: do not recreate. Play `assets/take.mp4`, the live round.
- Copy that must appear verbatim (already burned into the recording):
  - What would your mom say if she saw your For You page?
  - 68 points of pure aura loss, anakafeel. Your face folded instantly.

## Creative Direction
- Tone preset: default
- Creative direction: the live gap, dry
- Interpretation: the booth is the frame. Motion is the round itself plus one thin progress bar so the timeline is not frozen.
- Angle: claim 68, face on camera, composure 0.
- Hook: camera still off, then the lock.
- Outro / punchline: 68 against 0, gap 68.
- Avoid:
  - Generic SaaS language
  - A fake preview frame over the camera
  - The old 72-vs-36 preview

## Visual Identity
- Background: #0a0a0f
- Text: #f5f4f0
- Accent: #22e5ff
- Display font: Bungee (already in the recording)
- Body font: JetBrains Mono (already in the recording)
- Visual references from the project: void background, cyan claim, the face box

## Storyboard
1. Claim — 1.5s — dial, camera off, name anakafeel
2. Face — 6.5s — real camera, claim 68, composure 2, the question
3. Reveal — 13s — 68 vs 0, gap 68, the verdict

## Audio
- Audio role: warm bed
- Audio arc: bed, duck for the question, bed, duck for the verdict, fade
- Music: assets/music/bed.wav (the existing 20s bed)
- Music treatment: about 0.28, ducked to 0.10 under the two voices, fade across the last two seconds
- Music cue guidance: natural timing. Cues would move the real lock and the real reveal. Ignored on purpose.
- Audio-reactive treatment: skipped. Extraction was not wired, and a glow would cover the face.
- Audio-coupled moments:
  - face — the round's ElevenLabs question
  - reveal — the round's ElevenLabs verdict
- SFX selection guidance: one click at the lock, one soft impact when the reveal cuts in. Low high-frequency risk.
- Exact SFX: interface/click_001.ogg at 1.45s, impact/impactSoft_medium_000.ogg at 8.0s
- Audio files: copied into `brag-output/composition/assets/`

## Hyperframes Instructions
Play `assets/take.mp4` full frame, muted. Separate audio tracks for the bed, the question, and the verdict. A 4px claim-colored bar scales across the bottom for the whole 21s so the seek sweep is not static. No title card over the camera.

## Round logged
Player anakafeel. Claim 68. Composure 0. Gap 68. Score 32. Tier delulu. sessions.db row 33. Face in every frame of the window.
