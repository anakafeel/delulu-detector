# The Tell — PRD

Sep 26, 2026 · @Saim

## Overview & Problem

Most people are bad at knowing how good they actually are at something in the moment, a documented phenomenon studied under metacognitive calibration (the popular shorthand people know is the Dunning-Kruger effect, though the real research area is broader: does your confidence match your actual ability). That gap matters most right before something high-stakes, an interview, a pitch, a hard ask, where the person walking in has no real feedback on how they'll actually come across.

**The Tell** is a physical arcade-style party game built for Hack the Hill III that makes this gap visible, funny, and immediate. A player states how confident they feel about coming across calm and composed in a specific high-stakes moment on a physical dial, then performs a short mock version of that moment on camera while OpenCV reads facial signals nobody consciously controls, blink rate, mouth tension, stillness, expression change. An ElevenLabs-voiced narrator calls out the gap between the claim and what the face actually showed, in real time.

## What This Actually Is (Honest Framing)

This matters enough to state plainly, because it's easy to oversell and a judge will catch it if we do.

**What it doesn't do:** it does not measure real interview or pitch performance, it does not diagnose anxiety or any clinical condition, and it does not help anyone actually land the interview. One play doesn't improve anyone's real-world composure, and a Haar cascade or a frame-difference heuristic is not a validated psychological instrument.

**What it actually is:** a live demonstration of a real pattern, people are consistently bad at predicting how readable their own stress or overconfidence is to someone watching, because nobody gets real-time feedback on their own face during an actual high-stakes moment. "The tell" is just a measurable facial signal, movement, tension, blink rate, compared against a self-report. That's the honest phenomenon being shown, and it's genuinely interesting on its own.

**Why it's still a good pitch:** the entertainment value comes from watching confident people get called out by their own face in real time, the same basic appeal as a lie-detector party game. That's a legitimate, honest hook. It does not need an inflated "this will get you the job" claim to be worth building or demoing.

**The pitch line to actually use:** "we're not claiming this will help you land the interview, we're demonstrating that your face gives off signals you don't control and can't accurately predict, and making that visible live is funny, and a little uncomfortable." Say exactly this, don't reach further, it holds up under a follow-up question and an inflated version doesn't.

## Goals & Non-Goals

**Goals**

- Ship one fully working loop end to end (dial claim + live OpenCV facial read + roast-or-affirm ElevenLabs verdict) before anything else.
- Frame every round around a real high-stakes moment, an interview question, a pitch, a hard ask, not an abstract game show. That framing is what makes the gap land as "your face gives you away" instead of a generic sensor toy.
- Keep hardware to what's confirmed on hand and load-bearing for that framing: dial, button, webcam. Nothing added just because a sensor happens to be available.
- Demonstrate, live, that repeated rounds with instant feedback measurably shrink a player's prediction gap, this is the actual, honest, demonstrable claim.

**Non-Goals**

- Does not train anyone to interview better, negotiate better, or manage anxiety. Not a clinical or therapeutic tool, and that framing should not appear in the pitch.
- Not a biometric identification or storage tool. No face data is matched to identity or kept past the session, frames are processed live and discarded.
- Cut the accelerometer (Steady Hands) and ultrasonic (Retreat) rounds entirely. Tremor and flinch-distance don't connect to the interview-confidence story and aren't facial expression, they diluted the concept into a generic sensor grab-bag rather than one focused idea.
- Not trying to use every sensor on hand. UV, air quality, and barometer are deliberately excluded and called out as such in the pitch.

## Core Concept & Game Loop

Every round follows the same three-step loop:

1. **Predict** — player sets a 0-100 confidence claim on the rotary dial for a specific claim tied to a mock high-stakes moment about to happen ("I can stay completely composed answering this").
2. **Perform** — player does a short mock version of that moment on camera (a rapid-fire tough question, holding a poker face under pressure), while OpenCV reads their face live.
3. **Reveal** — the system computes the gap between the claim and the measured "tell," and ElevenLabs delivers a roast-or-affirm verdict, affirming a real match, escalating roast levels for a bigger gap, whether that means overconfidence or an undersell.

