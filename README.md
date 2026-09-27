# Hill's Kitchen

**Your face gives you away.** Hill's Kitchen is a live self-calibration game built for Hack the Hill III. You dial in how unreadable you think your face is going to be (0-100), lock it with a button, and then an interviewer voice asks you a tough question while a webcam watches you. Presage SmartSpectra rates how neutral your expression looks during the question, the game compares that with your claim, and an ElevenLabs-voiced narrator (a skeptical interviewer who is also your brutally honest friend) affirms you or roasts you, live.

Everything in the loop is real: the dial value, the Presage reading, the gap, the score and the voiced verdict. Nothing is pre-recorded or simulated in a live round. If Presage does not return a reading, the round is not scored. If ElevenLabs fails, the screen says "verdict unavailable" instead of playing a stand-in.

The GitHub repo is still called `delulu-detector` (an earlier name); the project is Hill's Kitchen. The product thinking is in [`Hill's Kitchen — PRD.md`](<Hill's Kitchen — PRD.md>).

## What this is, honestly

- **What it measures:** Presage's 8-class facial-expression model (angry, contempt, disgust, fear, happy, neutral, sad, surprise) runs on every frame. The number the game calls **composure** is the confidence of the **neutral** class, 0-100, averaged over the question window. It is expression neutrality: how unreadable your face looked. See [`docs/calibration/composure-vs-stillness-2026-09-27.md`](docs/calibration/composure-vs-stillness-2026-09-27.md) for how that was worked out from the SDK schema.
- **What it doesn't measure:** stress, nerves, honesty, lies, or interview skill. A blank, checked-out face scores as high as a calm one, and a calm but expressive person scores lower. Heart rate and HRV are **not** measured: the bridge only requests face metrics, and a 6 s window is far too short for HRV. It is not a lie detector, not a clinical or diagnostic tool, and it won't help anyone land a job.
- **What it is:** a live demonstration that people are bad at predicting how readable their own face is, because nobody gets real-time feedback on it. Play a few rounds in a row and the gap between claim and reading is what the calibration curve tracks.
- **The pitch line:** "We're not claiming this will help you land the interview. We're demonstrating that your face gives off signals you don't control and can't accurately predict, and making that visible live is funny, and a little uncomfortable."

## The game loop

Every round is **Predict, Perform, Reveal**. At the booth (Poker Face with the browser UI) one turn goes like this:

1. **Name.** The player types their name on the booth screen (up to 16 characters). The screen then asks whether to keep a leaderboard photo: **Y** yes, **N** or Enter no (see [Privacy](#privacy)).
2. **Claim.** The player turns the Arduino dial to their claim, 0-100 ("how unreadable is my poker face going into a tough interview question"). The number moves live on screen and on the optional Grove LCD. Pressing the button **locks** it.
3. **Perform.** Only now does the camera round start. An ElevenLabs voice asks one random tough interview question (the text is shown large on screen too) while the webcam reads the face for 6 s. OpenCV draws the face box so the player can see they're in frame, and the Presage composure number moves live while they answer.
4. **Reveal.** `gap = |claim - composure|`, `score = 100 - gap`. The screen shows claim, composure, gap, score and the verdict text; the narrator speaks it. The reveal also says how this round compares with the rounds logged so far (plain counts, no invented percentile), may show a [reaction GIF](#reaction-gifs), and the leaderboard and calibration curve update.

Press **?** on the booth screen for "How this is calculated", a plain-language panel with the same math.

## Rounds

| Round (on screen) | Internal id (`--round`) | Status | Claim | Reality |
| --- | --- | --- | --- | --- |
| **Poker Face** | 5 | **The live round.** Played end to end on the rig | poker face going into a tough interview question, 0-100 | Presage neutral-expression confidence over 6 s while one question is spoken |
| Straight Face Under Pressure | 6 | Implemented and tested in code; not yet verified live on the rig | 0-100 (shown as 0-20 s of straight face) | Presage composure against the dial, while rapid-fire questions play until OpenCV sees the expression change (or 20 s) |
| Reflex | 1 | Backup only, if the camera can't be used. Not the demo | reaction speed, 0-100 | ms from an LED cue to the button press |
| Steady Hands | 2 | Cut (measures hand tremor, not the face). Runs only with `--legacy-rounds` | steadiness | accelerometer tremor |

The internal ids are what the Arduino, the session log and `--round` use, and they never change. An ultrasonic "Retreat" round was planned and cut before it was built. Name entry and the photo question only exist for Poker Face with `--ui`; the other rounds log under `--player`.

## How it works

```
Rotary dial + button (+ optional Grove LCD, buzzer)
      |
