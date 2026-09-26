# The Tell

**Your face gives you away.** The Tell is a physical, arcade-style party game built for Hack the Hill III. You set a 0-100 confidence claim on a rotary dial ("I can stay completely composed through this"), then do a short mock version of a high-stakes moment, a tough interview question or a barrage of rapid-fire ones, while a webcam and OpenCV read what your face actually did. An ElevenLabs-voiced narrator, a skeptical interviewer who is also your brutally honest friend, calls out the gap: "validated" if you knew yourself, escalating roasts if you didn't (in either direction).

### What this is, honestly
- **What it doesn't do:** it does not measure real interview or pitch performance, it does not diagnose anxiety or anything clinical, and it won't help anyone land the job. One play doesn't improve anyone's real-world composure, and a Haar cascade or a frame-difference heuristic is not a validated psychological instrument.
- **What it is:** a live demonstration of a real pattern. People are consistently bad at predicting how readable their own stress or overconfidence is, because nobody gets real-time feedback on their own face during a high-stakes moment. "The tell" here is just a measurable facial signal (a smile, an expression change) compared against a self-report. Playing a few rounds in a row, the gap should shrink as players learn their own tells; the calibration curve shows exactly that.
- **The pitch line:** "We're not claiming this will help you land the interview. We're demonstrating that your face gives off signals you don't control and can't accurately predict, and making that visible live is funny, and a little uncomfortable."

### The rounds
| Round | Internal id (`--round`) | Sensors | Claim | Reality |
| --- | --- | --- | --- | --- |
| 1. Reflex | 1 | dial + button | reaction speed under pressure (0-100) | ms from the cue to the press |
| 2. Poker Face | 5 | dial + webcam (Haar smile detector) | poker face going into a tough interview question | % of face frames with a smile in a 6 s window |
| 3. Straight Face Under Pressure | 6 | dial + webcam (frame differencing on the face / mouth) | seconds you can keep a neutral face under rapid-fire questions (dial 100 = 20 s) | seconds until your expression visibly changes |