Playing multiple rounds back to back is the actual demo moment: the gap should visibly shrink round over round as the player learns their own tells. That's the real, honest, demonstrable claim behind the game, not a promise to fix nervousness or land the interview.

## The Tell: Rounds

| Round | Sensor(s) | Predict | Reality Check |
| --- | --- | --- | --- |
| 1. Reflex Round (build first, ships alone if nothing else lands) | Rotary dial + button | Claimed reaction speed under pressure (0-100) | Real reaction time in ms from cue to button press |
| 2. Poker Face Round (OpenCV, local, no API) | Rotary dial + webcam (OpenCV Haar cascade smile detector) | Claimed poker-face confidence going into a mock tough interview question (0-100) | Whether a smile, laugh, or visible reaction is detected in a short window |
| 3. Straight Face Under Pressure (OpenCV, local, no API) | Rotary dial + webcam (frame-difference on mouth/face region over time) | Claimed seconds they can hold a neutral, composed expression under a rapid-fire question | Actual seconds elapsed until detectable expression change |
| 4. Reveal Cam (stretch, no scoring impact) | Webcam | n/a | Auto-captures a photo at the exact reveal moment as a shareable meme, no biometric analysis |

**Cut this pivot:** Steady Hands Round (accelerometer, tremor while holding still) and Retreat Round (ultrasonic, flinch-back distance). Both measured physical steadiness rather than facial expression, and neither connected to the interview-confidence story, they were dropped to keep the concept to one clear thing: your face gives you away.

**Scoring:** `gap = abs(claimed_confidence_normalized − actual_performance_normalized)`. Smaller gap = higher score. A running leaderboard tracks best gap, worst ("most delulu") gap, and total rounds played per person.

**Considered and dropped:** a "Color Blind Spot" OpenCV round (guess a color, camera reads the real RGB value) was considered as a callback to the color-detection projects that have historically won at Hack the Hill, but it doesn't fit the claim-vs-reality format, colorblindness isn't a confidence thing, people generally already know if they see color differently, so there's no real "delulu" gap to reveal. Dropped rather than forced in.

**Build note:** the OpenCV rounds run fully local via built-in Haar cascades and frame-differencing, no external API, no network dependency, no added latency risk during the live demo (unlike the ElevenLabs call, which only fires once for the verdict). Build these only after Round 1 is fully working end to end.

## Technical Architecture

**Data flow:** Arduino Uno reads the dial and button → sends `{claim, actual, round_id}` over serial to a Raspberry Pi 4. For Rounds 2-3 the Pi also runs OpenCV against the webcam feed live (face detection, Haar cascade smile classifier, frame-difference over the mouth/face region) to compute the actual "tell" value. The Pi computes the gap and score, appends a row to the session log, calls ElevenLabs with the numbers to generate a roast-or-affirm verdict, and plays the audio through a speaker.

**Components**

- Arduino Uno: dial + button only, this pivot drops the accelerometer and ultrasonic wiring entirely.
- Raspberry Pi 4: serial listener, OpenCV pipeline for the face-reading rounds, scoring logic, session log, ElevenLabs API calls.
- ElevenLabs: generates the roast-or-affirm verdict line from a short prompt template fed the claim, actual result, and gap size. The prompt should lean into a skeptical-interviewer, brutally-honest-friend tone, that voice is the emotional core of the pivot.
- Session log: simple timestamped table (name/session id, round, claim, actual, gap, score), the natural hook for the Tiger Data mini-challenge if there's time left over.

**Build order:** get Round 1's dial + button reading real values over serial first, confirm the pipeline end to end with a hardcoded ElevenLabs call, before wiring the OpenCV rounds.

## Frontend

Display-only, no user input required, this is a live status screen shown next to the physical rig during play and judging, not an interactive UI. Owner is building this with a design skill/tool directly, this section exists so the rest of the team knows what data it needs to receive.

**Required to show, live, updating each round:**

