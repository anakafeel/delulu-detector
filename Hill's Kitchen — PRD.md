# Hill's Kitchen — PRD

Sep 26, 2026 · @Saim

## Overview & Problem

Most people don't know how they'll actually come across in a real high-stakes moment, a walk-in interview, a hard pitch, a tough ask, until they're already in it. That's a real, felt kind of nervous confidence: you can talk yourself into feeling calm and prepared, and your face can be telling a completely different story the whole time. This sits inside metacognitive calibration research (the popular shorthand is the Dunning-Kruger effect, though the actual research area is broader: does your confidence match your actual state), but the everyday version of it is simpler and more personal, the gap between how composed you think you're coming across and how composed you actually look.

**Hill's Kitchen** is a live nervous-confidence reality check built for Hack the Hill III. A player states how nervous or composed they expect to be in a specific high-stakes moment on a physical dial, then goes through a short mock version of that moment on camera. Presage reads real facial-emotion signal live, stress, tension, composure, alongside OpenCV's face tracking, and the two get compared against the player's own claim, end to end, with nothing pre-recorded or simulated anywhere in the loop. An ElevenLabs-voiced narrator calls out the gap the moment it's computed.

## Mascot / Narrator (the meme layer, doesn't touch the mechanic)

Same loop, same sensors, same scoring, this is purely a branding layer on top of the ElevenLabs verdict that already exists. The goal is to make the reveal moment feel like something people already see in their feed, not a generic "game show voice," using actual current meme language instead of inventing a bit from scratch.

