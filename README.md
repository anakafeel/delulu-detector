# Delulu Detector

A physical, arcade-style party game built for Hack the Hill III. You set a 0-100 confidence claim on a rotary dial, do a short physical challenge, a sensor measures what actually happened, and an ElevenLabs-voiced narrator calls out the gap: "validated" if you knew yourself, escalating roasts if you didn't. The honest pitch: **we're not claiming this makes you better at anything, we're demonstrating that people are reliably overconfident about tasks they've never gotten real feedback on before**, and making that visible live is funny.

This milestone ships **Round 1, the Reflex Round**, end to end: dial claim, button lock, random delay, cue, reaction timer, serial JSON, Pi scoring, SQLite session log and leaderboard, and the ElevenLabs verdict with an offline fallback.

## How it works

```
Rotary dial + button --> Arduino (UNO R4 WiFi or classic Uno) --JSON over USB serial (115200 baud)--> Raspberry Pi 4
                                                                     |- scoring.py        (gap and score)
                                                                     |- session_log.py    (data/sessions.db)
                                                                     |- elevenlabs_client.py (TTS or fallback) --> speaker
```

The Arduino only reads sensors and prints JSON. All logic lives on the Pi.

### Round 1 flow
1. Turn the dial to your claimed reaction speed (0 = slow, 100 = elite).
2. Press the button to **lock** the claim.
3. Wait. After a random 1.5-4 s the **cue** fires: the onboard `L` LED lights and, on the UNO R4 WiFi, the whole 12x8 LED matrix lights up too. If a buzzer is connected on D6 it also beeps. No external LED is needed.
4. Press the button as fast as you can. The Arduino reports the reaction time in ms, measured from the cue to the first contact of the press.
   - Pressing before the cue is a **false start**.
   - Not pressing within 3 s is a **timeout**.

A press only counts once the button has read pressed for 10 ms in total (`PRESS_CONFIRM_MS`). Short contact bounces during that window are ignored, and the reaction time still uses the moment of first contact. The same check is used for the lock press. After every round the Arduino waits for the button to be released before it accepts the next lock press, so a late press after a timeout doesn't start a new round.

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
- False start / timeout: always **score 0**, whatever the claim, and keep the tier `false_start` or `timeout`. Nothing was measured, so these rounds have no performance and no gap (stored as NULL). This stops a claim of 0 plus a timeout from counting as a perfect round. (`FAILED_ROUND_SCORE` in `pi/config.py`.)
- Leaderboard: best (smallest) gap, worst ("most delulu") gap, total rounds and average score per player. False starts and timeouts count toward total rounds and toward the average score (as 0), but **not** toward best gap, worst gap or the "most delulu" round.
- Calibration curve (stretch): `SessionLog.calibration_series(player, session_id=None)` returns `[(round_number, gap), ...]`, ready to plot. False starts and timeouts are skipped.

### Voice and fallback
`pi/elevenlabs_client.py` fills in a verdict line (picked by tier) with the numbers and sends it to `POST /v1/text-to-speech/{voice_id}` using `requests`. The whole call, including connecting, waiting for the first byte and downloading the audio, has a **3 s total budget** (`ELEVENLABS_TIMEOUT_S`). If there's no key, the call runs out of time, returns an HTTP error or empty audio, or the mp3 can't be saved, it plays a pre-recorded fallback instead: `assets/fallback_<tier>.mp3` if it exists, otherwise `assets/fallback_verdict.mp3`. If neither file exists, the verdict is text only. The verdict text is printed to the console every time.

**The fallback mp3s are not recorded yet.** `assets/` only holds a `.gitkeep`, so right now the fallback is text only. Record the lines ahead of time (for example, generate them once with ElevenLabs while you have a network connection) and add them to `assets/` with these names:

- `fallback_verdict.mp3` (generic, used when there is no file for the tier)
- `fallback_validated.mp3`, `fallback_mild.mp3`, `fallback_spicy.mp3`, `fallback_delulu.mp3`
- `fallback_false_start.mp3`, `fallback_timeout.mp3`

Each file is optional. A tier without its own file uses `fallback_verdict.mp3`; if that is missing too, the verdict for that tier is text only.