- **The live webcam feed itself, with the OpenCV detection overlay drawn on it** (face box, smile-detector confidence, or a marker each time expression change is registered). This is the single most important frontend requirement in this pivot, the audience needs to see the detector actually watching a face in real time, not just trust a final number.
- current round name/number
- the claim (dial value) and the actual measured tell score, side by side
- the computed gap and the verdict text (readable along with the audio, useful if the room's loud)
- running leaderboard: best gap, worst ("most delulu") gap, total rounds played
- gap-over-rounds line chart, this is the calibration-curve visual from the judge assessment, it's the cheap technical-execution/learning booster, don't cut it

**Data contract:** the Pi script should write each round's result (round id, claim, actual, gap, verdict text, timestamp) somewhere the frontend can read, a local JSON file or a lightweight local API endpoint both work. The live video overlay is a separate, higher-bandwidth stream (an MJPEG endpoint or a per-frame image push from the Pi's OpenCV loop), whoever builds the Pi backend and whoever builds the frontend should agree on both shapes early so they're not blocked on each other.

**Scope reminder:** no user interaction needed (no buttons, no forms), it only needs to render what the backend produces. Keep it that simple even if the visual polish goes further.

## Hardware & Sensor Mapping

**Used, and why each one earns its place:**

- Rotary angle sensor: the universal "claim" input for every round.
- Button: reaction-time trigger for Round 1.
- Webcam (Logitech, USB, connects to the Pi not the Arduino): confirmed on hand, plug-and-play with OpenCV via `cv2.VideoCapture()`, powers Rounds 2-3 (Poker Face Round, Straight Face Under Pressure), also usable for the stretch Reveal Cam snapshot. This is now the core sensor, everything the pivot is about runs through it.
- PS4 controller trigger: optional Round 4 (decisiveness via trigger-pull speed), stretch only.

**Deliberately not used, and why:**

- Accelerometer and ultrasonic sensor, cut this pivot. They measure physical steadiness and flinch distance, not facial expression, and don't connect to the interview-confidence story the game is now telling.
- UV sensor, air quality sensor, barometer, these measure the room, not the player. There's no natural "predict yourself" moment for ambient conditions, so they're left out rather than forced in. Worth one line in the pitch: it shows restraint, not a gap in ability.

## Target Audience (Honest)

Worth being just as direct about this as about the product claim. Tonight's actual audience is not someone prepping for a real interview tomorrow, and the pitch should not imply otherwise.

- **Hackathon judges scoring the rubric.** They want a working, understandable idea with a real technical decision behind it (why webcam-only, why these two OpenCV heuristics, why the accelerometer and ultrasonic rounds were cut). That's who most of the polish should serve.
- **Other hackers and attendees walking the floor.** A 60-90 second, funny, self-contained interaction is what turns into booth traffic and word of mouth, not a tool anyone installs afterward.
- **The team, honestly.** This is the version of the idea that's actually finishable and demoable cleanly by tonight, which is worth more than a more ambitious version that doesn't work live.

What this is explicitly not for tonight: an actual interview-prep tool for someone with a real interview coming up. Two Haar cascade heuristics on generic lighting are a fun, honest demonstration of a real effect, not calibrated coaching. If a judge asks "would I use this before my real interview," the honest answer is no, not yet, and saying so plainly is a better answer than reaching for a bigger claim.

## Target Prize Categories

| Category | How this project qualifies |
| --- | --- |
| **General Challenge — Best Overall** (primary target) | Focused, working, funny, clean 5-minute demo; winner also receives the ElevenLabs prize |
| **Best Hardware Hack** | Dial, button, and a live OpenCV pipeline against a real webcam feed, smaller hardware footprint after this pivot, but the sensor fusion that remains (dial input + live face-reading) is central to the concept, not decorative |
| **Best Use of ElevenLabs** | The roast-or-affirm voice is the core emotional payoff of every round, not bolted on |
| **Best FOSS Project** | Public repo with an open license, near-zero extra effort |
| **Best Educational Project (MathemaTech)** | Legitimate framing around metacognitive calibration and confidence-feedback loops, demonstrated live by showing the gap shrink across rounds |
| **Best Use of Tiger Data** (optional, only if time allows) | Session log (claim/actual/gap per round) is naturally a timestamped Postgres table, don't force this if it costs build time |

**Deliberately not targeting:** CGI Challenge (team decision, different project shape entirely), Civic Tech (see below), Solana/Gemini/Auth0/Vultr/GoDaddy (no natural fit, would read as forced).