Arduino (UNO R4 WiFi or classic Uno) --JSON lines over USB serial, 115200 baud--> laptop / Raspberry Pi 4
                                                                                    |- main.py            serial loop, rounds, scoring
                                                                                    |- scoring.py         gap and score
USB webcam ------------------------------------------------------------------------> |- vision.py          OpenCV face box (+ legacy smile / frame-diff)
                                                                                    |- presage_client.py  frames -> pi/presage/bridge.mjs (SmartSpectra SDK) -> composure
                                                                                    |- elevenlabs_client.py  question + verdict TTS --> speaker
                                                                                    |- session_log.py     data/sessions.db (SQLite, the game's own log)
                                                                                    |- tiger_store.py     optional copy to Tiger Data (Timescale)
                                                                                    |- ui_server.py + camera_feed.py --> browser (state, SSE, MJPEG)
```

The Arduino only reads the dial and button and prints JSON; all game logic runs on the computer. The webcam plugs into the computer, not the Arduino. The Presage bridge gets the frames the game already reads; it does not open a camera of its own.

## Scoring

- **Poker Face / Straight Face (live):** performance = Presage composure (0-100, the mean of the samples the bridge returned for the window). `gap = |claim - performance|`, `score = round(100 - gap)`. Logged with `unit` = `composure`.
- **Verdict tiers:** gap 0-10 `validated`, up to 25 `mild`, up to 45 `spicy`, above that `delulu`. Each tier has lines for over-confident and under-confident (sandbagging) players.
- **Not scored, logged or spoken:** a face in fewer than half the frames (`no_face`), a camera that delivers no frames (`camera_read`), and any Presage failure (bridge didn't start, timeout, SDK error, a window with no sample). No number is invented; the console says what went wrong and the player presses again.
- **Reflex:** 150 ms or faster = 100, 600 ms or slower = 0, linear and clamped (`REFLEX_FAST_MS`, `REFLEX_SLOW_MS`). A false start or timeout scores 0 and has no gap, so it never counts as a best or worst gap.
- **Leaderboard:** per player best gap, worst ("most delulu") gap, rounds played and average score. **Calibration curve:** gap by round number, so you can see whether a player's gap shrinks as they play.

All thresholds live in `pi/config.py`.

## Voice

`pi/elevenlabs_client.py` calls ElevenLabs text-to-speech (`POST /v1/text-to-speech/{voice_id}`) twice per face round:

- **The question.** One random line from `POKER_QUESTION_LINES` (Straight Face: `PRESSURE_QUESTION_LINES`, back to back) is synthesized live when the window starts and shown on screen. If that call fails, the console and screen say "question unavailable" and nothing else plays.
- **The verdict.** A line picked by round and tier (`POKER_TEMPLATES`, `STRAIGHT_TEMPLATES`, `TEMPLATES` for Reflex) is filled in with `{player}`, `{claim}`, `{perf}` and `{gap}`, printed to the console, then spoken. The call has a **3 s total budget** (`ELEVENLABS_TIMEOUT_S`). There are no pre-recorded verdict mp3s: a missing key, timeout, HTTP error or empty audio plays nothing, and the UI shows "verdict unavailable".

Verdict lines are capped at 18 words (`MAX_VERDICT_WORDS`), each key keeps at least 4 lines, and the narrator never repeats the same line twice in a row for a player. Keep new lines PG-13 and never about appearance or identity; `pi/tests/test_narrator.py` checks the limits. The key, voice and model come from `.env` (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`).

## Reaction GIFs