If one round fails on the Pi (for example the SQLite write fails, the mp3 can't be written or audio playback breaks), `main.py` prints an `[error]` line and keeps listening for the next round.

## Wiring (Arduino UNO R4 WiFi or classic Uno, Grove Base Shield or breadboard)

| Part | Arduino pin | `#define` | Notes |
| --- | --- | --- | --- |
| Rotary angle sensor (SIG) | A0 | `DIAL_PIN` | Grove A0 port. VCC 5V, GND |
| Button (SIG) | D2 | `BUTTON_PIN` | Grove D2 port. See "Button polarity" below |
| Cue | onboard | `CUE_LED_PIN` | The onboard `L` LED (`LED_BUILTIN`), plus the full 12x8 LED matrix on the UNO R4 WiFi. Nothing to wire |
| Buzzer / piezo | D6 | `BUZZER_PIN` | Optional. Grove buzzer or a passive piezo. Set `USE_BUZZER 0` if you have none (leaving it at 1 is harmless) |
| (nothing) | A1 | `RANDOM_SEED_PIN` | Leave unconnected. Floating noise seeds the random delay |
| USB | USB-C (UNO R4 WiFi) or USB-B (classic Uno) | | To the Pi. This carries both power and serial |

All pin numbers and timings are `#define`s at the top of the sketch.

### Button polarity
Set `BUTTON_ACTIVE_LOW` at the top of the sketch to match your button:

- **Grove button module** (what we use): it outputs HIGH when pressed, so use `BUTTON_ACTIVE_LOW 0`. The pin is set to plain `INPUT`. This is the default.
- **Plain tactile button** wired between D2 and GND: use `BUTTON_ACTIVE_LOW 1`. The sketch then enables `INPUT_PULLUP`, so the pin idles HIGH and reads LOW when pressed.

With the wrong setting the button either reads as pressed all the time or floats and reads at random, so claims lock on their own and rounds end in false starts.

## Setup

### Arduino
The PRD lists the sketch as `arduino/delulu_gauntlet.ino`. The Arduino IDE needs every sketch inside a folder with the same name, so it lives at **`arduino/delulu_gauntlet/delulu_gauntlet.ino`**.

The same sketch builds for both boards. The LED matrix code is only compiled for the UNO R4 WiFi; on a classic Uno the cue is the `L` LED (plus the buzzer, if connected).

| Board | Core | FQBN | USB |
| --- | --- | --- | --- |
| Arduino UNO R4 WiFi | `arduino:renesas_uno` | `arduino:renesas_uno:unor4wifi` | USB-C |
| Arduino Uno (classic, R3) | `arduino:avr` | `arduino:avr:uno` | USB-B |

The `Arduino_LED_Matrix` library comes with the `arduino:renesas_uno` core, so there is nothing extra to install.

Arduino IDE: install the core for your board in Boards Manager ("Arduino UNO R4 Boards" or "Arduino AVR Boards"), open the file, pick Board **Arduino UNO R4 WiFi** or **Arduino Uno** and the right port, then Upload. Open the Serial Monitor at **115200** to see JSON lines.

arduino-cli, UNO R4 WiFi:
```bash
arduino-cli core install arduino:renesas_uno
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi arduino/delulu_gauntlet
arduino-cli upload  --fqbn arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 arduino/delulu_gauntlet
```

arduino-cli, classic Uno:
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
# With hardware (the board usually shows up as /dev/ttyACM0, sometimes /dev/ttyUSB0)
python pi/main.py --port /dev/ttyACM0 --player Saim

# Leaderboard only
python pi/main.py --leaderboard
```
Opening the port can reset the board, so the Pi waits 2 s before it starts listening. To switch players, stop with Ctrl+C and restart with a new `--player`. Each run gets its own session id. Rows go to `data/sessions.db`.

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
The tests cover the ms-to-performance mapping (bounds, linearity, clamping), gap, score, tiers, false start and timeout handling (including the claim-0 case), the SQLite log (fields, per-player round numbering, leaderboard, calibration series), serial line parsing, verdict text, the TTS time budget (with a faked network) and the main loop surviving a failed round. They never call ElevenLabs.

CI (`.github/workflows/ci.yml`) runs these tests and compiles the sketch for both `arduino:avr:uno` and `arduino:renesas_uno:unor4wifi` on every push and pull request.

## Repo layout
```
delulu-detector/
├── README.md
├── .github/workflows/ci.yml        # tests + sketch compile for both boards
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
└── assets/                         # fallback mp3s go here (none recorded yet, see "Voice and fallback")
```

## License
MIT © 2026 Saim Hashmi