## Civic Tech Eligibility

Short answer: **not a natural fit, don't force it.**

The Civic Tech Challenge has one hard eligibility requirement: the demo must clearly show a connection between people and government (public services, legislation, civic participation, communication with institutions or representatives). The Tell is a self-assessment party game with no government or institutional touchpoint anywhere in the loop. There's no version of the current concept that demonstrates that connection without a fundamental redesign, not a reframe.

If civic tech were a hard requirement, the honest pivot would be a genuinely different project (for example, a confidence-calibration tool aimed at citizens rating their certainty on a ballot measure or public consultation before seeing expert information). That's a different build, not a repackaging of this one, and was already decided against earlier in scoping.

**Recommendation:** skip Civic Tech. Chasing it here would dilute focus on the categories this project can win legitimately.

## Build Plan & Team Roles

**Immediate next 10 minutes:** get the rotary dial printing 0-100 over serial, get one button press printing a timestamp. This is the whole hardware MVP foundation.

**Milestones**

1. Round 1 fully working end to end (dial + button + timer + serial + ElevenLabs verdict), don't start anything else until this works.
2. Session log/leaderboard writing each play to a table.
3. Round 2 (Poker Face, OpenCV smile detector), the first face-reading round, this is the actual pivot payoff.
4. Live OpenCV overlay wired into the frontend feed, this is what makes the face-reading visible and believable to a judge or a passerby.
5. Round 3 (Straight Face Under Pressure), only after Round 2 and the overlay are solid.
6. ElevenLabs roast-or-affirm personality polish and the 5-minute pitch script.
7. Devpost writeup, repo made public (FOSS), demo run-through.

**Suggested role split (adjust to actual headcount/skills)**

- Hardware: Arduino wiring for dial + button, serial output.
- Backend/Vision: Pi script, OpenCV pipeline for the face-reading rounds, scoring logic, ElevenLabs integration, session log.
- Voice/Personality: writes and iterates the ElevenLabs roast-or-affirm verdict script, this is where the comedy and the interview-tone framing live, worth real time.
- Presentation: Devpost page, one-line pitch, demo flow, timing the 5-minute slot.

## Risks & Out of Scope

**Risks**

- Serial communication flakiness between Arduino and Pi under time pressure, mitigate by fully testing Round 1's pipeline before adding the OpenCV rounds.
- Haar cascades and frame-differencing are lighting-sensitive, test under the actual venue lighting before the demo, not just at a desk, a poor face detect live is the single biggest thing that could undercut the pitch.
- ElevenLabs API latency during a live demo, have a short pre-recorded fallback line ready just in case.
- Overreaching on the claim in the pitch, saying or implying this helps with a real interview instead of the honest, demonstrable claim (see Goals & Non-Goals and Target Audience).

**Explicitly out of scope for tonight**

- CGI Northwind Brief
- Civic Tech Challenge
- Accelerometer and ultrasonic sensors, and the Steady Hands / Retreat rounds built on them, cut this pivot
- Any camera-based biometric identity matching, dropped earlier in scoping to reduce risk and keep the privacy story clean
- UV, air quality, and barometer sensors
- Round 4 (PS4 controller trigger), unless the OpenCV rounds are done early

## Judge Assessment (Rubric Scoring, Honest Verdict)

| Criterion | Points | Likely Score | Why |
| --- | --- | --- | --- |
| Technical Execution | 15 | 7-9 | Core mechanism is a threshold comparison plus a live OpenCV read plus a TTS call, real but not deep. Serial comms, a live vision pipeline, and a live API call is more than a pure-software wrapper project, but a judge who's seen 40 projects will clock the simplicity fast. Adding the live calibration curve and the OpenCV overlay raises this. |
| Idea & Impact | 10 | 8-9 | Strongest category, and stronger after this pivot: one focused idea (your face gives you away before something high-stakes) instead of a grab-bag of unrelated sensors. Funny, instantly understandable, has a real (if modest) grounding in metacognitive calibration. |
| Design & Usability | 10 | 7-8 | Simple physical interaction (dial, press, look at camera, listen), inherently usable if the physical build and the live video feed don't feel janky live. |
| Learning & Technical Decisions | 5 | free points if earned | Articulate real decisions made during the build: why webcam-only for the reality check, why the accelerometer and ultrasonic rounds were cut, why Presage-style biometric analysis was dropped. Cheap points, don't skip this in the pitch. |
| Presentation (+5 bonus) | 5 | winnable | Let a judge physically play a round during the 5-minute slot, and see their own face on the overlay. Interactive demos consistently beat screen recordings, and this pivot makes the interactive moment more visceral. |