The reveal can show a reaction GIF picked by file name from `frontend/src/assets/reactions/` (`67-` when a 67 is on screen, then `validated-`, `mild-`, `spicy-`, `delulu-` by gap, `any-` as a catch-all; `.gif`, `.webp` or `.png`). The files are **not committed** (they're other people's memes and film clips); drop them into that folder on the booth machine and run `npm run build`. With no matching file the reveal simply has no GIF. Details in [`frontend/src/assets/reactions/README.md`](frontend/src/assets/reactions/README.md).

## Tiger Data (optional)

Set `TIGER_DATA_URL` in `.env` to a Tiger Data (Timescale) service connection string and every scored round is also copied to a Timescale hypertable (`pi/tiger_store.py`, needs `psycopg`, which is in `pi/requirements.txt`). SQLite stays the game's own log; Tiger is a mirror.

- `round_events` is a hypertable on `ts`, one row per scored round: session, player, round number and type, claim, composure (`confidence_score`), `gap_score`, and `heart_rate` / `hrv` columns that are always NULL (not measured).
- `gap_by_round_daily` is a continuous aggregate (per player, round number and day), which the **calibration curve** reads as the average gap by round number across every session.
- The **leaderboard** becomes all-time: every player ranked by average gap across all logged sessions.
- Writes happen on a background thread that never blocks or fails a round. Reads (`GET /api/tiger/curve`, `GET /api/tiger/leaderboard`) have a short timeout; when Tiger is off or unreachable they return 503 and the UI falls back to the local SQLite data.

The console prints `Tiger Data: on` or `off` at startup. To copy rounds already in SQLite logs (safe to re-run; duplicates are skipped):

```bash
python pi/tiger_backfill.py data/sessions.db
```

## Privacy

- Frames are processed **in memory**, one at a time, and **never saved to disk**. The OpenCV code has no image-writing or network calls (a test checks this). Presage SmartSpectra runs on the device; the API key only authorizes the SDK.
- Only numbers are logged (claim, composure, gap, score, and some OpenCV readings in `extra`). Nothing identifies a face or matches it to a person.
- With `--ui`, the newest frame is held in memory to stream to the browser on this machine (`/api/camera.mjpg`, served on `--ui-host`, localhost by default). It is never stored.
- **The one exception is opt-in:** a player who presses **Y** after typing their name keeps one webcam photo from 3 s into the question, shown when their name is clicked on the leaderboard. It stays in the game's memory on this laptop, is never written to disk, SQLite or Tiger Data, and is gone when the game stops.

## Setup

### Computer (laptop or Raspberry Pi 4)
```bash
sudo apt install -y python3-venv mpg123            # mpg123 plays the spoken question and verdict
git clone https://github.com/anakafeel/delulu-detector && cd delulu-detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r pi/requirements.txt                  # opencv-python>=4.8,<5 (keep it below 5), psycopg for Tiger Data
cd pi/presage && npm install && cd ../..            # SmartSpectra bridge (Node) for live face rounds
cd frontend && npm install && npm run build && cd ..  # browser UI, served by Python (Node 20.19+)
cp .env.example .env                                # then fill in the keys below
sudo usermod -aG dialout $USER                      # serial port access (log out and back in)
```

`.env` (never commit it; `.env.example` lists every option):

| Variable | Needed for |
| --- | --- |
| `ELEVENLABS_API_KEY` (+ optional `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`, `ELEVENLABS_TIMEOUT_S`) | the spoken question and verdict |
| `SMARTSPECTRA_API_KEY` (`PRESAGE_API_KEY` also read) | live face rounds; without it `--round 5` / `--round 6` exit before the first claim |
| `TIGER_DATA_URL` | optional Tiger Data mirror; empty = off |
| `DELULU_CAMERA_INDEX`, `DELULU_SERIAL_PORT`, `DELULU_DB_PATH`, `DELULU_AUDIO_PLAYER`, `DELULU_CASCADE_DIR` | optional overrides |

