# Delulu Detector — PRD

Sep 26, 2026 · @Saim

## Overview & Problem

Most people are bad at knowing how good they actually are at something in the moment, a documented phenomenon studied under metacognitive calibration (the popular shorthand people know is the Dunning-Kruger effect, though the real research area is broader: does your confidence match your actual ability). Existing self-assessment tools, surveys, confidence sliders, post-hoc grades, rarely close the loop between what someone predicts about themselves and what actually happens, so the mismatch stays invisible until it costs something.

**Delulu Detector** is a physical arcade-style party game built for Hack the Hill III that makes this gap visible, funny, and immediate. A player states a confidence prediction on a physical dial, performs a short physical challenge, and a sensor measures the real outcome. An ElevenLabs-voiced narrator calls out the gap between prediction and reality in real time.

## What This Actually Is (Honest Framing)

This matters enough to state plainly, because it's easy to oversell and a judge will catch it if we do.

**What it doesn't do:** it does not train anyone to get better at anything, and it does not help with real-stakes nervousness (interviews, negotiations, exams). One play doesn't improve a skill.

**What it actually is:** a live demonstration of a real, well-documented pattern, people are consistently bad at predicting their own performance on tasks they've never gotten calibrated feedback on before (reaction time in milliseconds, how steady their hands actually are, how long they can hold an expression). Nobody has an accurate mental model of these because daily life never tests them. The "gap" the game measures is really just how bad humans are at estimating things they have zero real feedback on, that's the actual phenomenon, and it's genuinely interesting on its own.

**Why it's still a good pitch:** the entertainment value comes from watching confident people get proven wrong by their own body in real time, the same basic appeal as a lie-detector party game. That's a legitimate, honest hook. It does not need an inflated "this helps you" claim to be worth building or demoing.

**The pitch line to actually use:** "we're not claiming this makes you better at anything, we're demonstrating that people are reliably overconfident about tasks they've never gotten real feedback on before, and making that visible live is funny." Say exactly this, don't reach further, it holds up under a follow-up question and an inflated version doesn't.

## Goals & Non-Goals

**Goals**

- Ship one fully working round (dial + button + reaction timer + ElevenLabs verdict) end to end before anything else.
- Make the claim-vs-reality gap the entire mechanic, no extra features that don't serve that loop.
- Demonstrate, live, that repeated rounds with instant feedback measurably shrink a player's prediction gap, this is the actual, honest educational claim.

**Non-Goals**

- This does not claim to treat interview anxiety, negotiation nervousness, or any clinical condition. That's out of scope and should not appear in the pitch.
- Not a general mental-health or biometric diagnostic tool.
- Not trying to use every sensor on hand. Sensors without a natural claim-vs-reality moment (UV, air quality, barometer) are deliberately excluded and called out as such in the pitch.

## Core Concept & Game Loop

Every round follows the same three-step loop:

1. **Predict** — player sets a 0-100 confidence claim on the rotary dial for a specific, narrow physical challenge about to happen.
2. **Perform** — player does the challenge, a sensor captures the real, objective result.
3. **Reveal** — the system computes the gap between claim and result, and ElevenLabs delivers a personality-driven verdict ("validated" for a small gap, escalating roast levels for larger ones).

Playing multiple rounds back to back is the actual demo moment: the gap should visibly shrink round over round as the player recalibrates off the immediate feedback. That's the real, honest, demonstrable claim behind the game, not a promise to fix nervousness or anxiety.

## Round Designs

| Round | Sensor(s) | Predict | Reality Check |
| --- | --- | --- | --- |
| 1. Reflex Round (build first, ships alone if nothing else lands) | Rotary dial + button | Claimed reaction speed (0-100) | Real reaction time in ms from cue to button press |
| 2. Steady Hands Round | Rotary dial + accelerometer | Claimed calmness/steadiness (0-100) | Real tremor/movement while holding still for 5s |
| 3. Retreat Round | Rotary dial + ultrasonic | Claimed unshakeability (0-100) | Physical flinch-back distance when shown a startling prompt |
| 4. Reveal Cam (stretch, no scoring impact) | Webcam | n/a | Auto-captures a photo at the exact reveal moment as a shareable meme, no biometric analysis |
| 5. Poker Face Round (OpenCV, local, no API) | Rotary dial + webcam (OpenCV Haar cascade smile detector) | Claimed poker-face confidence (0-100) | Whether a smile/laugh is detected while shown something funny in a short window |
| 6. Straight Face Timer (OpenCV, local, no API) | Rotary dial + webcam (frame-difference on mouth/face region over time) | Claimed seconds they can hold a neutral expression | Actual seconds elapsed until detectable expression change |

**Scoring:** `gap = abs(claimed_confidence_normalized − actual_performance_normalized)`. Smaller gap = higher score. A running leaderboard tracks best gap, worst ("most delulu") gap, and total rounds played per person.