The internal ids are what the Arduino, the session log and `--round` use, and they never change; the UI and the console label the rounds 1 / 2 / 3. **Steady Hands** (accelerometer, id 2) and **Retreat** (ultrasonic, never built on the Pi) were cut in the pivot because they measure physical steadiness, not the face. The Steady Hands code is still in the repo and the sketch, and runs with `--legacy-rounds --round 2` (see [Legacy round: Steady Hands](#legacy-round-steady-hands)). The face rounds run fully locally with OpenCV (no external API, no network); only the verdict calls ElevenLabs, with an offline fallback. The live webcam feed with the OpenCV overlay is in the browser UI (`--ui`), next to the leaderboard and the gap-over-rounds calibration curve.

## How it works

```
Rotary dial + button --> Arduino (UNO R4 WiFi or classic Uno) --JSON over USB serial (115200 baud)--> Raspberry Pi 4 (or a laptop)
                                                                     |- scoring.py        (gap and score)
                                                                     |- session_log.py    (data/sessions.db)
                                                                     |- elevenlabs_client.py (TTS or fallback) --> speaker
USB webcam (Rounds 2 and 3) -----------------------------------------> |- vision.py, poker_round.py, straight_round.py (OpenCV, local)
                                                                     |- ui_server.py + camera_feed.py --> browser (state, SSE, MJPEG)
```

The Arduino only reads sensors and prints JSON. All logic lives on the Pi. The webcam plugs into the Pi, not the Arduino.

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

At boot the sketch prints one extra status line naming the accelerometer it found, for example `{"type":"status","state":"ready","accel":"LIS3DH@0x19"}` (or `"accel":"none"`). The Round 1 result and status lines are unchanged. Round 2 lines and the round selection (Pi to Arduino) are described under [Legacy round: Steady Hands](#legacy-round-steady-hands) and the face rounds.

This is the PRD's `{claim, actual, round_id}` plus a few extra fields. `round_id` is the internal round **type** (1 = Reflex, 5 = Poker Face, 6 = Straight Face; 2 = the legacy Steady Hands). `seq` counts attempts since the Arduino booted. The Pi keeps its own per-player round numbers. The Pi ignores `status` lines and anything that isn't valid JSON, like boot noise or half-lines.

Live dial (for the browser UI only): while it waits for the lock press, the sketch also prints `{"type":"dial","value":57}`, the knob position on the same 0-100 scale as the claim. It is smoothed, sent only when the value changes by 1 or more (with a little hysteresis so it doesn't flicker), at most every 100 ms, plus once after boot, after every round and after every command. The claim that locks at the press is this same smoothed value, so the number on screen at rest is always the number that locks. The `locked` status line carries the claim it just read: `{"type":"status","state":"locked","claim":72}`. Both are additions: the Pi never prints dial lines, and `--calibrate` and the scoring ignore them. The Pi also works with an older sketch that doesn't send them (the UI then shows `?` until the result).

### Scoring
- Reaction time to performance (0-100): **150 ms or faster = 100, 600 ms or slower = 0**, linear in between, clamped. You can change this in `pi/config.py` (`REFLEX_FAST_MS`, `REFLEX_SLOW_MS`).
- `gap = |claim - performance|` (both 0-100). `score = round(100 - gap)`.
- Verdict tiers: gap 0-10 is `validated`, up to 25 is `mild`, up to 45 is `spicy`, anything above is `delulu`. Each tier has over- and under-confident lines.
- False start / timeout: always **score 0**, whatever the claim, and keep the tier `false_start` or `timeout`. Nothing was measured, so these rounds have no performance and no gap (stored as NULL). This stops a claim of 0 plus a timeout from counting as a perfect round. (`FAILED_ROUND_SCORE` in `pi/config.py`.)
- Leaderboard: best (smallest) gap, worst ("most delulu") gap, total rounds and average score per player. False starts and timeouts count toward total rounds and toward the average score (as 0), but **not** toward best gap, worst gap or the "most delulu" round.
- Calibration curve (stretch): `SessionLog.calibration_series(player, session_id=None)` returns `[(round_number, gap), ...]`, ready to plot. False starts and timeouts are skipped.

### Voice and fallback
`pi/elevenlabs_client.py` fills in a verdict line (picked by round and tier) with the numbers and sends it to `POST /v1/text-to-speech/{voice_id}` using `requests`. The whole call, including connecting, waiting for the first byte and downloading the audio, has a **3 s total budget** (`ELEVENLABS_TIMEOUT_S`). If there's no key, the call runs out of time, returns an HTTP error or empty audio, or the mp3 can't be saved, it plays a pre-recorded fallback instead: `assets/fallback_round<N>_<tier>.mp3` (internal ids 5, 6 and the legacy 2), otherwise `assets/fallback_<tier>.mp3`, otherwise `assets/fallback_verdict.mp3`. If none of them exists, the verdict is text only. The verdict text is printed to the console every time, before the TTS call starts.

**The fallback mp3s are not in the repo.** `assets/` only holds a `.gitkeep`, so until you generate them the fallback is text only. `pi/make_fallbacks.py` generates them with ElevenLabs (see [Narrator](#narrator)):

- `fallback_verdict.mp3` (generic, used when there is no file for the tier)
- `fallback_validated.mp3`, `fallback_mild.mp3`, `fallback_spicy.mp3`, `fallback_delulu.mp3`
- `fallback_false_start.mp3`, `fallback_timeout.mp3`
- Round-specific versions win when present: `fallback_round5_<tier>.mp3` (Poker Face), `fallback_round6_<tier>.mp3` (Straight Face) and the legacy `fallback_round2_<tier>.mp3`. The plain `fallback_<tier>.mp3` lines are round-neutral, since every round uses them when it has no file of its own.

Each file is optional. A tier without its own file uses `fallback_verdict.mp3`; if that is missing too, the verdict for that tier is text only.

### Narrator
The narrator's voice is a **skeptical interviewer who is also your brutally honest friend**: dry, specific, unimpressed by claims, fair about the evidence. The verdict lines are in `pi/elevenlabs_client.py`: `TEMPLATES` (Reflex), `POKER_TEMPLATES` (Poker Face), `STRAIGHT_TEMPLATES` (Straight Face) and the legacy `STEADY_TEMPLATES`, one list per key (`validated`, `mild_over`, `mild_under`, `spicy_over`, ..., plus `false_start` and `timeout` for Reflex). "over" means the player claimed more than they delivered (press hardest), "under" means they sandbagged (needle them: why lowball?). To add a line, append a string to the right list. It can use `{player}`, `{claim}`, `{perf}` and `{gap}`, plus `{ms}` in Reflex, `{smile}` (percent of face frames with a smile) / `{secs}` (whole seconds to the first smile) in Poker Face, `{held}` / `{claimsecs}` (seconds held / seconds claimed) in Straight Face, or `{mg}` / `{peak}` in the legacy Steady Hands. A line that needs a reading the round doesn't have is skipped (for example `{secs}` when the player never smiled). Keep it party-friendly (PG-13 at most, nothing about appearance or identity) and keep at least 4 lines per key. The narrator never picks the same line twice in a row for one player in a session.

**Word limit: 18 words** (`MAX_VERDICT_WORDS`), counted as whitespace-separated words after filling in a 10-character name and 3-digit numbers. Short lines are quick to synthesize inside the 3 s budget and quick to say. `pi/tests/test_narrator.py` checks every line against the limit, so a line that is too long fails the tests.

The fallback lines are in `FALLBACK_LINES` in the same file. They play when the API is down, so they must not contain names or numbers, and each tier line has to work for both over- and underconfidence. Before a demo, with the real `ELEVENLABS_API_KEY` in `.env` (voice and model come from `ELEVENLABS_VOICE_ID` / `ELEVENLABS_MODEL_ID`, like the app):

```bash
python pi/make_fallbacks.py --dry-run     # prints each file and its text, needs no key, writes nothing
python pi/make_fallbacks.py               # generates the missing files in assets/
```

Existing files are skipped; `--force` regenerates them, `--only 'fallback_round2_*'` limits it to matching file names, and `--round 1`, `--round 5` or `--round 6` (or the legacy `2`) to the files that round can play. `--questions` generates the interview-question clips instead (see [Question clips](#question-clips)). On an HTTP or network error it stops with a non-zero exit code and an error message (the key is never printed); re-running keeps the files that were already written. **Listen to every generated mp3 once** before the demo, since TTS sometimes mispronounces a word or reads a line oddly. If one sounds wrong, regenerate it with `--only <file> --force`.

The clips are **not committed** (`assets/*.mp3` is gitignored), so every machine that runs the game has to generate its own, **including the demo Pi**. Without them the narrator falls back to text only when the API is slow or down. The record of the test laptop run is in [`docs/calibration/fallback-clips-2026-09-26.md`](docs/calibration/fallback-clips-2026-09-26.md).

If one round fails on the Pi (for example the SQLite write fails, the mp3 can't be written or audio playback breaks), `main.py` prints an `[error]` line and keeps listening for the next round.

## Legacy round: Steady Hands

**Cut from The Tell** (it measures hand tremor, not the face). The code, tests and sketch mode stay so nothing is lost, but it is hidden from the game: `main.py` refuses `--round 2` unless you add `--legacy-rounds`, and the UI leaves it out of the rotation. Everything below still works that way, e.g. `python pi/main.py --legacy-rounds --round 2 --port /dev/ttyACM0`.

The player claims how steady they are (0 = shaky, 100 = rock still), then holds the accelerometer still for 5 s. The Arduino measures the real tremor.

### Wiring
Plug the **Grove 3-Axis Digital Accelerometer (LIS3DHTR)** into any Grove **I2C** port on the base shield. Those ports are the main `Wire` bus (SDA/SCL, shared with A4/A5), which is what the sketch uses. Not the UNO R4 WiFi's Qwiic connector: that is `Wire1` (change `ACCEL_WIRE` if you ever use it). Nothing else changes: dial on A0, button on D2. Hold the sensor board (or whatever it's mounted on) in your hand during the round.

The sketch finds the sensor on its own at boot with plain `Wire` register reads (no extra libraries): LIS3DH/LIS3DHTR at 0x19 or 0x18 (`WHO_AM_I` 0x0F = 0x33) first, which is our part, then ADXL345 (0x53/0x1D) and MPU-6050 (0x68/0x69) as a cheap fallback for other kits. Each is set to ±2 g at a 100 Hz output rate. The LIS3DH runs in 12-bit high-resolution mode, which is 1 mg per count. The boot line says what it found: `{"type":"status","state":"ready","accel":"LIS3DH@0x19"}`. With `"accel":"none"`, Round 1 works exactly as before, and a Round 2 lock press gets an error result straight away instead of hanging (the sketch probes the bus again first, so plugging the sensor in late works too).

### Flow
1. Start the Pi with `--legacy-rounds --round 2`. It sends `R2` to the Arduino (see protocol below).
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
python pi/main.py --port /dev/ttyACM0 --legacy-rounds --round 2 --calibrate
```

`--calibrate` prints each hold's raw `tremor ... mg RMS`, `peak` and `samples`, plus the running min, median and max. Nothing is scored, logged or spoken, and the database isn't touched. Do a few holds with the sensor resting on the table (the noise floor), a few honest "as still as I can" holds in the hand, and a few deliberately shaky ones. Then set `STEADY_REST_MG` between the table holds and the stillest in-hand holds, `STEADY_BEST_MG` just above `STEADY_REST_MG`, and `STEADY_WORST_MG` around a clearly shaky hold in `pi/config.py`. If you ever swap in a different accelerometer, recalibrate: the noise floor is different for each part.

## Round 2: Poker Face

Internal id **5** (`--round 5`). The player claims how good their poker face is going into a tough interview question (0 = cracks at anything, 100 = stone), then looks into the webcam and keeps a straight face for 6 s while the narrator asks one ("Your references didn't call us back. Any idea why?"). The Pi's webcam counts how often they smile. Everything runs locally with OpenCV's built-in Haar cascades: no external API, no network, and no extra latency (the ElevenLabs call still only happens once, for the verdict).

### Setup
- Plug a USB webcam (ours is a Logitech) into the **Pi** (or the laptop standing in for it). Nothing changes on the Arduino wiring: dial on A0, button on D2.
- OpenCV comes with `pip install -r pi/requirements.txt`, which pins **`opencv-python>=4.8,<5`**. Keep that pin: **opencv-python 5.x removed `cv2.CascadeClassifier`**, the Haar cascade API this round uses. (On a headless Pi, `opencv-python-headless>=4.8,<5` works too, just without `--preview`.) Check with `python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'CascadeClassifier'))"`, which should print `4.x True`.
- OpenCV is imported only when a face round starts, so Reflex (and `--mock --round 5` / `--mock --round 6`) run without it. Choosing a face round without it stops with a clear message saying what to install.
- The cascades come from `cv2.data.haarcascades` (`haarcascade_frontalface_default.xml`, `haarcascade_smile.xml`). For OpenCV builds without `cv2.data` (such as apt's `python3-opencv`), set `DELULU_CASCADE_DIR`, for example `/usr/share/opencv4/haarcascades`.
- Camera index: `POKER_CAMERA_INDEX` in `pi/config.py` (default **0**, usually the built-in camera; `DELULU_CAMERA_INDEX` in `.env` overrides it), or per run with **`--camera N`**. An external USB webcam gets its own index: on our laptop the Logitech Brio 101 is **`--camera 2`** (`/dev/video2`) while the built-in camera stays at 0. On Linux, `ls /dev/video*` shows the candidates (a webcam often registers two nodes, and only the first one delivers frames). On macOS the first run asks to allow the terminal to use the camera.
- Optional: generate the interview-question clips (see [Question clips](#question-clips)).

### Flow
1. Start the Pi with `--round 5`. It opens the camera (and keeps it open for the session), sends `R5`, and after the ack sends `W6000` (the window length) to the Arduino.
2. Turn the dial to your claimed poker-face confidence and press the button to **lock** it (same press check as Round 1).
3. Let go of the button. The Arduino prints the claim line and shows a **smiley** on the R4 WiFi matrix (the `L` LED lights on either board) for the window.
4. On that line the Pi starts a random interview question from `assets/questions/poker_XX.mp3` (non-blocking; no clips = silence; a machine that still has the pre-pivot `assets/jokes/` clips plays those until it regenerates) and watches your face for `POKER_WINDOW_S` (6 s). A clip still playing at the end of the window is stopped, so it never talks over the verdict.
5. The matrix goes dark (plus a short beep if a buzzer is connected), and the Pi scores, logs and narrates the result.

If no face was visible in at least half the frames, the result is a `no_face` error: like a Steady Hands sensor error it is **not scored, logged or spoken**, and the console tells the player to face the camera and press again. A webcam that delivers no frames gives a `camera_read` error, handled the same way. Wait for the verdict before pressing again: a press during the verdict queues the next window.

### Serial protocol additions
Pi to Arduino (read between rounds, like `R1`/`R2`):

| Line | Effect | Answer |
| --- | --- | --- |
| `R5\n` | Poker Face Round | `{"type":"status","state":"mode","round_id":5,"accel":"LIS3DH@0x19"}` (same mode-ack format) |
| `R6\n` | Straight Face Under Pressure (see [Round 3](#round-3-straight-face-under-pressure)) | the same mode-ack format with `"round_id":6` |
| `W<ms>\n`, e.g. `W6000\n` | face-round cue length, 1000-30000 ms (default 6000 after boot; the Pi sends 6000 for Poker Face, 20000 for Straight Face) | `{"type":"status","state":"window","window_ms":6000}`, or `{"type":"status","state":"error","error":"bad_window"}` if out of range |

The Pi sends `W` once after each `R5` ack (again after a board reset). Arduino to Pi, face-round claim line (`round_id` 5 or 6) (there is no result line from the Arduino for this round; the Pi builds the result itself):
```json
{"type":"claim","round_id":5,"seq":6,"claim":72}
```
followed by `{"type":"status","state":"ready"}` when the cue ends. `R1`, `R2`, `?` and every Round 1 and 2 line are unchanged.

### The metric
For every frame in the window (`pi/vision.py`):
1. The frame is converted to grey and **downscaled** to 320 px wide (`VISION_DETECT_WIDTH`), and the frontal-face cascade finds the **largest face** (scaleFactor 1.1, minNeighbors 5, min size 10% of the width).
2. The smile cascade runs on the **lower half of that face**, cut from the full-resolution frame and resized to 160 px wide (`SMILE_ROI_WIDTH`) so the parameters behave the same at any distance: scaleFactor **1.7**, minNeighbors **20**, min size 20% x 10% of the face width (`SMILE_*` in `pi/config.py`, all configurable).
3. **Smoothing**: a face frame only counts as smiling if the detector saw a smile in at least **2 of the last 3** face frames (`SMILE_SMOOTH_HITS` / `SMILE_SMOOTH_FRAMES`). One-frame blips never count; a real smile counts from its second frame (and one frame after it ends, so a burst still counts at full length).

Per window: **`smile_frac` = smiling face frames / face frames** (the scored metric), `face_frac` = face frames / all frames, `frames`, `fps`, and `first_smile_ms` (ms from the window start to the first smoothed smile, or `null`). On an x86 dev box the detector takes about 7-17 ms a frame at 640x480; the Pi 4 is several times slower, which is why frames are downscaled first. `--calibrate` prints the fps, so check it on the Pi, and if it drops under ~10 lower `VISION_DETECT_WIDTH`.

### Scoring
Same rules as every round: smile_frac to performance (0-100) is linear and clamped: **`POKER_BEST_FRAC` (0.03) or less = 100, `POKER_WORST_FRAC` (0.40) or more = 0**. Then `gap = |claim - performance|`, `score = round(100 - gap)`, with the same tiers. No false starts or timeouts. The row goes to the v2 schema with `actual` = smile_frac x 100, `unit` = `smile_pct`, and `smile_frac`, `face_frac`, `frames`, `fps` and `first_smile_ms` in `extra` (no migration needed). The verdict lines have their own Poker Face set (`POKER_TEMPLATES`: pressing on stone-face claims that cracked, needling modest claims that stayed stony) and fallbacks `fallback_round5_<tier>.mp3`.

### Calibrate on the hardware
**0.03 and 0.40 are starting guesses, to be calibrated on the real camera.** The smile cascade has a false-positive floor that depends on the camera, the light and the face.

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --calibrate            # add --preview to see the boxes, --camera 2 for an external webcam
```

Each window prints `smile_frac`, `face_frac`, `fps` (and frame count) and `first_smile_ms`, plus the running min, median and max of smile_frac. Nothing is scored, logged or spoken (the question still plays, so conditions match a real round; `--no-audio` turns it off). Do a few honest stone-face windows and a few where you let yourself laugh. Then set `POKER_BEST_FRAC` just above the stone-face windows and `POKER_WORST_FRAC` around a clear laugh in `pi/config.py`. Plain `--calibrate` (no `--round`) means Poker Face now. `--video clip.mp4` calibrates against a saved clip instead (see [Testing against a saved clip](#testing-the-face-rounds-against-a-saved-clip---video)). If faces are often missed (`face_frac` low in good light), sit closer or lower `FACE_MIN_SIZE_FRAC`. If you get smiles on straight faces, raise `SMILE_MIN_NEIGHBORS`; if real smiles are missed, lower it.

### --preview
`--preview` opens an OpenCV window during each window showing the camera with the **face box (green)**, the **smile box (yellow)**, `SMILE!` when a smoothed smile counts, and the time left. It is off by default, only draws on screen (nothing is saved), and closes after each window. Without a display (for example a Pi over SSH) or with `opencv-python-headless`, it prints one warning and turns itself off. The round still runs.

### Live camera in the browser (`--ui`)
With the browser UI on (`python pi/main.py --port /dev/ttyACM0 --round 5 --camera 2 --ui`), the face-round screen shows the webcam next to the dial, mirrored like a selfie, with the face and smile boxes and the live numbers: the smile % in Poker Face (the same smoothed number the round scores), the seconds held, a level bar and an "expression change" marker in Straight Face. It is served as MJPEG at `GET /api/camera.mjpg`. The slow part (`available`, `mode`, `kind`) is in the state snapshot under `camera`; the fast numbers (`face`, `smiling`, `smilePct`, and for Straight Face `phase`, `heldS`, `changedAtS`, `trigger`, `level`) are pushed as small `event: live` SSE messages at most 4 times a second (and are in `GET /api/state` for polling clients), so the history and leaderboard are never re-sent for them.

- **No second camera handle.** The stream shows the frames the round already reads (`pi/camera_feed.py`). The measurement loop only drops each frame into a single latest-frame slot, which is O(1) and never waits. Each browser's HTTP thread picks up the newest frame at most `UI_CAMERA_FPS` (12) times a second, scales it to `UI_CAMERA_MAX_WIDTH` (640), draws the overlay and encodes a JPEG (quality `UI_CAMERA_JPEG_QUALITY`, 70). Nothing is encoded while nobody watches, and a stream error only ends that browser's stream, never the round.
- **While the claim is being set** (on by default), the stream also shows a preview: raw detector output, marked PREVIEW and not scored, so the player can frame their face before locking. It reads the already-open camera at `UI_CAMERA_IDLE_FPS` (10), but only while a browser is actually watching, and it stops before every measured window (the window always gets the camera first). Set `DELULU_CAMERA_PREVIEW=0` in `.env` to show frames only during the window.
- When the camera isn't being read, the stream shows a "camera paused" placeholder. Without a camera feed (other rounds, `--mock`), the endpoint returns 503 and the UI shows a placeholder instead.
- `--preview` (the OpenCV window) works alongside the stream.

### Question clips
The face rounds' stimulus is interview questions, voiced like the narrator. The lines are in `pi/elevenlabs_client.py`: `POKER_QUESTION_LINES` (one tough mock-interview question per Poker Face window) and `PRESSURE_QUESTION_LINES` (short rapid-fire ones for Straight Face). Generate them with the same ElevenLabs key, voice and model as the verdicts:

```bash
python pi/make_fallbacks.py --questions --dry-run            # lists assets/questions/poker_01.mp3 ... pressure_18.mp3 and the text, no key needed
python pi/make_fallbacks.py --questions                      # writes the missing clips
python pi/make_fallbacks.py --questions --round 6 --force    # regenerate only the rapid-fire set
```

The same `--force` and `--only 'poker_0*'` rules apply (`--jokes` is the old name of `--questions`). The same Poker Face clip never plays twice in a row; the Straight Face clips are shuffled and played back to back until your face changes. With no clips (or `--no-audio`) the rounds run in silence.

### Privacy
Frames are processed **in memory only**, one at a time, and are **never saved to disk or sent anywhere**. The code has no image-writing or network calls in the vision path, and a test checks for that. Only numbers are logged (smile_frac, face_frac, frame count, fps, first_smile_ms; for Straight Face the seconds held, the trigger and the difference scores). Straight Face keeps its neutral-face reference as a 48 x 48 grey crop in memory for one window and drops it afterwards. `--preview` only draws on the local screen. With `--ui`, the newest frame is also held in memory (one at a time, dropped when the window ends) to stream to the browser on this machine (`/api/camera.mjpg`, served on `--ui-host`, which is localhost by default). It is never saved.

## Round 3: Straight Face Under Pressure

Internal id **6** (`--round 6`). The player claims how many seconds they can keep a neutral, composed face while rapid-fire interview questions play (dial 0-100 = 0-`STRAIGHT_MAX_S` seconds, **20 s** by default, so 50 = 10 s; the UI shows the seconds under the dial). The Pi's webcam times how long the face actually stays neutral.

### Flow
1. Start with `--round 6`. The Pi opens the camera, sends `R6`, and after the ack `W20000` (the longest the cue can run).
2. Set the dial, press to **lock**, let go. The Arduino prints `{"type":"claim","round_id":6,...}` and shows a **straight face** on the R4 WiFi matrix (`L` LED on either board).
3. The Pi starts the rapid-fire questions (`assets/questions/pressure_XX.mp3`, shuffled, back to back) and watches your face.
4. The moment your expression changes, the questions stop, the Pi sends `S` so the Arduino ends its cue early, the browser overlay shows the change marker, and the Pi scores, logs and narrates. If nothing changes, the window ends at `STRAIGHT_MAX_S` and you held the whole time.

`no_face` (no neutral baseline within 4 s, or a face in fewer than half the frames) and `camera_read` errors are handled exactly like Poker Face: not scored, logged or spoken.

### The metric (frame differencing)
For every face frame (`pi/vision.py`, `FaceSignature` + `ExpressionTracker` + `measure_straight_face`):
1. The face box (from the same Haar face detector, smoothed over frames so its jitter doesn't read as movement) is cut from the grey frame, resized to **48 x 48** (`STRAIGHT_SIG_SIZE`, which normalizes by face size and distance), lightly blurred, and its mean brightness subtracted (so auto-exposure drift doesn't count).
2. **Baseline:** the first `STRAIGHT_BASELINE_S` (1 s, at least 5 face frames) are averaged into your neutral face. Their own distances to it give the noise level.
3. **Difference:** each later frame's mean absolute difference from the neutral face, over the whole face and over the mouth region (the rows below `STRAIGHT_MOUTH_FROM` = 55%), whichever is larger, in grey levels.
4. **Change:** `STRAIGHT_HOLD_FRAMES` (3) frames in a row above `max(STRAIGHT_MIN_DIFF, baseline mean + STRAIGHT_K x baseline std)` = `max(9, mean + 4 std)`. The time of the first of those frames is the change. A smoothed Haar smile (2 of the last 3 frames) also counts (`STRAIGHT_SMILE_BREAKS`).

`held` = seconds from the start of the window to the change (or 20 if none). Scoring is the usual: `performance = held / STRAIGHT_MAX_S x 100`, `gap = |claim - performance|`. The row stores `actual` = seconds held, `unit` = `s`, and `held_s`, `max_s`, `claim_s`, `broke`, `trigger`, `face_frac`, `frames`, `fps` in `extra`. Verdicts come from `STRAIGHT_TEMPLATES` and `fallback_round6_<tier>.mp3`.

### Calibrate on the hardware
**`STRAIGHT_MIN_DIFF` 9, `STRAIGHT_K` 4 and 3 hold frames are starting guesses from synthetic clips, not from a real webcam yet.**

```bash
python pi/main.py --port /dev/ttyACM0 --round 6 --calibrate --camera 2       # add --preview to watch
```

Each window prints when it changed (and why), the baseline noise, the threshold, the **peak** difference score, face_frac and fps; the summary compares the peaks of windows you held with the ones that changed. Do a few windows where you keep a straight face on purpose and a few where you react. If calm windows still trigger (their peaks near or above the threshold), raise `STRAIGHT_MIN_DIFF`; if clear reactions are missed, lower it. Lighting matters a lot: calibrate in the venue.

## Testing the face rounds against a saved clip (`--video`)
Both face rounds can read a video file instead of the webcam, for debugging lighting or camera trouble and for calibration without the whole rig:

```bash
python pi/vision.py --video clip.mp4 --round straight              # seconds until the face changes, per 20 s window
python pi/vision.py --video clip.mp4 --round poker --windows 3     # smile fraction per 6 s window
python pi/main.py --mock --round 6 --video clip.mp4 --calibrate    # the full round (fake Arduino claims, real clip)
python pi/main.py --mock --round 5 --video clip.mp4 --ui           # ... with the browser overlay
```

A clip runs on its **own clock** (frames / fps), so a 6 s window always covers 6 s of video however fast the machine decodes it, and the same clip gives the same numbers every run. `main.py` rewinds at the end of the clip; `vision.py --no-loop` stops there instead. `pi/tests/test_straight_round.py` generates a tiny synthetic clip (a drawn face whose mouth opens at 2.0 s) and checks the change is found at 2.0 s.

## Session log schema
`data/sessions.db` has one row per round. Schema v2 (this version) adds `actual` (the raw metric), `unit` (`ms`, `smile_pct`, `s` or the legacy `mg_rms`) and `extra` (JSON, for example Poker Face (5) `smile_frac`, `face_frac`, `frames`, `fps`, `first_smile_ms`, Straight Face (6) `held_s`, `max_s`, `claim_s`, `broke`, `trigger`, or legacy Steady Hands (2) `peak` and `samples`). `actual_ms` stays and is still filled for Round 1, so older queries keep working. An existing v1 file is upgraded in place the first time it's opened. The upgrade only adds columns (nothing is dropped or rewritten), copies `actual_ms` into `actual` with unit `ms` for the old rows, and runs in one transaction. Before that, a one-off copy of the old file is saved as `data/sessions.pre-v2-backup.db` (gitignored like the rest of `data/*.db`).

## Wiring (Arduino UNO R4 WiFi or classic Uno, Grove Base Shield or breadboard)

| Part | Arduino pin | `#define` | Notes |
| --- | --- | --- | --- |
| Rotary angle sensor (SIG) | A0 | `DIAL_PIN` | Grove A0 port. VCC 5V, GND |
| Button (SIG) | D2 | `BUTTON_PIN` | Grove D2 port. See "Button polarity" below |
| Cue | onboard | `CUE_LED_PIN` | The onboard `L` LED (`LED_BUILTIN`), plus the full 12x8 LED matrix on the UNO R4 WiFi. Nothing to wire |
| Buzzer / piezo | D6 | `BUZZER_PIN` | Optional. Grove buzzer or a passive piezo. Set `USE_BUZZER 0` if you have none (leaving it at 1 is harmless) |
| (nothing) | A1 | `RANDOM_SEED_PIN` | Leave unconnected. Floating noise seeds the random delay |
| Accelerometer (legacy Steady Hands, optional) | I2C (SDA/SCL = A4/A5) | `ACCEL_WIRE` | Grove 3-Axis Digital Accelerometer (LIS3DHTR) in any Grove **I2C** port. Not needed for The Tell. See [Legacy round: Steady Hands](#legacy-round-steady-hands) |
| Webcam (Rounds 2 and 3) | none: USB on the **Pi** | | Not on the Arduino. See [Round 2: Poker Face](#round-2-poker-face) and [Round 3](#round-3-straight-face-under-pressure) |
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
pip install -r pi/requirements.txt                # includes opencv-python>=4.8,<5 for the face rounds (keep it below 5)
cp .env.example .env                             # then put your real ELEVENLABS_API_KEY in .env
sudo usermod -aG dialout $USER                   # serial port access (log out and back in)
```
The code reads `ELEVENLABS_API_KEY` from the environment or from `.env`. Never commit `.env`.

## Run

```bash
# With hardware (the board usually shows up as /dev/ttyACM0, sometimes /dev/ttyUSB0)
python pi/main.py --port /dev/ttyACM0 --player Saim

# Round 2, Poker Face (internal id 5; webcam on the Pi; --preview to see the boxes)
python pi/main.py --port /dev/ttyACM0 --player Saim --round 5
# ... with an external USB webcam (e.g. the Logitech Brio 101 at index 2) and the browser UI
python pi/main.py --port /dev/ttyACM0 --player Saim --round 5 --camera 2 --ui

# Round 3, Straight Face Under Pressure (internal id 6)
python pi/main.py --port /dev/ttyACM0 --player Saim --round 6 --camera 2 --ui

# Leaderboard only
python pi/main.py --leaderboard
```
Opening the port can reset the board, so the Pi waits 2 s before it starts listening. To switch players, stop with Ctrl+C and restart with a new `--player`. Each run gets its own session id. Rows go to `data/sessions.db`.

Other flags: `--round {1,5,6}` (default 1), `--calibrate` (raw values only: Poker Face by default, or `--round 6`), `--camera N`, `--video PATH` and `--preview` (face rounds), `--legacy-rounds` (allows the cut `--round 2`), `--baud`, `--db PATH`, `--no-audio` (also skips the question clips), `--ui` (live browser UI, see below).

### Run without hardware
```bash
python pi/main.py --mock --player Tester --rounds 4 --seed 1
```
`--mock` sends the Pi JSON lines in the same format the Arduino would print. The simulated player starts overconfident and recalibrates, with the odd false start. `--mock --round 5` simulates Poker Face windows with a fake camera and detector (no webcam, no OpenCV, instant windows): straight faces with the odd one-frame blip, smile bursts, and now and then a player who looks away (`no_face`, reported and not scored). `--mock --round 6` does the same for Straight Face (a neutral face that changes at a random moment, sometimes held to the end). `--mock --calibrate` (with or without `--round 6`) exercises the calibration printout, and `--mock --video clip.mp4` swaps the fake camera for a real clip. `--mock --legacy-rounds --round 2` still simulates Steady Hands. If `ELEVENLABS_API_KEY` isn't set, this also exercises the fallback path. Add `--no-audio` for silent runs and `--mock-delay 0` for fast ones.

### Live browser UI
`--ui` shows the game in a browser while you play: idle screen, the round in progress, the claim moving live as the knob turns (with the current sketch), the locked claim while the round runs, the reveal (claim, reality, gap, tier, the narrator's line, the raw measurement) and the leaderboard and calibration curve from `data/sessions.db`.

```bash
# once per machine (needs Node 20.19+): build the frontend so Python can serve it
cd frontend && npm install && npm run build && cd ..

python pi/main.py --port /dev/ttyACM0 --player Saim --ui     # then open http://localhost:8765
python pi/main.py --mock --player Tester --ui                # simulated rounds (and knob turns); stays up until Ctrl+C
```
`pi/ui_server.py` (stdlib only) runs in a background thread: `GET /api/state` is the current state as JSON, `GET /api/events` pushes it on every change (Server-Sent Events; while the knob turns only a small `event: dial` with `{"liveClaim": N}` is pushed, not the whole state with history), and `/` serves `frontend/dist`, so the venue needs no Node. A UI problem is reported once and never stops a round; if the port is taken the game runs without the UI. Flags: `--ui-port` (default 8765), `--ui-host` (default 127.0.0.1; `0.0.0.0` to open it from another device on the network). Timings (how long the reveal stays up, when it falls back to the idle screen) are `UI_*` in `pi/config.py`.

To work on the frontend, run the Python side with `--ui` and `cd frontend && npm run dev`; Vite proxies `/api` to port 8765 (`DELULU_API=http://host:port npm run dev` for another address). Add `?mock=1` to the URL (or set `VITE_USE_MOCK=1`) for the built-in simulator without any backend.

## Tests
```bash
source .venv/bin/activate
python -m pytest pi/tests -q
```
The tests cover the ms-to-performance and mg-to-performance mappings (bounds, linearity, clamping), gap, score, tiers, false start and timeout handling (including the claim-0 case), the SQLite log (fields, per-player round numbering, leaderboard and calibration series across rounds, the schema v2 migration of old `sessions.db` files), serial line parsing for both rounds, the round selection line and its ack/resend logic (with a fake serial port), `--mock` and `--calibrate` for Round 2, verdict text for every tier of every round (word limit, at least 4 lines per key, no back-to-back repeats), the TTS time budget and which fallback plays when TTS fails or is too slow (with a faked network), `make_fallbacks.py` (dry run, skip/force, the faked HTTP call, errors, `--round 5` / `6`, `--questions`) and the main loop surviving a failed round. For Straight Face: the seconds mapping, the tracker (baseline, threshold, hold frames), whole windows on scripted frames (expression change, smile, no face, dead camera), the question barrage, the `R6` / `W20000` / `S` serial lines, `--mock` / `--calibrate --round 6`, the UI state and overlay, and `--video` on a generated clip. For Poker Face: the smile_frac mapping, scoring, the claim line, the `W` window line, the 2-of-3 smoothing, a fake camera and detector driving whole rounds (expected smile_frac and first_smile_ms, `no_face`, a dead camera, the question clip started and stopped), `--mock` and `--calibrate --round 5`, that nothing in the vision code writes or sends frames, and that Rounds 1 and 2 still produce byte-identical mock output. They need no camera and no OpenCV: `pi/tests/test_vision_cv2.py` (real cascades loading, synthetic frames, a fake `VideoCapture`) is skipped when `cv2` isn't installed. They never call ElevenLabs.

CI (`.github/workflows/ci.yml`) runs these tests, compiles the sketch for both `arduino:avr:uno` and `arduino:renesas_uno:unor4wifi`, and builds and lints the frontend on every push and pull request.

## Repo layout
```
delulu-detector/                    # the repo keeps its name; the game is The Tell
├── README.md
├── .github/workflows/ci.yml        # tests, sketch compile for both boards, frontend build + lint
├── LICENSE                         # MIT
├── .env.example
├── arduino/delulu_gauntlet/delulu_gauntlet.ino
├── pi/
│   ├── main.py                     # serial listener + main loop (--port, --player, --round, --calibrate, --mock, --camera, --video, --preview, --ui)
│   ├── ui_server.py                # live state for the browser UI (/api/state, /api/events, /api/camera.mjpg, serves frontend/dist)
│   ├── config.py                   # every tunable number (ms / mg / smile bounds, camera + detector, tiers, timeout, paths)
│   ├── scoring.py
│   ├── elevenlabs_client.py        # verdict lines, fallback lines, TTS with a 3 s budget
│   ├── make_fallbacks.py           # generates the fallback mp3s in assets/
│   ├── session_log.py
│   ├── vision.py                   # face rounds: webcam / --video, Haar face + smile, frame differencing (also a CLI)
│   ├── poker_round.py              # Poker Face: claim line -> question + camera window -> result (+ shared camera plumbing)
│   ├── straight_round.py           # Straight Face: claim line -> rapid-fire questions + change timer -> result
│   ├── camera_feed.py              # latest-frame slot + MJPEG frames with the overlay for the browser UI (--ui)
│   ├── requirements.txt            # opencv-python>=4.8,<5 (5.x has no CascadeClassifier)
│   └── tests/
├── frontend/                       # React + Vite browser UI (npm run dev / npm run build)
├── data/                           # sessions.db is created here (gitignored)
├── docs/pitch_script.md
└── assets/                         # fallback mp3s go here (generate with pi/make_fallbacks.py, see "Narrator")
    └── questions/                  # interview-question clips (pi/make_fallbacks.py --questions)
```

## License
MIT © 2026 Saim Hashmi