**The mascot: a nihilistic penguin.** Built off the viral "nihilistic penguin" clip (from Werner Herzog's *Encounters at the End of the World*, re-blown-up on TikTok/IG/X in early 2026), a lone penguin that wanders off from the group toward certain doom, used online as a symbol for "ignoring reality and committing to the bit anyway." That's almost exactly what an overconfident player is doing when they call a big number on the dial. Rendered as a simple low-poly 3D model in three.js on the frontend:

- On a **big gap** ("most delulu" territory): the penguin turns and waddles off-screen toward the horizon, deadpan, no music sting needed, the joke is that it's already checked out on you, same energy as the original clip.
- On a **small gap / validated**: the penguin does the Scuba Dance (nose pinch with one flipper, other flipper waving, knee bounce), the current viral celebration move from TikTok/NFL touchdown celebrations, repurposed here as "you called your own number correctly, that's a touchdown."
- Runs as a lightweight three.js scene reacting to the same round-result data the rest of the frontend already reads, no new backend needed, just three states (idle, leaving, scuba-dancing) triggered off the verdict payload.

**The verdict audio: work in a "6 7" beat.** "6-7" is the current everywhere-meme (from the Skrilla song, blew up via basketball edits, was Dictionary.com's word of the year), an absurdist, context-free numeric callout people drop into anything. Since every round's core output is literally two numbers (claimed vs. actual), there's a free, honest tie-in: on an ambiguous or medium-sized gap, the ElevenLabs line can land on a beat-dropped "6… 7…" the same way the meme does, before the actual roast or affirm line. Cheap, current, and it's a real joke about the number mismatch, not a bolted-on reference.

- **Where it plugs in:** `elevenlabs_client.py` already owns the verdict prompt/line, add the "6 7" beat as one more template variant it can pick for the ambiguous-gap case. The penguin model is a small three.js addition to the existing display-only frontend, driven by the same verdict payload, no new round, no new hardware, no new backend logic.
- **Priority:** polish layer, build only after Round 1 and the OpenCV rounds are solid end to end. Doesn't block anything and nothing blocks on it, cut first if time runs short.
- **Open:** need to actually pull/rig a low-poly penguin asset (or box-model one fast) and lock which round(s) get the "6 7" beat vs. a straight roast line.

## What This Actually Is (Honest Framing)

This matters enough to state plainly, because it's easy to oversell and a judge will catch it if we do.

**What it doesn't do:** it does not measure real interview or pitch performance, it does not diagnose anxiety or any clinical condition, and it does not help anyone actually land the interview. One play doesn't improve anyone's real-world composure, and a live Presage emotion read plus an OpenCV face track is a real signal, not a validated psychological instrument or a substitute for therapy or coaching.

**What it actually is:** a live demonstration of a real pattern, people are consistently bad at predicting how nervous or composed they'll actually look to someone watching, because nobody gets real-time feedback on their own face during an actual high-stakes moment. The "tell" (the poker word for an involuntary giveaway) is a real, measured facial-emotion signal, read live through Presage and cross-checked with OpenCV's face tracking, compared against a self-report. That's the honest phenomenon being shown, and it's genuinely interesting on its own, no invented gap, no mocked data behind it.

**Why it's still a good pitch:** the entertainment value comes from watching confident people get called out by their own face in real time, the same basic appeal as a lie-detector party game. That's a legitimate, honest hook. It does not need an inflated "this will get you the job" claim to be worth building or demoing.

**The pitch line to actually use:** "we're not claiming this will help you land the interview, we're demonstrating that your face gives off signals you don't control and can't accurately predict, and making that visible live is funny, and a little uncomfortable." Say exactly this, don't reach further, it holds up under a follow-up question and an inflated version doesn't.

## Goals & Non-Goals

**Goals**

- Ship one fully working loop end to end, dial claim, live Presage + OpenCV facial read, roast-or-affirm ElevenLabs verdict, with real data on the UI the whole way through, no pre-recorded audio, no mocked frontend states.
- Frame every round around a real high-stakes moment, an interview question, a pitch, a hard ask, not an abstract game show. The nervous-confidence gap is the whole pitch, not a bit.
- Keep hardware to what's confirmed on hand and load-bearing: dial, button, webcam. Presage and ElevenLabs are the only external APIs, both genuinely load-bearing, not decorative.
- Demonstrate, live, that repeated rounds with instant feedback measurably shrink a player's prediction gap, this is the actual, honest, demonstrable claim, and it has to run on real calibrated numbers, not placeholder thresholds.

**Non-Goals**

- Does not train anyone to interview better, negotiate better, or manage anxiety. Not a clinical or therapeutic tool, and that framing should not appear in the pitch, even with a real emotion-recognition API behind it.
- Not a biometric identification tool. Presage classifies emotion signal in the moment, it is not used to identify who someone is, match them to a stored profile, or keep frames past the session. The one exception is opt-in: after typing their name a player can press Y to keep one webcam photo from 3 s into the question for the leaderboard (click their name to see it). It stays in the game's memory on this laptop, is never written to disk, SQLite or Tiger Data, and is gone when the game stops.
- Cut the accelerometer (Steady Hands) and ultrasonic (Retreat) rounds entirely. Tremor and flinch-distance don't connect to the nervous-confidence story and aren't facial signal, they diluted the concept into a generic sensor grab-bag rather than one focused idea.
- Not trying to use every sensor or every sponsor API on hand. UV, air quality, and barometer are still deliberately excluded and called out as such in the pitch, adding Presage was a real fit decision, not a "use everything" reflex.

## Core Concept & Game Loop

Every round follows the same three-step loop:

1. **Predict** — player sets a 0-100 confidence claim on the rotary dial for a specific claim tied to a mock high-stakes moment about to happen ("I can stay completely composed answering this").
2. **Perform** — player does a short mock version of that moment on camera (a rapid-fire tough question, holding a poker face under pressure), while OpenCV reads their face live.
3. **Reveal** — the system computes the gap between the claim and the measured "tell," and ElevenLabs delivers a roast-or-affirm verdict, affirming a real match, escalating roast levels for a bigger gap, whether that means overconfidence or an undersell.

Playing multiple rounds back to back is the actual demo moment: the gap should visibly shrink round over round as the player learns their own tells. That's the real, honest, demonstrable claim behind the game, not a promise to fix nervousness or land the interview.

## Hill's Kitchen: Rounds

| Round | Sensor(s) | Predict | Reality Check |
| --- | --- | --- | --- |
| 1. Reflex Round (build first, ships alone if nothing else lands) | Rotary dial + button | Claimed reaction speed under pressure (0-100) | Real reaction time in ms from cue to button press |
| 2. Poker Face Round (Presage + OpenCV, live) | Rotary dial + webcam (Presage live emotion classification, OpenCV face detection for tracking/overlay) | Claimed poker-face confidence going into a mock tough interview question (0-100) | Whether a smile, laugh, or visible reaction is detected in a short window |
| 3. Straight Face Under Pressure (Presage + OpenCV, live) | Rotary dial + webcam (Presage live emotion signal over time, OpenCV frame-difference as a cross-check) | Claimed seconds they can hold a neutral, composed expression under a rapid-fire question | Actual seconds elapsed until detectable expression change |
| 4. Reveal Cam (stretch, no scoring impact) | Webcam | n/a | Auto-captures a photo at the exact reveal moment as a shareable meme, no biometric analysis |

**Cut this pivot:** Steady Hands Round (accelerometer, tremor while holding still) and Retreat Round (ultrasonic, flinch-back distance). Both measured physical steadiness rather than facial expression, and neither connected to the interview-confidence story, they were dropped to keep the concept to one clear thing: your face gives you away.

**Scoring:** `gap = abs(claimed_confidence_normalized − actual_performance_normalized)`. Smaller gap = higher score. A running leaderboard tracks best gap, worst ("most delulu") gap, and total rounds played per person.

**Considered and dropped:** a "Color Blind Spot" OpenCV round (guess a color, camera reads the real RGB value) was considered as a callback to the color-detection projects that have historically won at Hack the Hill, but it doesn't fit the claim-vs-reality format, colorblindness isn't a confidence thing, people generally already know if they see color differently, so there's no real "delulu" gap to reveal. Dropped rather than forced in.

**Build note:** Rounds 2-3 now depend on a live Presage API call on top of the one-shot ElevenLabs verdict call. That's a real network dependency during the demo, by design, this pivot trades the old "fully local, zero network risk" property for a real sponsor-tech integration and real, non-guessed emotion data. Mitigate with a stable venue connection check before the slot, not with a fallback path, there isn't one anymore. Build these only after Round 1 is fully working end to end.

## Technical Architecture

**Data flow:** Arduino Uno reads the dial and button → sends `{claim, actual, round_id}` over serial to a Raspberry Pi 4. For Rounds 2-3 the Pi streams the live webcam feed to Presage for real-time emotion classification (stress/composure signal) and runs OpenCV alongside it for face detection and the on-screen overlay. The Pi computes the gap and score off Presage's live number, appends a row to the session log, calls ElevenLabs with the numbers to generate a roast-or-affirm verdict, and plays the audio through a speaker. Every number on screen, claim, Presage read, gap, verdict, is live and computed in the moment, nothing on the frontend is pre-generated, cached, or mocked.

**Components**

- Arduino Uno: dial + button only, this pivot drops the accelerometer and ultrasonic wiring entirely.
- Raspberry Pi 4: serial listener, Presage client for live emotion classification, OpenCV for face tracking/overlay, scoring logic, session log, ElevenLabs API calls.
- Presage: reads the live webcam feed during Rounds 2-3 and returns a real-time emotion/stress signal, this is the actual "reality check" measurement now, not an OpenCV heuristic standing in for one.
- ElevenLabs: generates the roast-or-affirm verdict line from a short prompt template fed the claim, actual result, and gap size. The prompt should lean into a skeptical-interviewer, brutally-honest-friend tone, that voice is the emotional core of the pivot.
- Session log: simple timestamped table (name/session id, round, claim, actual, gap, score), the natural hook for the Tiger Data mini-challenge if there's time left over.

**Build order:** get Round 1's dial + button reading real values over serial first, confirm the pipeline end to end with a hardcoded ElevenLabs call, before wiring the OpenCV rounds.

## Frontend

Display-only, no user input required, this is a live status screen shown next to the physical rig during play and judging, not an interactive UI. Owner is building this with a design skill/tool directly, this section exists so the rest of the team knows what data it needs to receive.

**Required to show, live, updating each round:**

- **The live webcam feed itself, with the OpenCV detection overlay drawn on it** (face box, smile-detector confidence, or a marker each time expression change is registered). This is the single most important frontend requirement in this pivot, the audience needs to see the detector actually watching a face in real time, not just trust a final number.
- Everything on this screen is live, there is no mock cycle and no pre-generated demo data anywhere in the frontend path, if Presage or ElevenLabs is down, the screen should show that plainly rather than fake a result.
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
- Presage (cloud emotion-recognition API): reads the live webcam stream during the face rounds and returns the actual stress/composure signal, this replaces the OpenCV-only heuristics as the real reality-check measurement, OpenCV stays in for face detection and the on-screen overlay.
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
| **Best Use of Presage** | Presage's live emotion signal is now the actual reality-check measurement behind Rounds 2-3, not a bolted-on demo call, it's load-bearing for the core mechanic, if this prize exists at Hack the Hill, this is a genuine claim on it. |
| **Best FOSS Project** | Public repo with an open license, near-zero extra effort |
| **Best Educational Project (MathemaTech)** | Legitimate framing around metacognitive calibration and confidence-feedback loops, demonstrated live by showing the gap shrink across rounds |
| **Best Use of Tiger Data** (optional, only if time allows) | Session log (claim/actual/gap per round) is naturally a timestamped Postgres table, don't force this if it costs build time |

**Deliberately not targeting:** CGI Challenge (team decision, different project shape entirely), Civic Tech (see below), Solana/Gemini/Auth0/Vultr/GoDaddy (no natural fit, would read as forced).

## Civic Tech Eligibility

Short answer: **not a natural fit, don't force it.**

The Civic Tech Challenge has one hard eligibility requirement: the demo must clearly show a connection between people and government (public services, legislation, civic participation, communication with institutions or representatives). Hill's Kitchen is a self-assessment party game with no government or institutional touchpoint anywhere in the loop. There's no version of the current concept that demonstrates that connection without a fundamental redesign, not a reframe.

If civic tech were a hard requirement, the honest pivot would be a genuinely different project (for example, a confidence-calibration tool aimed at citizens rating their certainty on a ballot measure or public consultation before seeing expert information). That's a different build, not a repackaging of this one, and was already decided against earlier in scoping.

**Recommendation:** skip Civic Tech. Chasing it here would dilute focus on the categories this project can win legitimately.

## Current Status (vs. Plan)

Real, as of tonight, not projected:

- **Poker Face is live and working end to end.** Dial locks a claim, Presage returns a real composure number from the actual camera feed, gap and score compute, ElevenLabs speaks a real verdict, all inside the 3-second budget. Four scored rounds are logged in `data/sessions.db`, all real, no seed data. This is the loop the whole pivot bet on, and it's working.
- **Straight Face has not been played live yet.** Same Presage-backed code path as Poker Face, but zero live rounds and zero log rows for `--round 6`. Don't claim it's working in the pitch until it's actually been run.
- **The reveal label is wrong.** The number shown is Presage's composure score, but the screen and the terminal both still print the old OpenCV-era units, "% smiling" for Poker Face, "s held" for Straight Face. Cosmetic but embarrassing if a judge reads the actual output.
- **The interview questions are silent.** `assets/questions/` is empty and there's no live ElevenLabs call for them, so a face round is dead air until the verdict. Without the question audio, there's no actual mock-interview moment happening, just a countdown, which weakens the nervous-confidence framing this PRD is built around.
- **Camera positioning is a real constraint, not just a config value.** Presage throws a camera-position error if the face sits too high or low in frame. The rig's physical camera height has to be locked and calibrated at that exact height before the demo, a software fix alone won't cover it.
- **Reflex hasn't been re-verified since the Presage refactor.** Code is unchanged, but the shared process loop was touched, worth one confirmation run since Reflex is the fallback round if the camera fails.
- **The old OpenCV thresholds are now dead on the live path.** They only run under `--mock`/`--calibrate`, meaning `--calibrate` is currently tuning a path nobody actually plays on.
- **Steady Hands still exists in the repo** behind `--legacy-rounds --round 2`, not part of the live game, consistent with the cut in Goals & Non-Goals.
- **Devpost writeup and backup demo video are still outstanding**, `docs/devpost.md` exists but hasn't been written or submitted.

## UI/UX Polish & Interaction Additions (In Progress)

After a live judge preview, a real UI/UX pass is underway on top of the working Poker Face path. None of this touches the Presage/ElevenLabs/scoring logic underneath, it's the presentation layer catching up to the data that's already real.

**Bug fixes flagged from the judge preview:**

- The interview question text was too small to read at booth distance, being fixed as a type-hierarchy pass across the whole app (question text as the largest, boldest element on screen), not a one-off font bump.
- The verdict audio felt slow. Root cause gets diagnosed before it gets fixed, either the ElevenLabs voice's actual speaking rate, or the perceived wait during the 3-second API round-trip before any audio starts, those need different fixes, and a loading/processing state is going in either way so the screen never just sits frozen.

**New: name entry before the camera round.** A short input screen between locking the claim and the camera starting, replacing the hardcoded player name. Fast, one field, feeds into the session log and leaderboard for real. Framed as part of the game (the mascot "asking" for a name), not a bolted-on form.

**New: "How this is calculated" explainer.** A simple, honest panel spelling out claim vs. Presage composure vs. gap vs. score in plain language, no jargon, no implying more sophistication than the actual math. Matches the honesty standard the rest of this PRD already holds itself to.

**New: "how you compare," honest version.** Explicitly not a fabricated percentile against an implied large population, the live sample size tonight is a handful of rounds and pretending otherwise would break the same honesty standard the pitch depends on. Instead, compares against the real rows already in `data/sessions.db` ("better calibrated than 2 of the 4 rounds played tonight"), labeled plainly as based on tonight's plays so far. Grows more meaningful as more people play, which is itself a decent live demo beat.

**Considering: a second ElevenLabs voice** for tonal variety between a validated verdict and a big-gap roast, only if it doesn't add a second point of live-demo failure risk on top of what's already accepted by dropping the fallback path. One voice done reliably beats two voices done shakily.

**Live composure motion during the question**, not just at reveal, the score should visibly move while the player is answering, this is the clearest "it's actually reading me right now" moment available and it's currently backloaded to the end of the round.

**Physical dial feedback (separate hardware add, same spirit):** a Grove LCD RGB Backlight on the Arduino's I2C bus (A4/A5) showing the live 0-100 claim as a number, a text progress bar, and a backlight color that shifts from cool to warm as the value rises, plus a piezo buzzer giving a short pitch-mapped tick as the dial turns and a distinct confirm tone when the button locks it. Purely local feedback, the serial protocol to the Pi is unchanged. Both are non-blocking additions, tested on the bench before going anywhere near the actual rig.

**New: per-player baseline calibration.** An MLH judge raised a fair, real critique live: everyone has a different resting/neutral face, so scoring everyone against one fixed 0-100 composure scale isn't actually fair across different people. The fix is a real feature, not just a talking point: add a short 2-3 second "hold your neutral face" capture at the start of each player's round, before the question plays. Presage's read during that window becomes that player's own baseline, and the round's composure score is computed as the delta from that baseline, not an absolute number. That makes the claim-vs-reality gap genuinely comparable across different people's faces, not just internally consistent for one person across their own rounds.

**Known limitation, said out loud, not hidden:** even with per-player baseline calibration, this doesn't account for how someone's resting face might differ under a real interview's actual stakes versus a mock one at a hackathon booth. The honest, forward-looking answer to a judge pushing on rigor: this could eventually personalize further using context about the specific high-stakes moment someone's practicing for, for example weighting the baseline or verdict differently by the kind of role or interview a resume points at. That's explicitly future work, not built tonight, and saying so plainly is a stronger answer than pretending the current scale is already that sophisticated.

**"How this is calculated" explainer, made real, matching the above:** the panel should say, in this order and in plain language: (1) a short neutral-face baseline capture happens first, (2) Presage reads live facial signal during the actual question, (3) composure is that live read expressed relative to the player's own baseline, not a universal scale, (4) gap = |claim − personalized composure|, score = 100 − gap. No invented statistics, no clinical-sounding language, just the real steps in the real order.

**Clean, consistent animations.** State transitions (idle → name → baseline calibration → dial → question → live read → reveal → leaderboard) use one consistent transition style (a simple fade/slide, one easing curve and duration) across the whole app, not a different effect per screen. Animation is purely presentational, it must never delay real data appearing or block interaction, the state changes underneath still happen instantly, the animation just smooths how they're shown.

## Pitch & Judge Q&A (Practice This)

The pitch line stays what's already in "What This Actually Is": we're demonstrating that your face gives off signals you don't control and can't accurately predict, live, using Presage's real classification, not a canned demo. Below are the questions that will actually get asked, answered straight, no hand-waving.

**Operational note:** this PRD is committed in the repo as `Hill's Kitchen — PRD.md`, so this section and the per-player baseline spec elsewhere in it are the reference for any further work. The per-player baseline itself is spec only: it is not built yet.

**"How is the metric actually calculated?"** Claim is the 0-100 number a player dials in themselves. A short neutral-face baseline is captured first. Presage then reads live facial signal during the actual question. Composure is that live read expressed relative to the player's own baseline, not a universal scale. Gap is the absolute difference between claim and personalized composure. Score is 100 minus the gap. Every step is real, nothing is estimated or invented.

**"What's the baseline based on?"** Each player's own resting/neutral face, captured fresh for 2-3 seconds right before their round starts, not a population average or a canned template. It only measures that person against themselves in that moment, it does not claim to know what "confident" looks like on a stranger.

**"Doesn't a completely poker-faced, expressionless person just automatically win?"** Checked this against the actual Presage SDK schema, not a guess. Presage's node SDK returns an 8-class facial-expression distribution (angry, contempt, disgust, fear, happy, neutral, sad, surprise), and the number currently labeled "composure" is the NEUTRAL class confidence, averaged over the round. So it's genuinely reading expression, not movement or stillness, a smile held perfectly still should still score low. But it can't see what's happening internally: a blank, checked-out face IS neutral by definition, so it scores the same as someone who's actually calm and deliberately unreadable on purpose. There's no better signal available in a 6-second round either, Presage's only real stress-type field (Baevsky's Stress Index, from heart-rate variability) needs 30-60+ seconds of clean pulse data to mean anything. The honest fix isn't a different data feed, it's the label: this should be called "expression neutrality" or "how unreadable your face looked," not "composure," which implies calm on the inside rather than a blank read. That relabel is pending a quick on-rig test (blank face vs. genuinely relaxed-and-reactive vs. a smile held still, two rounds each) to confirm the direction before it ships, this answer should not be given with more certainty than that test has actually provided.

**"Would this scale beyond a hackathon booth?"** Personalizing by resume or by the specific role/interview someone's practicing for is the honest next step, not built tonight. Tonight's version proves the mechanism works and is personalized per-person, that's the real, demonstrable claim, a resume-aware version is a believable v2, not a promise being made now.

**"Why not a talking AI avatar for the verdict, since ElevenLabs has that now?"** Looked into it and it's a real product, but ElevenLabs' Avatars is a manual batch-generation workflow through their web UI with no API access at all yet, unusable for a per-round dynamically-generated verdict live. Noted below as considered and dropped for tonight, that's the right call, not a compromise.

**Constraint on all of the above:** every change gets a full live E2E regression check afterward, one complete Poker Face round on real hardware with the new flow in front of it, confirming claim lock, name entry, question legibility/audio, live composure movement, reveal, the honest comparison number, and the leaderboard all still work. A working demo does not get risked for polish.

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

- Serial communication flakiness between Arduino and Pi under time pressure, mitigate by fully testing Round 1's pipeline before adding the Presage/OpenCV rounds.
- Haar cascades and Presage's live read are both lighting- and framing-sensitive, test under the actual venue lighting and webcam angle before the demo, not just at a desk, a poor read live is the single biggest thing that could undercut the pitch.
- Two live network calls now, Presage per face round and ElevenLabs for the verdict, both against venue wifi, with no pre-recorded fallback for either. This is a deliberate no-fallback, fully-live decision, if either call fails mid-demo the honest move is to say so on screen, not fake a result.
- Overreaching on the claim in the pitch, saying or implying this helps with a real interview instead of the honest, demonstrable claim (see Goals & Non-Goals and Target Audience).

**Explicitly out of scope for tonight**

- CGI Northwind Brief
- Civic Tech Challenge
- Accelerometer and ultrasonic sensors, and the Steady Hands / Retreat rounds built on them, cut this pivot
- Biometric identity matching, or keeping face data past the session, still out. Presage is used for in-the-moment emotion classification only and nothing is matched to who someone is. The only face data shown next to a name is the opt-in leaderboard photo (press Y after typing the name), held in memory only until the game stops.
- ElevenLabs Avatars (talking character video), considered and dropped for tonight. Real product, but it's a manual batch-generation workflow through ElevenLabs' web UI with no API access yet, unusable for a per-round dynamically-generated verdict live. A single pre-made avatar clip recorded ahead of time as a one-time host intro (played once when someone approaches the booth, not per-round) is a defensible small addition if there's spare time, but it is not a substitute for the live verdict path and should not be pitched as one.
- UV, air quality, and barometer sensors
- Round 4 (PS4 controller trigger), unless the OpenCV rounds are done early

## Judge Assessment (Rubric Scoring, Honest Verdict)

| Criterion | Points | Likely Score | Why |
| --- | --- | --- | --- |
| Technical Execution | 15 | 7-9 | Core mechanism is a threshold comparison plus a live OpenCV read plus a TTS call, real but not deep. Serial comms, a live vision pipeline, and a live API call is more than a pure-software wrapper project, but a judge who's seen 40 projects will clock the simplicity fast. Adding the live calibration curve and the OpenCV overlay raises this. |
| Idea & Impact | 10 | 8-9 | Strongest category, and stronger after this pivot: one focused idea (your face gives you away before something high-stakes) instead of a grab-bag of unrelated sensors. Funny, instantly understandable, has a real (if modest) grounding in metacognitive calibration. |
| Design & Usability | 10 | 7-8 | Simple physical interaction (dial, press, look at camera, listen), inherently usable if the physical build and the live video feed don't feel janky live. |
| Learning & Technical Decisions | 5 | free points if earned | Articulate real decisions made during the build: why Presage plus OpenCV instead of OpenCV heuristics alone, why the accelerometer and ultrasonic rounds were cut, why there's no pre-recorded fallback anymore now that Presage is genuinely load-bearing. Cheap points, don't skip this in the pitch. |
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
- Presage API for live facial emotion/stress classification during Rounds 2-3, the actual reality-check measurement, not a demo call on the side
- Tiger Data (optional, stretch) if the session log gets upgraded to Postgres for the mini-challenge

**Dev tools**

- Git/GitHub for version control and the public FOSS repo
- Whatever the team already knows for quick scripting, don't learn a new framework tonight

## Repo Structure

```
delulu-detector/               # the GitHub repo keeps its name; the project is Hill's Kitchen
├── README.md                  # project pitch, setup instructions, demo gif
├── LICENSE                    # open license for the FOSS category
├── arduino/
│   └── delulu_gauntlet/delulu_gauntlet.ino   # reads dial/button, writes JSON over serial
├── pi/
│   ├── main.py                # serial listener + main loop
│   ├── vision.py              # OpenCV face detection + overlay, cross-check signal
│   ├── presage_client.py      # live Presage emotion/stress classification, no fallback path
│   ├── scoring.py             # gap/score calculation
│   ├── elevenlabs_client.py   # roast-or-affirm prompt building + TTS call, no fallback path
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
- `elevenlabs_client.py` and `presage_client.py` should both fail loud, not fall back to a canned line or a cached value, if either call doesn't return in time, show that plainly on the frontend instead of faking a result (see Risks)
- `vision.py` should be testable on its own against a saved video clip, not just the live webcam, so lighting or camera issues can be debugged without the whole rig running
- push early and often, a clean-looking commit history is not judged, but having actual history to point to if anyone asks how the project was built is good practice
