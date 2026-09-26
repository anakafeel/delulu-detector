# Delulu Detector

A physical, arcade-style party game built for Hack the Hill III. You set a 0-100 confidence claim on a rotary dial, do a short physical challenge, a sensor measures what actually happened, and an ElevenLabs-voiced narrator calls out the gap: "validated" if you knew yourself, escalating roasts if you didn't. The honest pitch: **we're not claiming this makes you better at anything, we're demonstrating that people are reliably overconfident about tasks they've never gotten real feedback on before**, and making that visible live is funny.

This milestone ships **Round 1, the Reflex Round**, end to end: dial claim, button lock, random delay, cue, reaction timer, serial JSON, Pi scoring, SQLite session log and leaderboard, and the ElevenLabs verdict with an offline fallback. **Round 2, the Steady Hands Round** (dial + accelerometer, see [Round 2](#round-2-steady-hands)) runs on the same sketch, scoring, log and voice.

## How it works

```
Rotary dial + button (+ accelerometer) --> Arduino (UNO R4 WiFi or classic Uno) --JSON over USB serial (115200 baud)--> Raspberry Pi 4
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

At boot the sketch prints one extra status line naming the accelerometer it found, for example `{"type":"status","state":"ready","accel":"LIS3DH@0x19"}` (or `"accel":"none"`). The Round 1 result and status lines are unchanged. Round 2 lines and the round selection (Pi to Arduino) are described under [Round 2](#round-2-steady-hands).

This is the PRD's `{claim, actual, round_id}` plus a few extra fields. `round_id` is the round **type** (1 = Reflex, 2 = Steady Hands). `seq` counts attempts since the Arduino booted. The Pi keeps its own per-player round numbers. The Pi ignores `status` lines and anything that isn't valid JSON, like boot noise or half-lines.

Live dial (for the browser UI only): while it waits for the lock press, the sketch also prints `{"type":"dial","value":57}`, the knob position on the same 0-100 scale as the claim. It is smoothed, sent only when the value changes by 1 or more (with a little hysteresis so it doesn't flicker), at most every 100 ms, plus once after boot, after every round and after every command. The `locked` status line carries the claim it just read: `{"type":"status","state":"locked","claim":72}`. Both are additions: the Pi never prints dial lines, and `--calibrate` and the scoring ignore them. The Pi also works with an older sketch that doesn't send them (the UI then shows `?` until the result).

### Scoring
- Reaction time to performance (0-100): **150 ms or faster = 100, 600 ms or slower = 0**, linear in between, clamped. You can change this in `pi/config.py` (`REFLEX_FAST_MS`, `REFLEX_SLOW_MS`).
- `gap = |claim - performance|` (both 0-100). `score = round(100 - gap)`.
- Verdict tiers: gap 0-10 is `validated`, up to 25 is `mild`, up to 45 is `spicy`, anything above is `delulu`. Each tier has over- and under-confident lines.
- False start / timeout: always **score 0**, whatever the claim, and keep the tier `false_start` or `timeout`. Nothing was measured, so these rounds have no performance and no gap (stored as NULL). This stops a claim of 0 plus a timeout from counting as a perfect round. (`FAILED_ROUND_SCORE` in `pi/config.py`.)
- Leaderboard: best (smallest) gap, worst ("most delulu") gap, total rounds and average score per player. False starts and timeouts count toward total rounds and toward the average score (as 0), but **not** toward best gap, worst gap or the "most delulu" round.
- Calibration curve (stretch): `SessionLog.calibration_series(player, session_id=None)` returns `[(round_number, gap), ...]`, ready to plot. False starts and timeouts are skipped.

### Voice and fallback
`pi/elevenlabs_client.py` fills in a verdict line (picked by round and tier) with the numbers and sends it to `POST /v1/text-to-speech/{voice_id}` using `requests`. The whole call, including connecting, waiting for the first byte and downloading the audio, has a **3 s total budget** (`ELEVENLABS_TIMEOUT_S`). If there's no key, the call runs out of time, returns an HTTP error or empty audio, or the mp3 can't be saved, it plays a pre-recorded fallback instead: `assets/fallback_round2_<tier>.mp3` (Round 2 only), otherwise `assets/fallback_<tier>.mp3`, otherwise `assets/fallback_verdict.mp3`. If none of them exists, the verdict is text only. The verdict text is printed to the console every time, before the TTS call starts.

**The fallback mp3s are not in the repo.** `assets/` only holds a `.gitkeep`, so until you generate them the fallback is text only. `pi/make_fallbacks.py` generates them with ElevenLabs (see [Narrator](#narrator)):

- `fallback_verdict.mp3` (generic, used when there is no file for the tier)
- `fallback_validated.mp3`, `fallback_mild.mp3`, `fallback_spicy.mp3`, `fallback_delulu.mp3`
- `fallback_false_start.mp3`, `fallback_timeout.mp3`
- Round-specific versions win when present: `fallback_round2_<tier>.mp3` (for example `fallback_round2_delulu.mp3`). The plain `fallback_<tier>.mp3` lines are round-neutral, since Round 2 uses them when it has no file of its own.

Each file is optional. A tier without its own file uses `fallback_verdict.mp3`; if that is missing too, the verdict for that tier is text only.

### Narrator
The verdict lines are in `pi/elevenlabs_client.py`: `TEMPLATES` (Round 1) and `STEADY_TEMPLATES` (Round 2), one list per key (`validated`, `mild_over`, `mild_under`, `spicy_over`, ..., plus `false_start` and `timeout` for Round 1). "over" means the player claimed more than they delivered (roast them), "under" means they sandbagged (tease them gently). To add a line, append a string to the right list. It can use `{player}`, `{claim}`, `{perf}` and `{gap}`, plus `{ms}` in Round 1 or `{mg}` / `{peak}` (milli-g) in Round 2. A line that needs a reading the round doesn't have is skipped. Keep it party-friendly (PG-13 at most, nothing about appearance or identity) and keep at least 4 lines per key. The narrator never picks the same line twice in a row for one player in a session.

**Word limit: 18 words** (`MAX_VERDICT_WORDS`), counted as whitespace-separated words after filling in a 10-character name and 3-digit numbers. Short lines are quick to synthesize inside the 3 s budget and quick to say. `pi/tests/test_narrator.py` checks every line against the limit, so a line that is too long fails the tests.

The fallback lines are in `FALLBACK_LINES` in the same file. They play when the API is down, so they must not contain names or numbers, and each tier line has to work for both over- and underconfidence. Before a demo, with the real `ELEVENLABS_API_KEY` in `.env` (voice and model come from `ELEVENLABS_VOICE_ID` / `ELEVENLABS_MODEL_ID`, like the app):

```bash
python pi/make_fallbacks.py --dry-run     # prints each file and its text, needs no key, writes nothing
python pi/make_fallbacks.py               # generates the missing files in assets/
```

Existing files are skipped; `--force` regenerates them, `--only 'fallback_round2_*'` limits it to matching file names, and `--round 1` or `--round 2` to the files that round can play. On an HTTP or network error it stops with a non-zero exit code and an error message (the key is never printed); re-running keeps the files that were already written. **Listen to every generated mp3 once** before the demo, since TTS sometimes mispronounces a word or reads a line oddly. If one sounds wrong, regenerate it with `--only <file> --force`.

The clips are **not committed** (`assets/*.mp3` is gitignored), so every machine that runs the game has to generate its own, **including the demo Pi**. Without them the narrator falls back to text only when the API is slow or down. The record of the test laptop run is in [`docs/calibration/fallback-clips-2026-09-26.md`](docs/calibration/fallback-clips-2026-09-26.md).

If one round fails on the Pi (for example the SQLite write fails, the mp3 can't be written or audio playback breaks), `main.py` prints an `[error]` line and keeps listening for the next round.

## Round 2: Steady Hands

The player claims how steady they are (0 = shaky, 100 = rock still), then holds the accelerometer still for 5 s. The Arduino measures the real tremor.

### Wiring
Plug the **Grove 3-Axis Digital Accelerometer (LIS3DHTR)** into any Grove **I2C** port on the base shield. Those ports are the main `Wire` bus (SDA/SCL, shared with A4/A5), which is what the sketch uses. Not the UNO R4 WiFi's Qwiic connector: that is `Wire1` (change `ACCEL_WIRE` if you ever use it). Nothing else changes: dial on A0, button on D2. Hold the sensor board (or whatever it's mounted on) in your hand during the round.

The sketch finds the sensor on its own at boot with plain `Wire` register reads (no extra libraries): LIS3DH/LIS3DHTR at 0x19 or 0x18 (`WHO_AM_I` 0x0F = 0x33) first, which is our part, then ADXL345 (0x53/0x1D) and MPU-6050 (0x68/0x69) as a cheap fallback for other kits. Each is set to ±2 g at a 100 Hz output rate. The LIS3DH runs in 12-bit high-resolution mode, which is 1 mg per count. The boot line says what it found: `{"type":"status","state":"ready","accel":"LIS3DH@0x19"}`. With `"accel":"none"`, Round 1 works exactly as before, and a Round 2 lock press gets an error result straight away instead of hanging (the sketch probes the bus again first, so plugging the sensor in late works too).

### Flow
1. Start the Pi with `--round 2`. It sends `R2` to the Arduino (see protocol below).
2. Turn the dial to your claimed steadiness and press the button to **lock** it (same press check as Round 1).
3. Let go of the button. A 1.5 s **get ready** countdown follows: 3-2-1 on the R4 WiFi LED matrix, and the `L` LED blinks once per step on either board.
4. **Hold still** while the whole matrix (and the `L` LED) is lit: 5 s. Pressing the button now does nothing.
5. The matrix goes dark (plus a short beep if a buzzer is connected) and the result goes to the Pi.

Timings are `#define`s in the sketch: `STEADY_COUNTDOWN_MS` (1500), `STEADY_HOLD_MS` (5000), `STEADY_SAMPLE_US` (10000, i.e. 100 Hz).

### The metric
The Arduino samples the accelerometer at a fixed 100 Hz (about 500 samples) and computes the tremor itself, because streaming 500 samples over serial is fragile:

- **`actual` = RMS deviation in mg**: `sqrt(mean_i |v_i - v_mean|^2)`, where `v_i` is each 3-axis sample and `v_mean` is the mean vector over the 5 s window. Subtracting the mean removes gravity, so the metric doesn't depend on how the sensor is held, only on how much it moves. It uses exact integer running sums (`n·Σx² − (Σx)²` per axis), so there is no sample buffer and it fits the classic Uno's RAM.
- **`peak`**: the largest deviation of a single sample from the running mean of the samples before it, in mg, ignoring the first 0.1 s. This is informational only and not scored.
- **`samples`**: how many good readings went in. If fewer than 80% of the expected samples could be read, the result is an `accel_read` error instead.

### Serial protocol additions
Pi to Arduino, one short line (the sketch reads it only between rounds):

| Line | Effect | Answer |
| --- | --- | --- |
| `R1\n` | Reflex Round (the default after every boot) | `{"type":"status","state":"mode","round_id":1,"accel":"LIS3DH@0x19"}` |
| `R2\n` | Steady Hands Round | `{"type":"status","state":"mode","round_id":2,"accel":"LIS3DH@0x19"}` |
| `?\n` | no change | the same `mode` line |
| anything else | ignored | `{"type":"status","state":"error","error":"unknown_command"}` |

`main.py` sends the selection right after opening the port (after the 2 s reset wait). It sends it again if no matching `mode` ack comes back within 3 s (up to 4 tries), and right away whenever it sees the boot line (the board reset and fell back to Round 1). A result for a different round than the one selected is still scored as the round it says it is, with a note in the console.

Arduino to Pi, Round 2 result:
```json
{"type":"result","round_id":2,"seq":5,"claim":72,"actual":14.3,"unit":"mg_rms","peak":61.2,"samples":500,"false_start":false,"timeout":false}
{"type":"result","round_id":2,"seq":6,"claim":72,"actual":null,"unit":"mg_rms","peak":null,"samples":0,"false_start":false,"timeout":false,"error":"no_accel"}
```
Informational status lines during the round: `locked`, `countdown`, `hold`, `ready`. An `error` result (`no_accel` or `accel_read`) is a hardware problem, not the player's fault: the Pi prints an `[error]` line and does **not** score, log or narrate it.

### Scoring
Same rules as every round: tremor to performance (0-100) is linear and clamped: **`STEADY_BEST_MG` (35 mg RMS) or steadier = 100, `STEADY_WORST_MG` (500 mg RMS) or shakier = 0**. A hold below `STEADY_REST_MG` (30 mg RMS) means the sensor was set down rather than held (no hand is that still), so it is rejected: not scored, logged or spoken, and the player is told to pick it up. That stops "claim 100 and put it on the table" from taking the best gap. Then `gap = |claim - performance|` and `score = round(100 - gap)`, with the same tiers. Round 2 has no false starts or timeouts. Rounds of both types share the leaderboard, "most delulu" and the calibration series, because every gap is on the same 0-100 scale. `calibration_series(player, session_id, round_id=2)` gives a Round 2 only curve. The verdict lines have their own Round 2 set ("steady as a surgeon" through "hands like a leaf in a hurricane") in `pi/elevenlabs_client.py`.

### Calibrate the thresholds on the hardware
**30 / 35 / 500 mg come from calibration on our hardware (2026-09-26)**; the raw `--calibrate` output is in [`docs/calibration/round2-2026-09-26.md`](docs/calibration/round2-2026-09-26.md). With the LIS3DHTR, holds read about 21 mg RMS lying on the table (the button press carries a little vibration), about 68 in a steady hand, and about 1494 when shaken hard. That's one session and one player, so re-tune with a few more people before a demo:

```bash
python pi/main.py --port /dev/ttyACM0 --round 2 --calibrate
```

`--calibrate` prints each hold's raw `tremor ... mg RMS`, `peak` and `samples`, plus the running min, median and max. Nothing is scored, logged or spoken, and the database isn't touched. Do a few holds with the sensor resting on the table (the noise floor), a few honest "as still as I can" holds in the hand, and a few deliberately shaky ones. Then set `STEADY_REST_MG` between the table holds and the stillest in-hand holds, `STEADY_BEST_MG` just above `STEADY_REST_MG`, and `STEADY_WORST_MG` around a clearly shaky hold in `pi/config.py`. If you ever swap in a different accelerometer, recalibrate: the noise floor is different for each part.

## Session log schema
`data/sessions.db` has one row per round. Schema v2 (this version) adds `actual` (the raw metric), `unit` (`ms` or `mg_rms`) and `extra` (JSON, for example Round 2 `peak` and `samples`). `actual_ms` stays and is still filled for Round 1, so older queries keep working. An existing v1 file is upgraded in place the first time it's opened. The upgrade only adds columns (nothing is dropped or rewritten), copies `actual_ms` into `actual` with unit `ms` for the old rows, and runs in one transaction. Before that, a one-off copy of the old file is saved as `data/sessions.pre-v2-backup.db` (gitignored like the rest of `data/*.db`).

## Wiring (Arduino UNO R4 WiFi or classic Uno, Grove Base Shield or breadboard)

| Part | Arduino pin | `#define` | Notes |
| --- | --- | --- | --- |
| Rotary angle sensor (SIG) | A0 | `DIAL_PIN` | Grove A0 port. VCC 5V, GND |
| Button (SIG) | D2 | `BUTTON_PIN` | Grove D2 port. See "Button polarity" below |
| Cue | onboard | `CUE_LED_PIN` | The onboard `L` LED (`LED_BUILTIN`), plus the full 12x8 LED matrix on the UNO R4 WiFi. Nothing to wire |
| Buzzer / piezo | D6 | `BUZZER_PIN` | Optional. Grove buzzer or a passive piezo. Set `USE_BUZZER 0` if you have none (leaving it at 1 is harmless) |
| (nothing) | A1 | `RANDOM_SEED_PIN` | Leave unconnected. Floating noise seeds the random delay |
| Accelerometer (Round 2) | I2C (SDA/SCL = A4/A5) | `ACCEL_WIRE` | Grove 3-Axis Digital Accelerometer (LIS3DHTR) in any Grove **I2C** port. See [Round 2](#round-2-steady-hands) |
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

The `Arduino_LED_Matrix` library comes with the `arduino:renesas_uno` core, and `Wire` (used for the Round 2 accelerometer) comes with both cores, so there is nothing extra to install.

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

# Round 2, Steady Hands
python pi/main.py --port /dev/ttyACM0 --player Saim --round 2

# Leaderboard only
python pi/main.py --leaderboard
```
Opening the port can reset the board, so the Pi waits 2 s before it starts listening. To switch players, stop with Ctrl+C and restart with a new `--player`. Each run gets its own session id. Rows go to `data/sessions.db`.

Other flags: `--round {1,2}` (default 1), `--calibrate` (Round 2 raw values only, see below), `--baud`, `--db PATH`, `--no-audio`, `--ui` (live browser UI, see below).

### Run without hardware
```bash
python pi/main.py --mock --player Tester --rounds 4 --seed 1
```
`--mock` sends the Pi JSON lines in the same format the Arduino would print. The simulated player starts overconfident and recalibrates, with the odd false start. `--mock --round 2` simulates Steady Hands holds instead (with the odd accelerometer read error, which is reported and not scored), and `--mock --calibrate` exercises the calibration printout. If `ELEVENLABS_API_KEY` isn't set, this also exercises the fallback path. Add `--no-audio` for silent runs and `--mock-delay 0` for fast ones.

### Live browser UI
`--ui` shows the game in a browser while you play: idle screen, the round in progress, the claim moving live as the knob turns (with the current sketch), the locked claim while the round runs, the reveal (claim, reality, gap, tier, the narrator's line, the raw measurement) and the leaderboard and calibration curve from `data/sessions.db`.

```bash
# once per machine (needs Node 20.19+): build the frontend so Python can serve it
cd frontend && npm install && npm run build && cd ..

python pi/main.py --port /dev/ttyACM0 --player Saim --ui     # then open http://localhost:8765
python pi/main.py --mock --player Tester --ui                # simulated rounds (and knob turns); stays up until Ctrl+C
```
`pi/ui_server.py` (stdlib only) runs in a background thread: `GET /api/state` is the current state as JSON, `GET /api/events` pushes it on every change (Server-Sent Events), and `/` serves `frontend/dist`, so the venue needs no Node. A UI problem is reported once and never stops a round; if the port is taken the game runs without the UI. Flags: `--ui-port` (default 8765), `--ui-host` (default 127.0.0.1; `0.0.0.0` to open it from another device on the network). Timings (how long the reveal stays up, when it falls back to the idle screen) are `UI_*` in `pi/config.py`.

To work on the frontend, run the Python side with `--ui` and `cd frontend && npm run dev`; Vite proxies `/api` to port 8765 (`DELULU_API=http://host:port npm run dev` for another address). Add `?mock=1` to the URL (or set `VITE_USE_MOCK=1`) for the built-in simulator without any backend.

## Tests
```bash
source .venv/bin/activate
python -m pytest pi/tests -q
```
The tests cover the ms-to-performance and mg-to-performance mappings (bounds, linearity, clamping), gap, score, tiers, false start and timeout handling (including the claim-0 case), the SQLite log (fields, per-player round numbering, leaderboard and calibration series across rounds, the schema v2 migration of old `sessions.db` files), serial line parsing for both rounds, the round selection line and its ack/resend logic (with a fake serial port), `--mock` and `--calibrate` for Round 2, verdict text for every tier of both rounds (word limit, at least 4 lines per key, no back-to-back repeats), the TTS time budget and which fallback plays when TTS fails or is too slow (with a faked network), `make_fallbacks.py` (dry run, skip/force, the faked HTTP call, errors) and the main loop surviving a failed round. They never call ElevenLabs.

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
│   ├── main.py                     # serial listener + main loop (--port, --player, --round, --calibrate, --mock, --ui)
│   ├── ui_server.py                # live state for the browser UI (/api/state, /api/events, serves frontend/dist)
│   ├── config.py                   # every tunable number (ms / mg bounds, tiers, timeout, paths)
│   ├── scoring.py
│   ├── elevenlabs_client.py        # verdict lines, fallback lines, TTS with a 3 s budget
│   ├── make_fallbacks.py           # generates the fallback mp3s in assets/
│   ├── session_log.py
│   ├── requirements.txt
│   └── tests/
├── frontend/                       # React + Vite browser UI (npm run dev / npm run build)
├── data/                           # sessions.db is created here (gitignored)
├── docs/pitch_script.md
└── assets/                         # fallback mp3s go here (generate with pi/make_fallbacks.py, see "Narrator")
```

## License
MIT © 2026 Saim Hashmi
