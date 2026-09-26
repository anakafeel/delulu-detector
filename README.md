# Delulu Detector

A physical, arcade-style party game built for Hack the Hill III. You set a 0-100 confidence claim on a rotary dial, do a short physical challenge, a sensor measures what actually happened, and an ElevenLabs-voiced narrator calls out the gap: "validated" if you knew yourself, escalating roasts if you didn't. The honest pitch: **we're not claiming this makes you better at anything, we're demonstrating that people are reliably overconfident about tasks they've never gotten real feedback on before**, and making that visible live is funny.

This milestone ships **Round 1, the Reflex Round**, end to end: dial claim, button lock, random delay, cue, reaction timer, serial JSON, Pi scoring, SQLite session log and leaderboard, and the ElevenLabs verdict with an offline fallback.

## How it works

```
Rotary dial + button --> Arduino Uno --JSON over USB serial (115200 baud)--> Raspberry Pi 4
                                                                     |- scoring.py        (gap and score)
                                                                     |- session_log.py    (data/sessions.db)
                                                                     |- elevenlabs_client.py (TTS or fallback) --> speaker
```

The Arduino only reads sensors and prints JSON. All logic lives on the Pi.

### Round 1 flow
1. Turn the dial to your claimed reaction speed (0 = slow, 100 = elite).
2. Press the button to **lock** the claim.
3. Wait. After a random 1.5-4 s the **cue** fires (LED on and a buzzer beep).
4. Press the button as fast as you can. The Arduino reports the reaction time in ms.
   - Pressing before the cue is a **false start**.
   - Not pressing within 3 s is a **timeout**.

### Serial protocol (Arduino to Pi)
115200 baud, 8N1, one JSON object per line:

```json
{"type":"result","round_id":1,"seq":3,"claim":72,"actual":243,"unit":"ms","false_start":false,"timeout":false}
{"type":"result","round_id":1,"seq":4,"claim":90,"actual":null,"unit":"ms","false_start":true,"timeout":false}
{"type":"status","state":"ready"}
```

This is the PRD's `{claim, actual, round_id}` plus a few extra fields. `round_id` is the round **type** (1 = Reflex). `seq` counts attempts since the Arduino booted. The Pi keeps its own per-player round numbers. The Pi ignores `status` lines and anything that isn't valid JSON, like boot noise or half-lines.

### Scoring
- Reaction time to performance (0-100): **150 ms or faster = 100, 600 ms or slower = 0**, linear in between, clamped. You can change this in `pi/config.py` (`REFLEX_FAST_MS`, `REFLEX_SLOW_MS`).
- `gap = |claim - performance|` (both 0-100). `score = round(100 - gap)`.
- Verdict tiers: gap 0-10 is `validated`, up to 25 is `mild`, up to 45 is `spicy`, anything above is `delulu`. Each tier has over- and under-confident lines.
- False start / timeout: scored as performance 0, so claiming 90 and jumping the gun is a gap of 90. To void these rounds instead (logged but not scored), set `FALSE_START_PERFORMANCE` / `TIMEOUT_PERFORMANCE = None` in `pi/config.py`.
- Leaderboard: best (smallest) gap, worst ("most delulu") gap, total rounds and average score per player.
- Calibration curve (stretch): `SessionLog.calibration_series(player, session_id=None)` returns `[(round_number, gap), ...]`, ready to plot.

### Voice and fallback
`pi/elevenlabs_client.py` fills in a verdict line (picked by tier) with the numbers and sends it to `POST /v1/text-to-speech/{voice_id}` using `requests`. The whole call has a **3 s budget** (`ELEVENLABS_TIMEOUT_S`). If there's no key, the call times out, returns an HTTP error or returns empty audio, it plays a pre-recorded fallback instead: `assets/fallback_<tier>.mp3` if it exists, otherwise `assets/fallback_verdict.mp3`. If neither file exists, the verdict is text only. The verdict text is printed to the console every time.

Record your fallback lines ahead of time (for example, generate them once with ElevenLabs while you have a network connection) and drop them in `assets/`.

## Wiring (Arduino Uno, Grove Base Shield or breadboard)