**Honest verdict:** this is a safe, well-scoped, funny, finishable project that should demo cleanly, and this pivot makes it a more cohesive pitch than the original sensor grab-bag, which matters given the rubric explicitly rewards focused-and-working over ambitious-and-broken. Genuinely competitive for **Best Use of ElevenLabs** and a solid, honestly-framed entry for **Best Hardware Hack** even with a smaller sensor footprint. For **General/Best Overall**, be realistic: competing against teams with more algorithmic depth, cute and funny doesn't automatically beat technically harder. Expect to win the smaller categories comfortably; Best Overall is a genuine toss-up depending on the field.

**Cheapest way to raise the ceiling:** don't just play the roast line, show the live calibration curve, a small chart of gap size shrinking round over round, next to the live OpenCV overlay. Both are just presenting data already being collected, but together they turn "funny toy" into "we're demonstrating a measurable effect, live, on your own face," a real boost to Technical Execution and Learning for minimal extra build time.

## Tools & Tech Stack

**Hardware**

- Arduino Uno (dial + button reads, serial output)
- Raspberry Pi 4 (main logic, OpenCV pipeline, orchestration)
- Rotary angle sensor, button
- Speaker (audio output for ElevenLabs verdicts)
- Webcam (Logitech, confirmed on hand, connects via USB to the Pi): powers the OpenCV rounds, plus the stretch reveal-moment photo capture
- PS4 controller (stretch: Round 4 trigger input)

**Software / Languages**

- Arduino sketch in C/C++ for dial and button reads and serial writes
- Python on the Pi for OpenCV (face detection, Haar cascade smile classifier, frame-differencing), the serial listener, scoring logic, and API orchestration (pyserial for serial, opencv-python for vision, requests or the official SDK for ElevenLabs)
- Simple local storage for the session log/leaderboard: SQLite or a flat CSV/JSON file is enough for tonight, only reach for Postgres/Tiger Data if there's real time left over

**APIs / Services**

- ElevenLabs API for text-to-speech verdict generation
- Tiger Data (optional, stretch) if the session log gets upgraded to Postgres for the mini-challenge

**Dev tools**

- Git/GitHub for version control and the public FOSS repo
- Whatever the team already knows for quick scripting, don't learn a new framework tonight

## Repo Structure

```
the-tell/
├── README.md                  # project pitch, setup instructions, demo gif
├── LICENSE                    # open license for the FOSS category
├── arduino/
│   └── the_tell.ino           # reads dial/button, writes JSON over serial
├── pi/
│   ├── main.py                # serial listener + main loop
│   ├── vision.py               # OpenCV face detection, smile classifier, frame-difference logic
│   ├── scoring.py             # gap/score calculation
│   ├── elevenlabs_client.py   # roast-or-affirm prompt building + TTS call
│   ├── session_log.py         # writes each round to storage (sqlite/csv, or Tiger Data if upgraded)
│   └── requirements.txt
├── data/
│   └── sessions.db            # or sessions.csv, local session log
├── docs/
│   └── pitch_script.md        # 5-minute pitch, judge Q&A prep
└── assets/
    └── demo_recording.mp4     # backup demo video in case live hardware hiccups
```

**Notes**

- keep `arduino/` and `pi/` fully separate, the Arduino sketch should only ever read the dial and button and print JSON, all logic including OpenCV lives on the Pi
- `elevenlabs_client.py` should support a fallback pre-recorded line in case of API latency during the live demo (see Risks)
- `vision.py` should be testable on its own against a saved video clip, not just the live webcam, so lighting or camera issues can be debugged without the whole rig running
- push early and often, a clean-looking commit history is not judged, but having actual history to point to if anyone asks how the project was built is good practice