**Considered and dropped:** a "Color Blind Spot" OpenCV round (guess a color, camera reads the real RGB value) was considered as a callback to the color-detection projects that have historically won at Hack the Hill, but it doesn't fit the claim-vs-reality format, colorblindness isn't a confidence thing, people generally already know if they see color differently, so there's no real "delulu" gap to reveal. Dropped rather than forced in.

**Build note for rounds 5-6:** both run fully local via OpenCV's built-in Haar cascades, no external API, no network dependency, no added latency risk during the live demo (unlike the ElevenLabs call, which only fires once for the verdict). Build these only after Round 1 is fully working end to end.

## Technical Architecture

**Data flow:** Arduino Uno reads the round's sensor(s) → sends `{claim, actual, round_id}` over serial → Raspberry Pi 4 parses the serial stream, computes the gap and score, appends a row to the session log → Pi calls ElevenLabs with the numbers to generate the spoken verdict → audio plays through a speaker.

**Components**

- Arduino Uno: dial + button (round 1), + accelerometer (round 2), + ultrasonic (round 3)
- Raspberry Pi 4: serial listener, scoring logic, session log, ElevenLabs API calls
- ElevenLabs: generates the verdict line from a short prompt template fed the claim, actual result, and gap size
- Session log: simple timestamped table (name/session id, round, claim, actual, gap, score), the natural hook for the Tiger Data mini-challenge if there's time left over

**Build order:** get round 1's dial + button reading real values over serial first, confirm the pipeline end to end with a hardcoded ElevenLabs call before wiring anything else.

## Hardware & Sensor Mapping

**Used, and why each one earns its place:**

- Rotary angle sensor: the universal "claim" input for every round
- Button: reaction-time trigger for Round 1
- Accelerometer: tremor/steadiness reality check for Round 2
- Ultrasonic sensor: flinch-distance reality check for Round 3
- Webcam (Logitech, USB, connects to the Pi not the Arduino): confirmed on hand, plug-and-play with OpenCV via cv2.VideoCapture(), powers Rounds 5-6 (Poker Face Round, Straight Face Timer); also usable for the stretch Reveal Cam snapshot
- PS4 controller trigger: optional Round 4 (decisiveness via trigger-pull speed), stretch only

**Deliberately not used, and why:**

- UV sensor, air quality sensor, barometer — these measure the room, not the player. There's no natural "predict yourself" moment for ambient conditions, so they're left out rather than forced in. Worth one line in the pitch: it shows restraint, not a gap in ability.

## Target Prize Categories

| Category | How this project qualifies |
| --- | --- |
| **General Challenge — Best Overall** (primary target) | Focused, working, funny, clean 5-minute demo; winner also receives the ElevenLabs prize |
| **Best Hardware Hack** | Real multi-sensor fusion (dial, button, accelerometer, ultrasonic), physical build central to the concept, not decorative |
| **Best Use of ElevenLabs** | The verdict/roast voice is the core payoff of every round, not bolted on |
| **Best FOSS Project** | Public repo with an open license, near-zero extra effort |
| **Best Educational Project (MathemaTech)** | Legitimate framing around metacognitive calibration and confidence-feedback loops, demonstrated live by showing the gap shrink across rounds |
| **Best Use of Tiger Data** (optional, only if time allows) | Session log (claim/actual/gap per round) is naturally a timestamped Postgres table, don't force this if it costs build time |

**Deliberately not targeting:** CGI Challenge (team decision, different project shape entirely), Civic Tech (see below), Solana/Gemini/Auth0/Vultr/GoDaddy (no natural fit, would read as forced).

## Civic Tech Eligibility

Short answer: **not a natural fit, don't force it.**

The Civic Tech Challenge has one hard eligibility requirement: the demo must clearly show a connection between people and government (public services, legislation, civic participation, communication with institutions or representatives). Delulu Gauntlet is a self-assessment party game with no government or institutional touchpoint anywhere in the loop. There's no version of the current concept that demonstrates that connection without a fundamental redesign, not a reframe.

If civic tech were a hard requirement, the honest pivot would be a genuinely different project (for example, a confidence-calibration tool aimed at citizens rating their certainty on a ballot measure or public consultation before seeing expert information). That's a different build, not a repackaging of this one, and was already decided against earlier in scoping.

**Recommendation:** skip Civic Tech. Chasing it here would dilute focus on the four categories this project can win legitimately.

## Build Plan & Team Roles

**Immediate next 10 minutes:** get the rotary dial printing 0-100 over serial, get one button press printing a timestamp. This is the whole hardware MVP foundation.

**Milestones**

1. Round 1 fully working end to end (dial + button + timer + serial + ElevenLabs verdict), don't start anything else until this works
2. Session log/leaderboard writing each play to a table
3. Round 2 (accelerometer), only after 1 and 2 are solid
4. Round 3 (ultrasonic), only if time remains
5. ElevenLabs personality polish and the 5-minute pitch script
6. Devpost writeup, repo made public (FOSS), demo run-through

**Suggested role split (adjust to actual headcount/skills)**