Notes: opencv-python 5.x removed `cv2.CascadeClassifier`, which the face box uses, so keep the `<5` pin (`opencv-python-headless>=4.8,<5` also works, without `--preview`). OpenCV builds without `cv2.data` (such as apt's `python3-opencv`) need `DELULU_CASCADE_DIR`, e.g. `/usr/share/opencv4/haarcascades`. `PRESAGE_NODE` overrides the `node` binary for the bridge.

### Arduino
The sketch is `arduino/delulu_gauntlet/delulu_gauntlet.ino` (the folder keeps the old name; the Arduino IDE needs the sketch inside a folder of the same name). It builds for the UNO R4 WiFi (`arduino:renesas_uno:unor4wifi`) and the classic Uno (`arduino:avr:uno`). It includes `rgb_lcd.h`, so install the **Grove - LCD RGB Backlight** library first:

```bash
arduino-cli core install arduino:renesas_uno        # or arduino:avr for a classic Uno
arduino-cli lib install "Grove - LCD RGB Backlight"
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi arduino/delulu_gauntlet
arduino-cli upload  --fqbn arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 arduino/delulu_gauntlet
```

In the Arduino IDE: install the board core and the "Grove - LCD RGB Backlight" library, open the sketch, pick the board and port, Upload. The Serial Monitor at 115200 shows the JSON lines.

### Wiring (Grove Base Shield or breadboard)

| Part | Pin | Notes |
| --- | --- | --- |
| Rotary angle sensor | A0 (`DIAL_PIN`) | the claim for every round |
| Button | D2 (`BUTTON_PIN`) | Grove button (HIGH when pressed): `BUTTON_ACTIVE_LOW 0`, the default. A plain tactile button to GND: `BUTTON_ACTIVE_LOW 1` (enables the pull-up). The wrong setting makes claims lock on their own |
| Grove LCD RGB Backlight | I2C (A4/A5) | optional: shows `Claim: N`, a bar and a blue-to-red backlight while the dial turns. Local only; the serial protocol doesn't change |
| Buzzer / piezo | D6 (`BUZZER_PIN`) | optional: pitch-mapped ticks as the dial turns, cue beeps. `USE_BUZZER 0` if none |
| Cue | onboard | the `L` LED, plus the 12x8 LED matrix on the UNO R4 WiFi. Nothing to wire |
| A1 | leave unconnected | floating noise seeds the Reflex random delay |
| Webcam | USB on the **computer** | not on the Arduino |
| USB | USB-C (R4 WiFi) / USB-B (Uno) | to the computer: power and serial |

All pins and timings are `#define`s at the top of the sketch. The accelerometer for the cut Steady Hands round is not needed.

## Run

The booth setup (live Poker Face, Arduino on `/dev/ttyACM0`, external webcam at index 2, browser UI):

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --camera 2 --ui     # then open http://127.0.0.1:8765
```

Players type their names on screen, so `--player` isn't needed here (rounds are logged as `Guest` until someone types a name, and again after 90 s idle). The author's machine wraps this exact command in a local, untracked `start.sh` helper; it is not part of the repo.

Other runs:

```bash
python pi/main.py --port /dev/ttyACM0 --player Saim --round 6 --camera 2 --ui   # Straight Face
python pi/main.py --port /dev/ttyACM0 --player Saim                            # Reflex (the default round, backup only)
python pi/main.py --leaderboard                                                # print the leaderboard and exit
```

Opening the port can reset the board, so the game waits 2 s before listening. Each run gets its own session id; rows go to `data/sessions.db`.

Flags (`python pi/main.py --help`):

| Flag | Meaning |
| --- | --- |
| `--port`, `--baud` | serial port (default from `DELULU_SERIAL_PORT`, else `/dev/ttyACM0`) and baud (115200) |
| `--round {1,2,5,6}` | 1 Reflex (default), 5 Poker Face, 6 Straight Face; 2 needs `--legacy-rounds` |
| `--player NAME` | name for the session log (with `--ui --round 5` the screen asks instead) |
| `--camera N` | webcam index for face rounds (default `POKER_CAMERA_INDEX` = 0; on Linux `ls /dev/video*`) |
| `--video PATH` | face rounds: read a saved clip instead of the webcam |
| `--preview` | face rounds: local OpenCV window with the face / smile boxes (nothing saved) |
| `--ui`, `--ui-port`, `--ui-host` | browser UI (default port 8765, host 127.0.0.1; `0.0.0.0` to reach it from another device) |
| `--calibrate` | print raw OpenCV values per window; no scoring, logging, voice or Presage (see [Calibration](#calibration-and-camera-position)) |
| `--mock`, `--rounds`, `--seed`, `--mock-delay` | simulate the Arduino (and, for face rounds, the camera) with no hardware |
| `--no-audio` | don't play audio |
| `--db PATH` | SQLite path (default `data/sessions.db`) |
| `--legacy-rounds` | allow the cut Steady Hands round (`--round 2`) |

### Without hardware
```bash
python pi/main.py --mock --player Tester --rounds 4 --seed 1          # Reflex rounds from a simulated player
python pi/main.py --mock --round 5 --player Tester --ui               # simulated Poker Face in the browser UI
python pi/main.py --mock --round 5 --video clip.mp4 --ui              # a saved clip instead of the fake camera
```

`--mock` feeds the game the same JSON lines the Arduino prints. For the face rounds it uses a fake camera and detector (or `--video`) and scores the **legacy OpenCV metric**, not Presage, so no Presage key is needed. `--mock-delay 0` runs fast, `--no-audio` runs silent.

### Frontend development
The UI is React + Vite in `frontend/` (scripts from `frontend/package.json`):

```bash
cd frontend
npm run dev:preview    # no Arduino, no camera: the screens walk idle, claim, measuring and reveal on their own (keys 1-4 pin a screen, 0 resumes)
npm run dev            # against a running `python pi/main.py ... --ui`; Vite proxies /api to port 8765
npm run build          # production build into frontend/dist, which pi/ui_server.py serves
npm run lint           # oxlint
```

`DELULU_API=http://host:port npm run dev` points the dev server at another address. `pi/ui_server.py` (stdlib only) exposes `GET /api/state`, `GET /api/events` (Server-Sent Events), `GET /api/camera.mjpg`, `POST /api/player` (name + photo consent), `GET /api/photo`, `GET /api/health` and the Tiger endpoints above. A UI problem never stops a round.

## Calibration and camera position

The live score is Presage's own classification, so there are no thresholds to tune for it. The pre-demo check that matters is **camera position**: the whole face, chin to the top of the head, centered in the frame. Presage reports framing hints (`Move up` / `Move down`) and a window with no composure sample isn't scored. Notes from the rig are in [`docs/calibration/framing-2026-09-26.md`](docs/calibration/framing-2026-09-26.md).

`--calibrate` is the **legacy OpenCV path** (Haar smile fraction for Poker Face, frame differencing for Straight Face). It prints each window's raw numbers and scores nothing. It is still useful for checking lighting, face detection (`face_frac`) and frame rate, and it drives `--mock` / `--calibrate` scoring, but it does not tune the live round:

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --calibrate --camera 2 --preview
python pi/vision.py --video clip.mp4 --round poker --windows 3        # the same metric on a saved clip
```

The OpenCV settings (`VISION_DETECT_WIDTH`, `FACE_MIN_SIZE_FRAC`, `SMILE_*`, `POKER_BEST_FRAC` / `POKER_WORST_FRAC`, `STRAIGHT_*`) are in `pi/config.py`.

## Serial protocol

115200 baud, one JSON object per line. Pi to Arduino (read between rounds):

| Line | Effect |
| --- | --- |
| `R1` / `R5` / `R6` (`R2` legacy) | select the round; answered with `{"type":"status","state":"mode","round_id":5,...}` |
| `W<ms>`, e.g. `W6000` | face-round cue length, 1000-30000 ms (6000 for Poker Face, 20000 for Straight Face) |
| `S` | during a Straight Face cue only: end it now (the face changed) |
| `?` | report the current mode |

Arduino to Pi:

```json
{"type":"dial","value":57}
{"type":"status","state":"locked","claim":72}
{"type":"claim","round_id":5,"seq":6,"claim":72}
{"type":"result","round_id":1,"seq":3,"claim":72,"actual":243,"unit":"ms","false_start":false,"timeout":false}
```

`dial` lines stream the smoothed knob position while waiting for a lock (for the live claim on screen). In a face round the Arduino only sends the locked claim; the computer measures and builds the result. The game re-sends the round selection if no ack arrives, and again after a board reset.

## Session log

`data/sessions.db` (gitignored) has one row per round: player, session id, per-player round number, round id, claim, performance, `actual` + `unit` (`composure` for a live face round, `ms` for Reflex, `smile_pct` / `s` for mock face rounds, `mg_rms` for the legacy round), false start / timeout flags, gap, score, tier, and `extra` (JSON). The verdict text is printed and shown, not stored. Older v1 files are upgraded in place on first open, after a one-off backup to `data/sessions.pre-v2-backup.db`.

## Tests

```bash
source .venv/bin/activate
python -m pytest pi/tests -q
```

The tests need no camera, Arduino, network or API keys (`test_vision_cv2.py` is skipped without OpenCV). They cover scoring and tiers, the SQLite log and leaderboard, serial parsing and round selection, whole Poker Face and Straight Face rounds on a fake camera, the Presage client (missing key, SDK error, averaging only the returned samples, never inventing a number), verdict lines (word limit, no repeats), the TTS budget and failure paths, the Tiger Data store, the UI server (including name entry and photos) and the camera feed.

CI (`.github/workflows/ci.yml`) runs the tests, builds and lints the frontend, and compiles the sketch for both boards. The sketch compile job currently fails in CI because it doesn't install the Grove LCD library that the sketch now includes; the sketch builds locally once `arduino-cli lib install "Grove - LCD RGB Backlight"` is done.

## Legacy: Steady Hands

Cut from Hill's Kitchen because it measures hand tremor, not the face. The code, tests and sketch mode stay: `python pi/main.py --legacy-rounds --round 2 --port /dev/ttyACM0` (or `--mock --legacy-rounds --round 2`). It needs a Grove LIS3DHTR accelerometer on the I2C port; the player holds it still for 5 s and the Arduino reports the RMS tremor in mg. Thresholds (`STEADY_*` in `pi/config.py`) came from one calibration session, recorded in [`docs/calibration/round2-2026-09-26.md`](docs/calibration/round2-2026-09-26.md).

## Repo layout
```
delulu-detector/                       # the repo keeps its name; the project is Hill's Kitchen
├── README.md
├── Hill's Kitchen — PRD.md            # product requirements: goals, honest framing, rounds, status
├── LICENSE                            # MIT
├── .env.example
├── .github/workflows/ci.yml           # pytest, sketch compile for both boards, frontend build + lint
├── arduino/delulu_gauntlet/delulu_gauntlet.ino
├── pi/
│   ├── main.py                        # serial loop, rounds, flags
│   ├── config.py                      # every tunable number and path
│   ├── scoring.py                     # gap, score, tiers
│   ├── presage_client.py              # frames in, Presage composure 0-100 out
│   ├── presage/bridge.mjs             # SmartSpectra SDK bridge (npm install here); opens no camera
│   ├── elevenlabs_client.py           # question + verdict lines, TTS with a 3 s budget
│   ├── poker_round.py                 # Poker Face: claim -> spoken question + camera window -> result
│   ├── straight_round.py              # Straight Face: claim -> rapid-fire questions until the face changes
│   ├── vision.py                      # webcam / --video, Haar face box, legacy smile + frame-diff (also a CLI)
│   ├── camera_feed.py                 # MJPEG frames with the overlay for the browser
│   ├── ui_server.py                   # /api/state, /api/events, /api/camera.mjpg, /api/player, serves frontend/dist
│   ├── session_log.py                 # data/sessions.db
│   ├── tiger_store.py                 # optional Tiger Data mirror + curve / leaderboard reads
│   ├── tiger_backfill.py              # copy existing SQLite rounds to Tiger Data
│   ├── requirements.txt
│   └── tests/
├── frontend/                          # React + Vite booth UI
│   └── src/assets/reactions/          # reaction GIFs (not committed)
├── docs/
│   ├── devpost.md                     # Devpost write-up
│   ├── pitch_script.md                # 5-minute judging script
│   └── calibration/                   # dated notes from the rig
├── data/                              # sessions.db is created here (gitignored)
└── assets/
```

## License
MIT © 2026 Saim Hashmi