| Part | Arduino pin | `#define` | Notes |
| --- | --- | --- | --- |
| Rotary angle sensor (SIG) | A0 | `DIAL_PIN` | Grove A0 port. VCC 5V, GND |
| Button (SIG) | D2 | `BUTTON_PIN` | Grove D2 port. The Grove button is active-HIGH (`BUTTON_ACTIVE_LOW 0`). For a bare tactile switch wired between pin and GND, set `BUTTON_ACTIVE_LOW 1` (uses INPUT_PULLUP) |
| Cue LED | D4 | `CUE_LED_PIN` | Grove LED, or an LED with a 220 Ω resistor to GND |
| Buzzer / piezo | D6 | `BUZZER_PIN` | Optional. Grove buzzer or a passive piezo |
| (nothing) | A1 | `RANDOM_SEED_PIN` | Leave unconnected. Floating noise seeds the random delay |
| USB | USB-B | | To the Pi. This carries both power and serial |

All pin numbers and timings are `#define`s at the top of the sketch.

## Setup

### Arduino
The PRD lists the sketch as `arduino/delulu_gauntlet.ino`. The Arduino IDE needs every sketch inside a folder with the same name, so it lives at **`arduino/delulu_gauntlet/delulu_gauntlet.ino`**.

Arduino IDE: open the file, pick Board **Arduino Uno** and the right port, then Upload. Open the Serial Monitor at **115200** to see JSON lines.

arduino-cli:
```bash
arduino-cli core install arduino:avr
arduino-cli compile --fqbn arduino:avr:uno arduino/delulu_gauntlet
arduino-cli upload  --fqbn arduino:avr:uno -p /dev/ttyACM0 arduino/delulu_gauntlet
```

### Raspberry Pi 4
```bash
sudo apt install -y python3-venv mpg123          # mpg123 plays the mp3 verdicts
cd delulu-detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r pi/requirements.txt
cp .env.example .env                             # then put your real ELEVENLABS_API_KEY in .env
sudo usermod -aG dialout $USER                   # serial port access (log out and back in)
```
The code reads `ELEVENLABS_API_KEY` from the environment or from `.env`. Never commit `.env`.

## Run

```bash
# With hardware (the Uno usually shows up as /dev/ttyACM0 or /dev/ttyUSB0)
python pi/main.py --port /dev/ttyACM0 --player Saim

# Leaderboard only
python pi/main.py --leaderboard
```
Opening the port resets the Uno, so the Pi waits 2 s before it starts listening. To switch players, stop with Ctrl+C and restart with a new `--player`. Each run gets its own session id. Rows go to `data/sessions.db`.

Other flags: `--baud`, `--db PATH`, `--no-audio`.

### Run without hardware
```bash
python pi/main.py --mock --player Tester --rounds 4 --seed 1
```
`--mock` sends the Pi JSON lines in the same format the Arduino would print. The simulated player starts overconfident and recalibrates, with the odd false start. If `ELEVENLABS_API_KEY` isn't set, this also exercises the fallback path. Add `--no-audio` for silent runs and `--mock-delay 0` for fast ones.

## Tests
```bash
source .venv/bin/activate
python -m pytest pi/tests -q
```
The tests cover the ms-to-performance mapping (bounds, linearity, clamping), gap, score, tiers, false start and timeout handling, the SQLite log (fields, per-player round numbering, leaderboard, calibration series) and serial line parsing.

## Repo layout
```
delulu-detector/
├── README.md
├── LICENSE                         # MIT
├── .env.example
├── arduino/delulu_gauntlet/delulu_gauntlet.ino
├── pi/
│   ├── main.py                     # serial listener + main loop (--port, --player, --mock)
│   ├── config.py                   # every tunable number (ms bounds, tiers, timeout, paths)
│   ├── scoring.py
│   ├── elevenlabs_client.py
│   ├── session_log.py
│   ├── requirements.txt
│   └── tests/
├── data/                           # sessions.db is created here (gitignored)
├── docs/pitch_script.md
└── assets/                         # fallback_verdict.mp3 (+ optional fallback_<tier>.mp3)
```

## License
MIT © 2026 Saim Hashmi
