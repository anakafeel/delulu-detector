# Delulu Detector: 5-minute pitch (skeleton)

## 0:00 Hook (20s)
- "Rate how fast your reflexes are, 0 to 100." Hand the dial to a judge.

## 0:20 The honest framing (30s)
- Say exactly: "We're not claiming this makes you better at anything, we're demonstrating that people are reliably overconfident about tasks they've never gotten real feedback on before, and making that visible live is funny."

## 0:50 Live round (90s)
- Judge sets claim, presses to lock, waits for the cue, presses.
- Narrator verdict. Point at the gap and score on screen.

## 2:20 Second/third round (60s)
- Same judge again. Show the gap shrinking (calibration series printout).

## 3:20 How it works (40s)
- Dial + button -> Arduino (JSON over serial, 115200) -> Pi (score, SQLite log) -> ElevenLabs voice.
- 3 s TTS timeout, pre-recorded fallback line so the demo never stalls.

## 4:00 Decisions we made (30s)
- Why serial, why one round first, why we left out UV/air-quality/barometer (they measure the room, not the player), why Presage was dropped.

## 4:30 Close + leaderboard (30s)
- Most delulu of the night. Thank you.

## Judge Q&A prep
- "Does this train people?" No. See honest framing.
- "Why is 150 ms = 100?" Typical fast human visual reaction; bounds live in `pi/config.py`.
- "What if the API dies?" Fallback audio / printed verdict after 3 s.
