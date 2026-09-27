# Brag Plan: What the Hill

## What is this app?
A live booth that locks the composure you claim, reads your face on camera, and scores the gap. This cut is anakafeel's Poker Face round: claim 68, composure 0, gap 68, score 32.

## The angle
The number on the dial and the face on the camera are not the same thing. Hyperframes builds the brag around the real webcam take, with the booth's own type (Bungee, JetBrains Mono) drawn in the composition, not borrowed from a fontless screen recording.

## Hook (first 2-3 seconds)
WHAT THE HILL, then the claim: anakafeel claimed 68.

## Key moments (the middle)
- The live camera, cropped out of the take, face box still on, while the question holds: "What would your mom say if she saw your For You page?"
- The reveal, camera still in frame: claimed 68 against composure 0, gap 68, score 32.

## Outro / punchline
"68 points of pure aura loss, anakafeel. Your face folded instantly." Then the name.

## User flow worth showing
Claim locked (68) → camera on for the question → reveal of composure 0, gap 68, score 32.

## Tone
- Preset: default
- Creative direction: booth game-show roast, camera on the face, type in the real booth fonts
- Interpretation: snappy entrances, then holds long enough to read the question and the verdict. No SaaS language. No second narrator.

## Format: landscape — 1920x1080
## Duration: 20.5

## Visual identity (from the project)
- Background: #0a0a0f
- Accent: #22e5ff (claim) and #c58bff (composure)
- Text: #f5f4f0
- Display font: Bungee (local file, font-display: block). Headlines, question, verdict, player name, WHAT THE HILL.
- Body font: JetBrains Mono (local Regular and Bold)
- Strongest visual element: the live camera with the face box, then 68 against 0

## Share copy (draft)
anakafeel claimed a 68 poker face. What the Hill read composure 0 on the live camera. Gap 68.
68 points of pure aura loss, anakafeel. Your face folded instantly.

## Audio direction
- Role: warm bed
- Music: happy-beats-business-moves-vol-11-by-ende-dot-app.mp3 (114.84 BPM). No voiceover.
- Music treatment: in at 0, volume 0.34, short fade-in, fade-out over the last 1.8s. No ducking (nothing is spoken).
- Music cue guidance: bundled preset `skills/brag/assets/music/cues/happy-beats-business-moves-vol-11-by-ende-dot-app.music-cues.md`. Strong cues used as optional locks: 3.70s (question), 8.96s (68 vs 0), 17.91s (logo). Beat grid for the two stat lines: 10.01s and 11.06s (every other beat, so each label can be read). The verdict sits on the 12.65s cue and then holds.
- Audio-reactive treatment: subtle. The hyperframes-creative extract helper is not installed in this environment. A local ffmpeg RMS envelope of the bed drives the progress bar's opacity. No waveform, no strobe.
- SFX posture: moderate, five cues, low or medium HF risk. Soft hit on the title, click as the camera opens, drop as the question lands, bell on the reveal, bell on the logo.
- Audio-coupled moments: question entrance, 68 vs 0 slam, gap then score.
- Restraint rule: do not cover the camera with type or a glow. Do not add a narrator.

## Storyboard

### Scene 1 — Hook — 2.65s
Void. WHAT THE HILL in Bungee, then "anakafeel claimed 68" with 68 in claim cyan. A small scale pulse on the title at 1.60s.
Sequential/interaction: the claim number follows the name. Hold the title ~1.5s settled (3 words) and the claim line ~1.5s (4 words).
Audio intent: bed up, one soft hit as the title lands
Audio-coupled idea: title pulse on the first strong cue
Music: bed, vol-11
Transition mood: hard → Scene 2

### Scene 2 — Face — 6.0s
The webcam crop from the live take (source 1.90s–7.90s), face box visible the whole scene. Right rail: anakafeel, POKER FACE, CLAIM 68, all in booth type. Under the camera, the question in Bungee: "What would your mom say if she saw your For You page?" Lands at 3.70s and holds past 4s settled (12 words).
Sequential/interaction: camera opens, then the question. The face is the live take, not a simulated click.
Audio intent: click as the frame opens, drop as the question lands
Audio-coupled idea: question reveal on the 3.70s cue
Music: bed
Transition mood: hard → Scene 3

### Scene 3 — Numbers — 4.0s
Same face, now a still from the take, kept on screen. Claimed 68 in cyan slams against composure 0 in purple at 8.96s. GAP 68 at 10.01s, SCORE 32 at 11.06s. Labels are short and then hold together.
Sequential/interaction: yes — 68 and 0 together, then gap, then score, on every other beat
Audio intent: bell as 68 meets 0
Audio-coupled idea: the slam on the 8.96s cue, stats on the beat grid
Music: bed
Transition mood: hard → Scene 4

### Scene 4 — Verdict — 5.26s
The numbers and the camera stay. The verdict lands at 12.65s and holds: "68 points of pure aura loss, anakafeel. Your face folded instantly." 14 words, held past 4.2s settled.
Sequential/interaction: none — one sentence, then a hold
Audio intent: the bed carries it; no extra hit on the sentence
Audio-coupled idea: none beyond the cue-aligned entrance
Music: bed
Transition mood: hard → Scene 5

### Scene 5 — Outro — 2.59s
WHAT THE HILL. "your face gives you away." Logo lands at 17.91s.
Sequential/interaction: none
Audio intent: bell under the logo, bed fading out
Audio-coupled idea: logo on the 17.91s cue
Music: fade out
Transition mood: hold

**Music mood for this video:** upbeat, kept under the type
**Audio summary:** one bed, five hits, the camera never ducked under a voice, the bar breathing with the music.
