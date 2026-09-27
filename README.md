# What the Hill

<p align="center">
  <img src="frontend/src/assets/logo.png" width="220" alt="What the Hill logo: an orange fox in a green shirt and tie, scuba tank on his back, holding a finger to his lips underwater">
</p>

**Your face gives you away.** What the Hill is a live nervous-confidence check built for Hack the Hill III. Most people do not find out how they actually come across in a high-stakes moment until they are already in it. A player dials in how composed they expect to look, then does a short mock of that moment on camera. Presage reads the face live, the game compares that reading with the claim, and an ElevenLabs narrator calls the gap the moment it is computed.

https://github.com/user-attachments/assets/5e04c1db-09b3-4fd9-830d-9c0b3a61b0a2

That is the latest brag cut, 19 seconds, recorded from the live booth in the booth fonts: the real camera, anakafeel's claim of 68, composure 0, gap 68. The same file is in the repo at [`brag-output/brag.mp4`](brag-output/brag.mp4).

The product thinking, including the pitch line, the rounds, and what is still spec, is in [`What the Hill — PRD.md`](<What the Hill — PRD.md>). The GitHub repo is [anakafeel/what-the-hill](https://github.com/anakafeel/what-the-hill). The project domain is [whatthehill.wiki](http://whatthehill.wiki). It forwards to this README at the repo home, [https://github.com/anakafeel/what-the-hill](https://github.com/anakafeel/what-the-hill).

Everything in a live round is computed in the moment: the dial, the Presage reading, the gap, the score, and the spoken verdict. If Presage returns no reading, the round is not scored. If ElevenLabs fails, the screen says so. Nothing is substituted.

## The honest claim

The pitch line, from the PRD:

> We're not claiming this will help you land the interview. We're demonstrating that your face gives off signals you don't control and can't accurately predict, and making that visible live is funny, and a little uncomfortable.

**What the number is.** Presage's 8-class expression model (angry, contempt, disgust, fear, happy, neutral, sad, surprise) runs on each frame. **Composure** is the confidence of the **neutral** class, 0–100, averaged over the question window. It is how unreadable the face looked. The working-out is in [`docs/calibration/composure-vs-stillness-2026-09-27.md`](docs/calibration/composure-vs-stillness-2026-09-27.md).

**What a round shows.** People are bad at predicting how readable their own face will be, because they almost never get that feedback while the moment is happening. A few rounds in a row are the demo: the calibration curve is the gap between claim and reading, round by round.

**What it leaves alone.** It does not measure stress, nerves, honesty, or interview skill, and it does not train anyone for a real interview. A blank face and a deliberately calm face can both land on neutral. Heart rate and HRV are not read. It is not a lie detector, not a clinical tool, and not a biometric ID. Frames are not kept, except the one opt-in leaderboard photo described under [Privacy](#privacy).

## Predict, Perform, Reveal

Every round is the same three steps. At the booth, Poker Face with the browser UI, one turn goes like this:

1. **Name.** The player types their name (up to 16 characters). The screen asks whether to keep a leaderboard photo: **Y** yes, **N** or Enter no.
2. **Predict.** They turn the Arduino dial to a claim, 0–100: how unreadable their face will be through one tough question. The number moves live on screen and on the optional Grove LCD. The button locks it. A claim locked before a name is typed is not measured.
3. **Perform.** The camera round starts only after the lock. An ElevenLabs voice asks one random interview question, also shown large on screen, while the webcam reads the face for 6 seconds. OpenCV draws the face box. Presage composure moves live while they answer.
4. **Reveal.** `gap = |claim − composure|`, `score = 100 − gap`. The screen shows claim, composure, gap, score, and the verdict. The narrator speaks it. The reveal compares this round with the rows already logged tonight, in plain counts, with no invented percentile. A [reaction GIF](#reaction-gifs) may play. The leaderboard and calibration curve update.

Press **?** on the booth for "How this is calculated". Same math, plain language.

The PRD's per-player neutral-face baseline (composure as a delta from a 2–3 second capture of that player's own resting face) is specified and **not built**. The live score is the absolute neutral-class confidence above.

## Rounds

On-screen numbers follow the PRD. Internal ids are what the Arduino, the session log, and `--round` use, and they stay fixed.

| On screen | Internal id | In the live booth | Predict | Reality check |
| --- | --- | --- | --- | --- |
| **Round 1 · Reflex** | `--round 1` | Built. Backup when the camera cannot be used. | Reaction speed under pressure, 0–100 | Milliseconds from the LED cue to the button |
| **Round 2 · Poker Face** | `--round 5` | **The demo.** Played end to end on the rig. | Poker face going into one tough interview question, 0–100 | Presage neutral-class confidence over 6 seconds while that question is spoken |
| **Round 3 · Straight Face Under Pressure** | `--round 6` | Same Presage path as Poker Face. Not yet the round to claim in the pitch until it has been played live on the rig. | How long they can hold a straight face, dialed 0–100 and shown as 0–20 seconds | Presage composure while rapid-fire questions play, until OpenCV sees the expression change or 20 seconds pass |

Steady Hands (accelerometer, internal id 2) and the ultrasonic Retreat round are cut. They measure tremor and flinch, not the face. Steady Hands still runs only with `--legacy-rounds --round 2`. Name entry and the photo question exist for Poker Face with `--ui`. The other rounds log under `--player`.

## In the PRD, not in the live booth

These are written down in the PRD and are not what a judge will see tonight:

- A per-player neutral-face baseline, and scoring composure as a delta from it.
- The nihilistic-penguin mascot (walks off on a big gap, scuba-dances on a small one) and a spoken "6 7" beat in the verdict.
- Reveal Cam, a shareable snapshot at the reveal, and a PS4-trigger stretch round.
- ElevenLabs Avatars. Dropped: no API for a per-round talking character.

UV, air quality, and barometer stay out. They measure the room, not the player. Civic Tech, CGI, Solana, Gemini, Auth0, Vultr, and GoDaddy are out of scope on purpose.

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

The Arduino reads the dial and the button and prints JSON. The game logic runs on the computer. The webcam plugs into the computer, not the Arduino. The Presage bridge uses frames the game already captured. It does not open a second camera.

The booth page is on this machine at `http://127.0.0.1:8765`. Presage authorizes its key when the process starts, and ElevenLabs speaks the question and the verdict during the round. Both need a working network. There is no stand-in clip and no invented score if either call fails.

## Scoring

- **Poker Face and Straight Face:** performance is Presage composure, 0–100, the mean of the samples the bridge returned for the window. `gap = |claim − performance|`, `score = round(100 − gap)`. Logged with `unit` = `composure`.
- **Verdict tiers:** gap 0–10 `validated`, up to 25 `mild`, up to 45 `spicy`, above that `delulu`. Each tier has lines for over-confident and under-confident players.
- **Not scored, logged, or spoken:** a face in fewer than half the frames (`no_face`), a camera that delivers no frames (`camera_read`), and any Presage failure (bridge did not start, timeout, SDK error, a window with no sample). The console says what failed. The player presses again.
- **Reflex:** 150 ms or faster = 100, 600 ms or slower = 0, linear and clamped (`REFLEX_FAST_MS`, `REFLEX_SLOW_MS`). A false start or timeout scores 0 and has no gap, so it never counts as a best or worst gap.
- **Leaderboard:** per player, best gap, worst ("most delulu") gap, rounds played, and average score. **Calibration curve:** gap by round number.

Thresholds live in `pi/config.py`.

## Voice

`pi/elevenlabs_client.py` calls ElevenLabs text-to-speech (`POST /v1/text-to-speech/{voice_id}`) twice per face round. The voice is a skeptical interviewer who is also a brutally honest friend.

- **The question.** One random line from `POKER_QUESTION_LINES` (Straight Face: `PRESSURE_QUESTION_LINES`, back to back) is synthesized when the window starts and shown on screen. If that call fails, the screen says "question unavailable" and nothing else plays.
- **The verdict.** A line picked by round and tier (`POKER_TEMPLATES`, `STRAIGHT_TEMPLATES`, `TEMPLATES` for Reflex) is filled in with `{player}`, `{claim}`, `{perf}`, and `{gap}`, printed, then spoken. The call has a **3 second** total budget (`ELEVENLABS_TIMEOUT_S`). A missing key, timeout, HTTP error, or empty audio plays nothing, and the UI shows "verdict unavailable".

Verdict lines are capped at 18 words (`MAX_VERDICT_WORDS`). Each key keeps at least 4 lines. The narrator does not repeat the same line twice in a row for a player. New lines stay PG-13 and stay off appearance and identity. `pi/tests/test_narrator.py` checks the limits. The key, voice, and model come from `.env` (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`).

## Reaction GIFs

The reveal can show a reaction GIF picked by file name from `frontend/src/assets/reactions/` (`67-` when a 67 is on screen, then `validated-`, `mild-`, `spicy-`, `delulu-` by gap, `any-` as a catch-all; `.gif`, `.webp`, or `.png`). Those files are other people's clips, so they are not committed. Drop them into that folder on the booth machine and run `npm run build`. With no matching file, the reveal has no GIF. Details are in [`frontend/src/assets/reactions/README.md`](frontend/src/assets/reactions/README.md).

## Tiger Data (optional)

Set `TIGER_DATA_URL` in `.env` to a Tiger Data (Timescale) connection string and every scored round is also copied to a hypertable (`pi/tiger_store.py`, needs `psycopg` from `pi/requirements.txt`). SQLite stays the game's own log. Tiger is a mirror, and it is the optional mini-challenge, not required for the demo.

- `round_events` is a hypertable on `ts`: session, player, round number and type, claim, composure (`confidence_score`), `gap_score`. The `heart_rate` and `hrv` columns stay NULL.
- `gap_by_round_daily` is a continuous aggregate. The calibration curve reads it as the average gap by round number across sessions.
- The leaderboard, when Tiger is on, is all-time: every player ranked by average gap.
- Writes run on a background thread and never block or fail a round. `GET /api/tiger/curve` and `GET /api/tiger/leaderboard` have a short timeout. When Tiger is off or unreachable they return 503 and the UI uses SQLite.

Startup prints `Tiger Data: on` or `off`. To copy rounds already in SQLite (safe to re-run; duplicates are skipped):

```bash
python pi/tiger_backfill.py data/sessions.db
```

## Privacy

- Frames are processed in memory, one at a time, and never saved to disk. The OpenCV code has no image-writing or network calls (a test checks this). Presage SmartSpectra runs on the device. The API key only authorizes the SDK.
- The log stores numbers: claim, composure, gap, score, and some OpenCV readings in `extra`. It does not store a face and it does not match a face to a person.
- With `--ui`, the newest frame is held in memory for the browser on this machine (`/api/camera.mjpg`, `--ui-host`, localhost by default). It is never stored.
- **Opt-in photo:** a player who presses **Y** after typing their name keeps one webcam frame from 3 seconds into the question, shown when their name is clicked on the leaderboard. It stays in the game's memory on this laptop. It is never written to disk, SQLite, or Tiger Data, and it is gone when the game stops.

## Setup

### Computer (laptop or Raspberry Pi 4)

```bash
sudo apt install -y python3-venv mpg123            # mpg123 plays the spoken question and verdict
git clone https://github.com/anakafeel/what-the-hill && cd what-the-hill
python3 -m venv .venv && source .venv/bin/activate
pip install -r pi/requirements.txt                  # opencv-python>=4.8,<5 (keep it below 5), psycopg for Tiger Data
cd pi/presage && npm install && cd ../..            # SmartSpectra bridge (Node) for live face rounds
cd frontend && npm install && npm run build && cd ..  # browser UI, served by Python (Node 20.19+)
cp .env.example .env                                # then fill in the keys below
sudo usermod -aG dialout $USER                      # serial port access (log out and back in)
```

`.env` is never committed. `.env.example` lists every option.

| Variable | Needed for |
| --- | --- |
| `ELEVENLABS_API_KEY` (optional `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`, `ELEVENLABS_TIMEOUT_S`) | the spoken question and verdict |
| `SMARTSPECTRA_API_KEY` (`PRESAGE_API_KEY` is also read) | live face rounds. Without it, `--round 5` and `--round 6` exit before the first claim |
| `TIGER_DATA_URL` | optional Tiger Data mirror. Empty means off |
| `DELULU_CAMERA_INDEX`, `DELULU_SERIAL_PORT`, `DELULU_DB_PATH`, `DELULU_AUDIO_PLAYER`, `DELULU_CASCADE_DIR` | optional overrides |

opencv-python 5.x removed `cv2.CascadeClassifier`, which the face box uses, so keep the `<5` pin. `opencv-python-headless>=4.8,<5` also works, without `--preview`. OpenCV builds without `cv2.data` (such as apt's `python3-opencv`) need `DELULU_CASCADE_DIR`, for example `/usr/share/opencv4/haarcascades`. `PRESAGE_NODE` overrides the `node` binary for the bridge.

### Arduino

The sketch is `arduino/delulu_gauntlet/delulu_gauntlet.ino`. The folder keeps that name because the Arduino IDE wants the sketch inside a folder of the same name. It builds for the UNO R4 WiFi (`arduino:renesas_uno:unor4wifi`) and the classic Uno (`arduino:avr:uno`). It includes `rgb_lcd.h`, so install the **Grove - LCD RGB Backlight** library first.

```bash
arduino-cli core install arduino:renesas_uno        # or arduino:avr for a classic Uno
arduino-cli lib install "Grove - LCD RGB Backlight"
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi arduino/delulu_gauntlet
arduino-cli upload  --fqbn arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 arduino/delulu_gauntlet
```

In the Arduino IDE: install the board core and the Grove LCD library, open the sketch, pick the board and port, Upload. The Serial Monitor at 115200 shows the JSON lines. Stop the game before uploading. The game holds the port.

### Wiring

| Part | Pin | Notes |
| --- | --- | --- |
| Rotary angle sensor | A0 (`DIAL_PIN`) | the claim for every round |
| Button | D2 (`BUTTON_PIN`) | Grove button (HIGH when pressed): `BUTTON_ACTIVE_LOW 0`, the default. A plain tactile button to GND: `BUTTON_ACTIVE_LOW 1` (enables the pull-up). The wrong setting makes claims lock on their own |
| Grove LCD RGB Backlight | I2C (A4/A5) | optional: `Claim: N`, a bar, and a blue-to-red backlight while the dial turns. Local only. The serial protocol does not change |
| Buzzer / piezo | D6 (`BUZZER_PIN`) | optional: pitch rises with the knob, and the lock plays two notes. On the UNO R4 the LED matrix owns the timer `tone()` needs, so the sketch bit-bangs pin 6. `USE_BUZZER 0` if there is no buzzer |
| Cue | onboard | the `L` LED, plus the 12x8 LED matrix on the UNO R4 WiFi |
| A1 | leave unconnected | floating noise seeds the Reflex random delay |
| Webcam | USB on the **computer** | Logitech. Not on the Arduino |
| USB | USB-C (R4 WiFi) / USB-B (Uno) | power and serial |

Pins and timings are `#define`s at the top of the sketch. The accelerometer for the cut Steady Hands round is not part of the booth.

## Run

Live Poker Face, Arduino on `/dev/ttyACM0`, external webcam at index 2, browser UI:

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --camera 2 --ui
```

Then open http://127.0.0.1:8765. Players type their names on screen, so `--player` is not needed here. Until someone types a name, and again after 90 seconds idle, rounds log as `Guest`.

```bash
python pi/main.py --port /dev/ttyACM0 --player Saim --round 6 --camera 2 --ui   # Straight Face
python pi/main.py --port /dev/ttyACM0 --player Saim                            # Reflex, the no-camera backup
python pi/main.py --leaderboard                                                # print the leaderboard and exit
```

Opening the port resets the board, so the game waits 2 seconds before listening. Each run gets its own session id. Rows go to `data/sessions.db`.

Flags (`python pi/main.py --help`):

| Flag | Meaning |
| --- | --- |
| `--port`, `--baud` | serial port (default from `DELULU_SERIAL_PORT`, else `/dev/ttyACM0`) and baud (115200) |
| `--round {1,2,5,6}` | 1 Reflex, 5 Poker Face, 6 Straight Face. 2 needs `--legacy-rounds`. Default is Reflex |
| `--player NAME` | name for the session log. With `--ui --round 5` the screen asks instead |
| `--camera N` | webcam index for face rounds (default `POKER_CAMERA_INDEX`, 0). On the booth laptop the Logitech is `2` |
| `--video PATH` | face rounds: read a saved clip instead of the webcam |
| `--preview` | face rounds: local OpenCV window with the face box (nothing saved) |
| `--ui`, `--ui-port`, `--ui-host` | browser UI (default port 8765, host 127.0.0.1). `0.0.0.0` reaches it from another device |
| `--calibrate` | print raw OpenCV values per window. No scoring, logging, voice, or Presage. See [Calibration](#calibration-and-camera-position) |
| `--mock`, `--rounds`, `--seed`, `--mock-delay` | simulate the Arduino, and for face rounds the camera, with no hardware |
| `--no-audio` | don't play audio |
| `--db PATH` | SQLite path (default `data/sessions.db`) |
| `--legacy-rounds` | allow the cut Steady Hands round (`--round 2`) |

### Without hardware

```bash
python pi/main.py --mock --player Tester --rounds 4 --seed 1          # Reflex rounds from a simulated player
python pi/main.py --mock --round 5 --player Tester --ui               # simulated Poker Face in the browser UI
python pi/main.py --mock --round 5 --video clip.mp4 --ui              # a saved clip instead of the fake camera
```

`--mock` feeds the game the same JSON lines the Arduino prints. For the face rounds it uses a fake camera and detector (or `--video`) and scores the legacy OpenCV metric, not Presage, so no Presage key is needed. `--mock-delay 0` runs fast. `--no-audio` runs silent.

### Frontend development

The UI is React + Vite in `frontend/`:

```bash
cd frontend
npm run dev:preview    # no Arduino, no camera: idle, claim, measuring, and reveal walk on their own (keys 1-4 pin a screen, 0 resumes)
npm run dev            # against a running `python pi/main.py ... --ui`. Vite proxies /api to port 8765
npm run build          # production build into frontend/dist, which pi/ui_server.py serves
npm run lint           # oxlint
```

`DELULU_API=http://host:port npm run dev` points the dev server at another address. `pi/ui_server.py` exposes `GET /api/state`, `GET /api/events` (Server-Sent Events), `GET /api/camera.mjpg`, `POST /api/player` (name and photo consent), `GET /api/photo`, `GET /api/health`, and the Tiger endpoints above. A UI problem never stops a round.

The pitch and the Devpost text are [`docs/pitch_script.md`](docs/pitch_script.md) and [`docs/devpost.md`](docs/devpost.md).

## Calibration and camera position

The live score is Presage's own classification, so there is no threshold to tune for it. The pre-demo check is **camera position**: the whole face, chin to the top of the head, centered in the frame. Presage reports framing hints (`Move up` / `Move down`). A window with no composure sample is not scored. Notes from the rig are in [`docs/calibration/framing-2026-09-26.md`](docs/calibration/framing-2026-09-26.md).

`--calibrate` is the legacy OpenCV path (Haar smile fraction for Poker Face, frame differencing for Straight Face). It prints each window's raw numbers and scores nothing. It checks lighting, face detection (`face_frac`), and frame rate, and it is what `--mock` scores. It does not tune the live round.

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --calibrate --camera 2 --preview
python pi/vision.py --video clip.mp4 --round poker --windows 3
```

The OpenCV settings (`VISION_DETECT_WIDTH`, `FACE_MIN_SIZE_FRAC`, `SMILE_*`, `POKER_BEST_FRAC` / `POKER_WORST_FRAC`, `STRAIGHT_*`) are in `pi/config.py`.

## Serial protocol

115200 baud, one JSON object per line. The computer writes these between rounds:

| Line | Effect |
| --- | --- |
| `R1` / `R5` / `R6` (`R2` legacy) | select the round. Answered with `{"type":"status","state":"mode","round_id":5,...}` |
| `W<ms>`, for example `W6000` | face-round cue length, 1000–30000 ms (6000 for Poker Face, 20000 for Straight Face) |
| `S` | during a Straight Face cue only: end it now, because the face changed |
| `?` | report the current mode |

The Arduino writes:

```json
{"type":"dial","value":57}
{"type":"status","state":"locked","claim":72}
{"type":"claim","round_id":5,"seq":6,"claim":72}
{"type":"result","round_id":1,"seq":3,"claim":72,"actual":243,"unit":"ms","false_start":false,"timeout":false}
```

`dial` lines stream the smoothed knob while waiting for a lock. In a face round the Arduino sends the locked claim. The computer measures and builds the result. The game re-sends the round selection if no ack arrives, and again after a board reset. Press the button once and release. Holding it down keeps the measurement window from starting.

## Session log

`data/sessions.db` (gitignored) has one row per round: player, session id, per-player round number, round id, claim, performance, `actual` + `unit` (`composure` for a live face round, `ms` for Reflex, `smile_pct` / `s` for mock face rounds, `mg_rms` for the legacy round), false start and timeout flags, gap, score, tier, and `extra` (JSON). The verdict text is printed and shown, not stored. Older v1 files are upgraded in place on first open, after a one-off backup.

## Tests

```bash
source .venv/bin/activate
python -m pytest pi/tests -q
```

The tests need no camera, Arduino, network, or API keys (`test_vision_cv2.py` is skipped without OpenCV). They cover scoring and tiers, the SQLite log and leaderboard, serial parsing and round selection, whole Poker Face and Straight Face rounds on a fake camera, the Presage client (missing key, SDK error, averaging only the returned samples, never inventing a number), verdict lines (word limit, no repeats), the TTS budget and failure paths, the Tiger Data store, the UI server (including name entry and photos), and the camera feed.

CI (`.github/workflows/ci.yml`) runs the tests, builds and lints the frontend, and compiles the sketch for both boards. The sketch compile job does not install the Grove LCD library the sketch includes, so that job fails until `arduino-cli lib install "Grove - LCD RGB Backlight"` is added there. A local build works once that library is installed.

## Legacy: Steady Hands

Cut from What the Hill because it measures hand tremor, not the face. The code, tests, and sketch mode stay:

```bash
python pi/main.py --legacy-rounds --round 2 --port /dev/ttyACM0
python pi/main.py --mock --legacy-rounds --round 2
```

It needs a Grove LIS3DHTR accelerometer on the I2C port. The player holds it still for 5 seconds and the Arduino reports RMS tremor in mg. Thresholds (`STEADY_*` in `pi/config.py`) came from one calibration session, recorded in [`docs/calibration/round2-2026-09-26.md`](docs/calibration/round2-2026-09-26.md).

## Repo layout

```
what-the-hill/                         # github.com/anakafeel/what-the-hill
├── README.md
├── What the Hill — PRD.md             # product requirements
├── LICENSE                            # MIT
├── .env.example
├── .github/workflows/ci.yml
├── arduino/delulu_gauntlet/delulu_gauntlet.ino
├── pi/
│   ├── main.py                        # serial loop, rounds, flags
│   ├── config.py                      # every tunable number and path
│   ├── scoring.py                     # gap, score, tiers
│   ├── presage_client.py              # frames in, Presage composure 0-100 out
│   ├── presage/bridge.mjs             # SmartSpectra SDK bridge. Opens no camera
│   ├── elevenlabs_client.py           # question + verdict lines, TTS with a 3 s budget
│   ├── poker_round.py                 # Poker Face
│   ├── straight_round.py              # Straight Face Under Pressure
│   ├── vision.py                      # webcam / --video, Haar face box, legacy smile + frame-diff
│   ├── camera_feed.py                 # MJPEG frames for the browser
│   ├── ui_server.py                   # /api/state, /api/events, /api/camera.mjpg, serves frontend/dist
│   ├── session_log.py                 # data/sessions.db
│   ├── tiger_store.py                 # optional Tiger Data mirror
│   ├── tiger_backfill.py
│   ├── requirements.txt
│   └── tests/
├── frontend/                          # React + Vite booth UI
│   └── src/assets/logo.png            # the mark at the top of this README
├── docs/
│   ├── devpost.md
│   ├── pitch_script.md
│   └── calibration/
├── data/                              # sessions.db is created here (gitignored)
└── assets/
```

## License

MIT © 2026 Saim Hashmi