- Hardware: Arduino wiring, serial output, sensor calibration
- Backend: Pi script, scoring logic, ElevenLabs integration, session log
- Voice/Personality: writes and iterates the ElevenLabs verdict script, this is where the comedy lives, worth real time
- Presentation: Devpost page, one-line pitch, demo flow, timing the 5-minute slot

## Risks & Out of Scope

**Risks**

- Serial communication flakiness between Arduino and Pi under time pressure, mitigate by fully testing Round 1's pipeline before adding more sensors
- ElevenLabs API latency during a live demo, have a short pre-recorded fallback line ready just in case
- Overreaching on the educational claim in the pitch (see Goals & Non-Goals), stick to the honest, demonstrable claim only

**Explicitly out of scope for tonight**

- CGI Northwind Brief
- Civic Tech Challenge
- Any camera-based biometric analysis (Presage), dropped earlier in scoping to reduce risk
- UV, air quality, and barometer sensors
- Round 4 (PS4 controller trigger), unless rounds 1-3 are done early

## Judge Assessment (Rubric Scoring, Honest Verdict)

| Criterion | Points | Likely Score | Why |
| --- | --- | --- | --- |
| Technical Execution | 15 | 7-9 | Core mechanism is a threshold comparison plus a TTS call, real but not deep. Serial comms between Arduino and Pi plus a live API call is more than a pure-software wrapper project, but a judge who's seen 40 projects will clock the simplicity fast. Adding a live calibration curve (below) raises this. |
| Idea & Impact | 10 | 8-9 | Strongest category. Funny, instantly understandable, has a real (if modest) grounding in metacognitive calibration. This is where the project actually differentiates. |
| Design & Usability | 10 | 7-8 | Simple physical interaction (dial, press, listen), inherently usable if the physical build doesn't feel janky live. |
| Learning & Technical Decisions | 5 | free points if earned | Articulate real decisions made during the build: why serial, why scoped down from 4 rounds to 1-2, why Presage was dropped. Cheap points, don't skip this in the pitch. |
| Presentation (+5 bonus) | 5 | winnable | Let a judge physically play a round during the 5-minute slot. Interactive demos consistently beat screen recordings. |

**Honest verdict:** this is a safe, well-scoped, funny, finishable project that should demo cleanly, which matters given the rubric explicitly rewards focused-and-working over ambitious-and-broken. Genuinely competitive for **Best Hardware Hack** and **Best Use of ElevenLabs** (smaller pools, non-trivial use of both). For **General/Best Overall**, be realistic: competing against teams with more algorithmic depth, cute and funny doesn't automatically beat technically harder. Expect to win the smaller categories comfortably; Best Overall is a genuine toss-up depending on the field.

**Cheapest way to raise the ceiling:** don't just play the roast line, show a live calibration curve, a small chart of gap size shrinking round over round. This is just plotting data already being collected, but it turns "funny toy" into "we're demonstrating a measurable effect," a real boost to Technical Execution and Learning for minimal extra build time.

## Tools & Tech Stack

**Hardware**

- Arduino Uno (sensor reads, serial output)
- Raspberry Pi 4 (main logic, orchestration)
- Rotary angle sensor, button, accelerometer, ultrasonic sensor
- Speaker (audio output for ElevenLabs verdicts)
- Webcam (Logitech, confirmed on hand, connects via USB to the Pi): powers Rounds 5-6 via OpenCV, plus the stretch reveal-moment photo capture
- PS4 controller (stretch: Round 4 trigger input)

**Software / Languages**

- Arduino sketch in C/C++ for sensor reads and serial writes
- Python on the Pi for the serial listener, scoring logic, and API orchestration (pyserial for serial, requests or the official SDK for ElevenLabs)
- Simple local storage for the session log/leaderboard: SQLite or a flat CSV/JSON file is enough for tonight, only reach for Postgres/Tiger Data if there's real time left over

**APIs / Services**

- ElevenLabs API for text-to-speech verdict generation
- Tiger Data (optional, stretch) if the session log gets upgraded to Postgres for the mini-challenge

**Dev tools**

- Git/GitHub for version control and the public FOSS repo
- Whatever the team already knows for quick scripting, don't learn a new framework tonight

## Repo Structure

```
delulu-detector/
├── README.md                  # project pitch, setup instructions, demo gif
├── LICENSE                    # open license for the FOSS category
├── arduino/
│   └── delulu_gauntlet.ino    # reads dial/button/accelerometer/ultrasonic, writes JSON over serial
├── pi/
│   ├── main.py                # serial listener + main loop
│   ├── scoring.py             # gap/score calculation
│   ├── elevenlabs_client.py   # verdict prompt building + TTS call
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

- keep `arduino/` and `pi/` fully separate, the Arduino sketch should only ever read sensors and print JSON, all logic lives on the Pi
- `elevenlabs_client.py` should support a fallback pre-recorded line in case of API latency during the live demo (see Risks)
- push early and often, a clean-looking commit history is not judged, but having actual history to point to if anyone asks how the project was built is good practice
