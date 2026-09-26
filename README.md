# The Tell

**Your face gives you away.** The Tell is a live composure check built for Hack the Hill III. You set a 0-100 confidence claim on a rotary dial ("I can stay completely composed through this"), then do a short mock version of a high-stakes moment, a tough interview question or a barrage of rapid-fire ones, while a webcam reads your face. On a real Poker Face or Straight Face round, Presage SmartSpectra scores neutral-expression confidence (0-100); OpenCV still draws the face box. An ElevenLabs-voiced narrator, a skeptical interviewer who is also your brutally honest friend, calls out the gap when speech works: "validated" if you knew yourself, escalating roasts if you didn't (in either direction). If ElevenLabs fails, the browser UI shows "verdict unavailable". There are no pre-recorded verdict mp3s.

### What this is, honestly
- **What it doesn't do:** it does not measure real interview or pitch performance, it does not diagnose anxiety or anything clinical, and it won't help anyone land the job. One play doesn't improve anyone's real-world composure. Presage's neutral-expression confidence is not a validated psychological instrument, and neither is the Haar cascade or the frame-difference heuristic used by `--mock` and `--calibrate`.
- **What it is:** a live demonstration of a real pattern. People are consistently bad at predicting how readable their own stress or overconfidence is, because nobody gets real-time feedback on their own face during a high-stakes moment. "The tell" here is a measurable facial signal compared against a self-report: on a live face round, Presage neutral-expression confidence (0-100); with `--mock` or `--calibrate`, an OpenCV smile or a frame difference. Playing a few rounds in a row, the gap should shrink as players learn their own tells; the calibration curve shows exactly that.
- **The pitch line:** "We're not claiming this will help you land the interview. We're demonstrating that your face gives off signals you don't control and can't accurately predict, and making that visible live is funny, and a little uncomfortable."

### The rounds
| Round | Internal id (`--round`) | Sensors | Claim | Reality |
| --- | --- | --- | --- | --- |
| 1. Reflex | 1 | dial + button | reaction speed under pressure (0-100) | ms from the cue to the press |
| 2. Poker Face | 5 | dial + webcam | poker face going into a tough interview question | live: Presage neutral-expression confidence, 0-100, over 6 s. `--mock` / `--calibrate`: % of face frames with a smile |
| 3. Straight Face Under Pressure | 6 | dial + webcam | dial 0-100 (the UI also shows that as 0-20 s of straight face under rapid-fire questions) | live: the same Presage confidence, 0-100, against the dial. The window still ends when the expression changes. `--mock` / `--calibrate`: seconds until the expression changes |

The internal ids are what the Arduino, the session log and `--round` use, and they never change; the UI and the console label the rounds 1 / 2 / 3. **Steady Hands** (accelerometer, id 2) and **Retreat** (ultrasonic, never built on the Pi) were cut in the pivot because they measure physical steadiness, not the face. The Steady Hands code is still in the repo and the sketch, and runs with `--legacy-rounds --round 2` (see [Legacy round: Steady Hands](#legacy-round-steady-hands)). There is no ultrasonic sensor to wire. Live Poker Face and Straight Face (`--round 5` or `--round 6`, not `--mock`, not `--calibrate`) score Presage; see [Presage](#presage-live-face-rounds). `--mock` and `--calibrate` stay on the OpenCV smile / frame-diff path and do not call Presage. ElevenLabs speaks the verdict; if it fails, the UI shows "verdict unavailable". The live webcam feed with the OpenCV overlay is in the browser UI (`--ui`), next to the leaderboard and the gap-over-rounds calibration curve.

## How it works

```
Rotary dial + button --> Arduino (UNO R4 WiFi or classic Uno) --JSON over USB serial (115200 baud)--> Raspberry Pi 4 (or a laptop)
                                                                     |- scoring.py        (gap and score)
                                                                     |- session_log.py    (data/sessions.db)
                                                                     |- elevenlabs_client.py (TTS; UI shows "verdict unavailable" if it fails) --> speaker
USB webcam (Rounds 2 and 3) -----------------------------------------> |- vision.py, poker_round.py, straight_round.py (OpenCV face box; smile / frame-diff for --mock and --calibrate)
                                                                     |- presage_client.py --> pi/presage/bridge.mjs (live --round 5 or 6 only; does not open a camera)
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

### Voice
`pi/elevenlabs_client.py` fills in a verdict line (picked by round and tier) with the numbers and sends it to `POST /v1/text-to-speech/{voice_id}` using `requests`. The whole call, including connecting, waiting for the first byte and downloading the audio, has a **3 s total budget** (`ELEVENLABS_TIMEOUT_S`). The verdict text is printed to the console every time, before the TTS call starts. There are no pre-recorded verdict mp3s, and a failed TTS call does not play a file from `assets/`. `pi/make_fallbacks.py` has been removed.

If there's no `ELEVENLABS_API_KEY`, the call runs out of time, returns an HTTP error or empty audio, or the mp3 can't be saved, nothing is played. With `--ui`, the reveal shows **verdict unavailable** and does not substitute another line. The key, voice and model come from `.env` (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`).

### Narrator
The narrator's voice is a **skeptical interviewer who is also your brutally honest friend**: dry, specific, unimpressed by claims, fair about the evidence. The verdict lines are in `pi/elevenlabs_client.py`: `TEMPLATES` (Reflex), `POKER_TEMPLATES` (Poker Face), `STRAIGHT_TEMPLATES` (Straight Face) and the legacy `STEADY_TEMPLATES`, one list per key (`validated`, `mild_over`, `mild_under`, `spicy_over`, ..., plus `false_start` and `timeout` for Reflex). "over" means the player claimed more than they delivered (press hardest), "under" means they sandbagged (needle them: why lowball?). To add a line, append a string to the right list. It can use `{player}`, `{claim}`, `{perf}` and `{gap}`, plus `{ms}` in Reflex, `{smile}` (percent of face frames with a smile) / `{secs}` (whole seconds to the first smile) when the unit is `smile_pct`, `{held}` / `{claimsecs}` (seconds held / seconds claimed) when the unit is `s`, or `{mg}` / `{peak}` in the legacy Steady Hands. A line that needs a reading the round doesn't have is skipped (for example `{secs}` when the player never smiled). A live face round's unit is `composure`, so lines that need `{smile}`, `{secs}`, `{held}` or `{claimsecs}` are skipped and one that only needs the claim, performance and gap is used. Keep it PG-13 at most, nothing about appearance or identity, and keep at least 4 lines per key. The narrator never picks the same line twice in a row for one player in a session.

**Word limit: 18 words** (`MAX_VERDICT_WORDS`), counted as whitespace-separated words after filling in a 10-character name and 3-digit numbers. Short lines are quick to synthesize inside the 3 s budget and quick to say. `pi/tests/test_narrator.py` checks every line against the limit, so a line that is too long fails the tests.

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

## Presage (live face rounds)

A real Poker Face or Straight Face round (`--round 5` or `--round 6`, with the webcam or `--video`, and **not** `--mock` or `--calibrate`) scores **Presage SmartSpectra neutral-expression confidence, 0-100**. Performance is that confidence, unchanged. `gap = |claim - performance|` on the same 0-100 scale (`score_composure_round` in `pi/scoring.py`). The logged `actual` is that number and `unit` is `composure`. The value is the mean of the samples the bridge actually returned for the window.

- Put `SMARTSPECTRA_API_KEY` in the repo-root `.env`. `PRESAGE_API_KEY` is also read. `pi/config.py` loads `.env` and the key only authorizes the on-device SDK. Without a key the process exits before the first claim (`SMARTSPECTRA_API_KEY is not set`).
- `pi/presage_client.py` pushes BGR frames from the webcam `vision.py` already opened into `pi/presage/bridge.mjs`. The bridge does **not** open a camera. Install its dependency once, on the machine that runs the Pi side: `cd pi/presage && npm install`. `PRESAGE_NODE` overrides the `node` binary if it is not `node` on `PATH`.
- OpenCV still finds the face and draws the face box (and the smile box when the smile cascade fires). A face in fewer than half the frames is still `no_face`: not scored, logged or spoken.
- A Presage error (bridge failed to start, timeout, SDK error, or a window with no sample) is not scored, logged or spoken, and no number is invented. The console says Presage did not return a composure reading.

`--mock` and `--calibrate` do not start the bridge. `--calibrate` is the legacy OpenCV smile and frame-diff printout. It does not tune Presage. The pre-demo check for a live face round is camera position: the whole face, chin included, centered in the frame. Presage reports that as a validation hint (`Move up` / `Move down`) and does not score a window with no composure sample.

## Round 2: Poker Face

Internal id **5** (`--round 5`). The player claims how good their poker face is going into a tough interview question (0 = cracks at anything, 100 = stone), then looks into the webcam and keeps a straight face for 6 s while one interview question plays ("Your references didn't call us back. Any idea why?"). A real round scores Presage neutral-expression confidence (see [Presage](#presage-live-face-rounds)). OpenCV still draws the face box. `--mock` and `--calibrate` do not call Presage; they score the Haar smile fraction below. The ElevenLabs call still only happens once, for the verdict.

### Setup
- Plug a USB webcam (ours is a Logitech) into the **Pi** (or the laptop standing in for it). Nothing changes on the Arduino wiring: dial on A0, button on D2.
- OpenCV comes with `pip install -r pi/requirements.txt`, which pins **`opencv-python>=4.8,<5`**. Keep that pin: **opencv-python 5.x removed `cv2.CascadeClassifier`**, the Haar cascade API this round uses. (On a headless Pi, `opencv-python-headless>=4.8,<5` works too, just without `--preview`.) Check with `python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'CascadeClassifier'))"`, which should print `4.x True`.
- OpenCV is imported only when a face round starts, so Reflex (and `--mock --round 5` / `--mock --round 6`) run without it. Choosing a face round without it stops with a clear message saying what to install.
- The cascades come from `cv2.data.haarcascades` (`haarcascade_frontalface_default.xml`, `haarcascade_smile.xml`). For OpenCV builds without `cv2.data` (such as apt's `python3-opencv`), set `DELULU_CASCADE_DIR`, for example `/usr/share/opencv4/haarcascades`.
- Camera index: `POKER_CAMERA_INDEX` in `pi/config.py` (default **0**, usually the built-in camera; `DELULU_CAMERA_INDEX` in `.env` overrides it), or per run with **`--camera N`**. An external USB webcam gets its own index: on our laptop the Logitech Brio 101 is **`--camera 2`** (`/dev/video2`) while the built-in camera stays at 0. On Linux, `ls /dev/video*` shows the candidates (a webcam often registers two nodes, and only the first one delivers frames). On macOS the first run asks to allow the terminal to use the camera.
- Optional: interview-question mp3s (see [Question clips](#question-clips)). If they are missing, the prompt is silent.

### Flow
1. Start the Pi with `--round 5`. It opens the camera (and keeps it open for the session), sends `R5`, and after the ack sends `W6000` (the window length) to the Arduino.
2. Turn the dial to your claimed poker-face confidence and press the button to **lock** it (same press check as Round 1).
3. Let go of the button. The Arduino prints the claim line and shows a **smiley** on the R4 WiFi matrix (the `L` LED lights on either board) for the window.
4. On that line the Pi starts a random interview question from `assets/questions/poker_XX.mp3` (non-blocking; no clips = silence; a machine that still has the pre-pivot `assets/jokes/` clips plays those until it regenerates) and watches your face for `POKER_WINDOW_S` (6 s). A clip still playing at the end of the window is stopped, so it never talks over the verdict.
5. The matrix goes dark (plus a short beep if a buzzer is connected), and the Pi scores, logs and narrates the result.

If no face was visible in at least half the frames, the result is a `no_face` error: like a Steady Hands sensor error it is **not scored, logged or spoken**, and the console tells the player to face the camera and press again. A webcam that delivers no frames gives a `camera_read` error, handled the same way. A Presage error is handled the same way: not scored, and no composure number is invented. Wait for the verdict before pressing again: a press during the verdict queues the next window.

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

### The OpenCV metric (what `--mock` and `--calibrate` score)
For every frame in the window (`pi/vision.py`). A live round still runs this detector for the face box and for `no_face`; it does not score `smile_frac`.
1. The frame is converted to grey and **downscaled** to 320 px wide (`VISION_DETECT_WIDTH`), and the frontal-face cascade finds the **largest face** (scaleFactor 1.1, minNeighbors 5, min size 10% of the width).
2. The smile cascade runs on the **lower half of that face**, cut from the full-resolution frame and resized to 160 px wide (`SMILE_ROI_WIDTH`) so the parameters behave the same at any distance: scaleFactor **1.7**, minNeighbors **20**, min size 20% x 10% of the face width (`SMILE_*` in `pi/config.py`, all configurable).
3. **Smoothing**: a face frame only counts as smiling if the detector saw a smile in at least **2 of the last 3** face frames (`SMILE_SMOOTH_HITS` / `SMILE_SMOOTH_FRAMES`). One-frame blips never count; a real smile counts from its second frame (and one frame after it ends, so a burst still counts at full length).

Per window: **`smile_frac` = smiling face frames / face frames** (the `--mock` / `--calibrate` score), `face_frac` = face frames / all frames, `frames`, `fps`, and `first_smile_ms` (ms from the window start to the first smoothed smile, or `null`). On an x86 dev box the detector takes about 7-17 ms a frame at 640x480; the Pi 4 is several times slower, which is why frames are downscaled first. `--calibrate` prints the fps, so check it on the Pi, and if it drops under ~10 lower `VISION_DETECT_WIDTH`.

### Scoring
A real round (`--round 5`, not `--mock`, not `--calibrate`) scores Presage neutral-expression confidence directly: performance is that 0-100 number, `unit` is `composure` (see [Presage](#presage-live-face-rounds)). Then `gap = |claim - performance|`, `score = round(100 - gap)`, with the same tiers. No false starts or timeouts. The verdict lines are `POKER_TEMPLATES`.

`--mock` and `--calibrate` do not call Presage. They map smile_frac to performance (0-100), linear and clamped: **`POKER_BEST_FRAC` (0.03) or less = 100, `POKER_WORST_FRAC` (0.40) or more = 0**. The row then uses `actual` = smile_frac x 100, `unit` = `smile_pct`, and `smile_frac`, `face_frac`, `frames`, `fps` and `first_smile_ms` in `extra`.

### Calibrate on the hardware
**0.03 and 0.40 are starting guesses, to be calibrated on the real camera.** The smile cascade has a false-positive floor that depends on the camera, the light and the face.

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --calibrate            # add --preview to see the boxes, --camera 2 for an external webcam
```

Each window prints `smile_frac`, `face_frac`, `fps` (and frame count) and `first_smile_ms`, plus the running min, median and max of smile_frac. Nothing is scored, logged or spoken, and Presage is not called (the question still plays; `--no-audio` turns it off). Do a few honest stone-face windows and a few where you let yourself laugh. Then set `POKER_BEST_FRAC` just above the stone-face windows and `POKER_WORST_FRAC` around a clear laugh in `pi/config.py`. Plain `--calibrate` (no `--round`) means Poker Face now. `--video clip.mp4` calibrates against a saved clip instead (see [Testing against a saved clip](#testing-the-face-rounds-against-a-saved-clip---video)). If faces are often missed (`face_frac` low in good light), sit closer or lower `FACE_MIN_SIZE_FRAC`. If you get smiles on straight faces, raise `SMILE_MIN_NEIGHBORS`; if real smiles are missed, lower it.

### --preview
`--preview` opens an OpenCV window during each window showing the camera with the **face box (green)**, the **smile box (yellow)**, `SMILE!` when a smoothed smile counts, and the time left. It is off by default, only draws on screen (nothing is saved), and closes after each window. Without a display (for example a Pi over SSH) or with `opencv-python-headless`, it prints one warning and turns itself off. The round still runs.

### Live camera in the browser (`--ui`)
With the browser UI on (`python pi/main.py --port /dev/ttyACM0 --round 5 --camera 2 --ui`), the face-round screen shows the webcam next to the dial, mirrored like a selfie. OpenCV draws the face box (green) and, when the smile cascade fires, the smile box (yellow). On a real face round the browser readout is Presage composure, 0-100, the number the round scores. `--mock` and `--calibrate` do not run Presage, so that readout is absent and the OpenCV smile % or the Straight Face seconds are what those modes score. The stream is MJPEG at `GET /api/camera.mjpg`. The slow part (`available`, `mode`, `kind`) is in the state snapshot under `camera`; the fast numbers (`face`, `smiling`, `smilePct`, `composure` when Presage has a sample, and for Straight Face `phase`, `heldS`, `changedAtS`, `trigger`, `level`) are pushed as small `event: live` SSE messages at most 4 times a second (and are in `GET /api/state` for polling clients), so the history and leaderboard are never re-sent for them.

- **No second camera handle.** The stream shows the frames the round already reads (`pi/camera_feed.py`). The measurement loop only drops each frame into a single latest-frame slot, which is O(1) and never waits. Each browser's HTTP thread picks up the newest frame at most `UI_CAMERA_FPS` (12) times a second, scales it to `UI_CAMERA_MAX_WIDTH` (640), draws the overlay and encodes a JPEG (quality `UI_CAMERA_JPEG_QUALITY`, 70). Nothing is encoded while nobody watches, and a stream error only ends that browser's stream, never the round.
- **While the claim is being set** (on by default), the stream also shows a preview: raw detector output, marked PREVIEW and not scored, so the player can frame their face before locking. It reads the already-open camera at `UI_CAMERA_IDLE_FPS` (10), but only while a browser is actually watching, and it stops before every measured window (the window always gets the camera first). Set `DELULU_CAMERA_PREVIEW=0` in `.env` to show frames only during the window.
- When the camera isn't being read, the stream shows a "camera paused" placeholder. Without a camera feed (other rounds, `--mock`), the endpoint returns 503 and the UI shows a placeholder instead.
- `--preview` (the OpenCV window) works alongside the stream.

### Question clips
The face rounds' stimulus is interview questions. The lines are in `pi/elevenlabs_client.py`: `POKER_QUESTION_LINES` and `PRESSURE_QUESTION_LINES`. Spoken clips under `assets/questions/` are optional. Poker Face plays one `poker_XX.mp3` per window (never the same file twice in a row). Straight Face plays `pressure_XX.mp3`, shuffled, back to back until the face changes. If those files are missing, the prompt is silent and the round still runs. `--no-audio` skips them too. If there is no `poker_XX.mp3`, an older machine's `assets/jokes/` mp3s are still used for Poker Face.

### Privacy
Frames are processed **in memory only**, one at a time, and are **not saved to disk**. The OpenCV vision path has no image-writing or network calls of its own, and a test checks for that. On a live face round the same frames are piped to `pi/presage/bridge.mjs`, which does not open a camera; the SmartSpectra key only authorizes the on-device SDK. Only numbers are logged (for a live round, composure; the OpenCV readings can still be in `extra`: smile_frac, face_frac, frame count, fps, first_smile_ms, and for Straight Face the seconds held, the trigger and the difference scores). Straight Face keeps its neutral-face reference as a 48 x 48 grey crop in memory for one window and drops it afterwards. `--preview` only draws on the local screen. With `--ui`, the newest frame is also held in memory (one at a time, dropped when the window ends) to stream to the browser on this machine (`/api/camera.mjpg`, served on `--ui-host`, which is localhost by default). It is never saved.

## Round 3: Straight Face Under Pressure

Internal id **6** (`--round 6`). The player sets the dial while rapid-fire interview questions play (the UI shows dial 0-100 as 0-`STRAIGHT_MAX_S` seconds, **20 s** by default, so 50 = 10 s). A real round does **not** score those seconds. It scores Presage neutral-expression confidence, 0-100, against the dial's 0-100 (see [Presage](#presage-live-face-rounds)). OpenCV still draws the face box and still ends the window when the expression changes. `--mock` and `--calibrate` do not call Presage; they score the seconds held, below.

### Flow
1. Start with `--round 6`. The Pi opens the camera, sends `R6`, and after the ack `W20000` (the longest the cue can run).
2. Set the dial, press to **lock**, let go. The Arduino prints `{"type":"claim","round_id":6,...}` and shows a **straight face** on the R4 WiFi matrix (`L` LED on either board).
3. The Pi starts the rapid-fire questions (`assets/questions/pressure_XX.mp3`, shuffled, back to back) and watches your face.
4. The moment your expression changes, the questions stop, the Pi sends `S` so the Arduino ends its cue early, the browser overlay shows the change marker, and the Pi scores, logs and narrates. If nothing changes, the window ends at `STRAIGHT_MAX_S` and you held the whole time.

`no_face` (no neutral baseline within 4 s, or a face in fewer than half the frames), `camera_read` and `presage` errors are handled exactly like Poker Face: not scored, logged or spoken, and a Presage failure does not invent a number.

### The OpenCV metric (frame differencing; what `--mock` and `--calibrate` score)
For every face frame (`pi/vision.py`, `FaceSignature` + `ExpressionTracker` + `measure_straight_face`):
1. The face box (from the same Haar face detector, smoothed over frames so its jitter doesn't read as movement) is cut from the grey frame, resized to **48 x 48** (`STRAIGHT_SIG_SIZE`, which normalizes by face size and distance), lightly blurred, and its mean brightness subtracted (so auto-exposure drift doesn't count).
2. **Baseline:** the first `STRAIGHT_BASELINE_S` (1 s, at least 5 face frames) are averaged into your neutral face. Their own distances to it give the noise level.
3. **Difference:** each later frame's mean absolute difference from the neutral face, over the whole face and over the mouth region (the rows below `STRAIGHT_MOUTH_FROM` = 55%), whichever is larger, in grey levels.
4. **Change:** `STRAIGHT_HOLD_FRAMES` (3) frames in a row above `max(STRAIGHT_MIN_DIFF, baseline mean + STRAIGHT_K x baseline std)` = `max(9, mean + 4 std)`. The time of the first of those frames is the change. A smoothed Haar smile (2 of the last 3 frames) also counts (`STRAIGHT_SMILE_BREAKS`).

`held` = seconds from the start of the window to the change (or 20 if none). On `--mock` and `--calibrate`, scoring is `performance = held / STRAIGHT_MAX_S x 100`, `gap = |claim - performance|`, with `actual` = seconds held, `unit` = `s`, and `held_s`, `max_s`, `claim_s`, `broke`, `trigger`, `face_frac`, `frames`, `fps` in `extra`. A real round keeps that OpenCV timing (the questions stop and the Arduino cue ends early) but replaces the scored `actual` with Presage composure and sets `unit` to `composure`. Verdicts come from `STRAIGHT_TEMPLATES`. There is no `fallback_round6_*.mp3`.

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

A clip runs on its **own clock** (frames / fps), so a 6 s window always covers 6 s of video however fast the machine decodes it, and the same clip gives the same numbers every run. `main.py` rewinds at the end of the clip; `vision.py --no-loop` stops there instead. `pi/tests/test_straight_round.py` generates a tiny synthetic clip (a drawn face whose mouth opens at 2.0 s) and checks the change is found at 2.0 s. `vision.py` and the `--mock` / `--calibrate` commands above stay on the OpenCV metric. A face round that is not `--mock` and not `--calibrate` scores Presage even when the frames come from `--video`, and it needs `SMARTSPECTRA_API_KEY`.

## Session log schema
`data/sessions.db` has one row per round. Schema v2 (this version) adds `actual` (the raw metric), `unit` (`ms`, live face-round `composure`, mock Poker Face `smile_pct`, mock Straight Face `s`, or the legacy `mg_rms`) and `extra` (JSON, for example Poker Face (5) `smile_frac`, `face_frac`, `frames`, `fps`, `first_smile_ms`, Straight Face (6) `held_s`, `max_s`, `claim_s`, `broke`, `trigger`, or legacy Steady Hands (2) `peak` and `samples`). A live face round stores Presage's confidence in `actual` with `unit` `composure`. `actual_ms` stays and is still filled for Round 1, so older queries keep working. An existing v1 file is upgraded in place the first time it's opened. The upgrade only adds columns (nothing is dropped or rewritten), copies `actual_ms` into `actual` with unit `ms` for the old rows, and runs in one transaction. Before that, a one-off copy of the old file is saved as `data/sessions.pre-v2-backup.db` (gitignored like the rest of `data/*.db`).

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
sudo apt install -y python3-venv mpg123          # mpg123 plays the mp3 verdicts (and optional question clips)
cd delulu-detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r pi/requirements.txt                # includes opencv-python>=4.8,<5 for the face rounds (keep it below 5)
cd pi/presage && npm install && cd ../..          # SmartSpectra bridge for live --round 5 or 6 (Node; does not open a camera)
cp .env.example .env                             # then set ELEVENLABS_API_KEY and SMARTSPECTRA_API_KEY
sudo usermod -aG dialout $USER                   # serial port access (log out and back in)
```
The code reads `ELEVENLABS_API_KEY` and `SMARTSPECTRA_API_KEY` from the environment or from `.env` (`PRESAGE_API_KEY` is accepted for Presage). Never commit `.env`. Live face rounds need the Presage key and the bridge install above. `--mock`, `--calibrate` and Reflex do not. Interview questions are spoken live by ElevenLabs when the window starts. If that call fails, the screen says "question unavailable" and no file is played.

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

Other flags: `--round {1,5,6}` (default 1), `--calibrate` (OpenCV raw values only, no Presage: Poker Face smile_frac by default, or `--round 6`), `--camera N`, `--video PATH` and `--preview` (face rounds), `--legacy-rounds` (allows the cut `--round 2`), `--baud`, `--db PATH`, `--no-audio` (also skips the question clips), `--ui` (live browser UI, see below). Real `--round 5` or `--round 6` (not `--mock`, not `--calibrate`) need `SMARTSPECTRA_API_KEY` and `pi/presage/bridge.mjs`.

### Run without hardware
```bash
python pi/main.py --mock --player Tester --rounds 4 --seed 1
```
`--mock` sends the Pi JSON lines in the same format the Arduino would print. The simulated player starts overconfident and recalibrates, with the odd false start. `--mock --round 5` simulates Poker Face windows with a fake camera and detector (no webcam, no OpenCV, no Presage, instant windows): straight faces with the odd one-frame blip, smile bursts, and now and then a player who looks away (`no_face`, reported and not scored). `--mock --round 6` does the same for Straight Face (a neutral face that changes at a random moment, sometimes held to the end) and scores the OpenCV seconds, not Presage. `--mock --calibrate` (with or without `--round 6`) exercises the calibration printout, and `--mock --video clip.mp4` swaps the fake camera for a real clip while staying on the OpenCV metric. `--mock --legacy-rounds --round 2` still simulates Steady Hands. If `ELEVENLABS_API_KEY` isn't set, nothing is played; with `--ui` the reveal shows "verdict unavailable". Add `--no-audio` for silent runs and `--mock-delay 0` for fast ones.

### Live browser UI
`--ui` shows the game in a browser while you play: idle screen, the round in progress, the claim moving live as the knob turns (with the current sketch), the locked claim while the round runs, the reveal (claim, reality, gap, tier, the narrator's line, the raw measurement) and the leaderboard and calibration curve from `data/sessions.db`.

```bash
# once per machine (needs Node 20.19+): build the frontend so Python can serve it
cd frontend && npm install && npm run build && cd ..

python pi/main.py --port /dev/ttyACM0 --player Saim --ui     # then open http://localhost:8765
python pi/main.py --mock --player Tester --ui                # simulated rounds (and knob turns); stays up until Ctrl+C
```
`pi/ui_server.py` (stdlib only) runs in a background thread: `GET /api/state` is the current state as JSON, `GET /api/events` pushes it on every change (Server-Sent Events; while the knob turns only a small `event: dial` with `{"liveClaim": N}` is pushed, not the whole state with history), and `/` serves `frontend/dist`, so the venue needs no Node. A UI problem is reported once and never stops a round; if the port is taken the game runs without the UI. Flags: `--ui-port` (default 8765), `--ui-host` (default 127.0.0.1; `0.0.0.0` to open it from another device on the network). Timings (how long the reveal stays up, when it falls back to the idle screen) are `UI_*` in `pi/config.py`.

To work on the frontend with no Arduino and no camera, `cd frontend && npm run dev:preview` and open the Vite URL. The pages walk idle, dial, measuring, and reveal on their own. Keys `1` `2` `3` `4` pin one of those screens, and `0` resumes the walk. `?preview=1` on a built page does the same thing. That mode never talks to the game. For a real round, run the Python side with `--ui` and `cd frontend && npm run dev`; Vite proxies `/api` to port 8765 (`DELULU_API=http://host:port npm run dev` for another address).

## Tests
```bash
source .venv/bin/activate
python -m pytest pi/tests -q
```
The tests cover the ms-to-performance and mg-to-performance mappings (bounds, linearity, clamping), gap, score, tiers, false start and timeout handling (including the claim-0 case), the SQLite log (fields, per-player round numbering, leaderboard and calibration series across rounds, the schema v2 migration of old `sessions.db` files), serial line parsing for both rounds, the round selection line and its ack/resend logic (with a fake serial port), `--mock` and `--calibrate` for Round 2, verdict text for every tier of every round (word limit, at least 4 lines per key, no back-to-back repeats), the TTS time budget and that a timeout, HTTP error, empty audio or missing key plays nothing and does not read a fallback mp3 (with a faked network), Presage (a missing key, an SDK error, an average of only the samples the bridge returned, and no invented composure) and the main loop surviving a failed round. For Straight Face: the seconds mapping, the tracker (baseline, threshold, hold frames), whole windows on scripted frames (expression change, smile, no face, dead camera), the question barrage, the `R6` / `W20000` / `S` serial lines, `--mock` / `--calibrate --round 6`, the UI state and overlay, and `--video` on a generated clip. For Poker Face: the smile_frac mapping, scoring, the claim line, the `W` window line, the 2-of-3 smoothing, a fake camera and detector driving whole rounds (expected smile_frac and first_smile_ms, `no_face`, a dead camera, the question clip started and stopped), `--mock` and `--calibrate --round 5`, that nothing in the vision code writes or sends frames, and that Rounds 1 and 2 still produce byte-identical mock output. They need no camera and no OpenCV: `pi/tests/test_vision_cv2.py` (real cascades loading, synthetic frames, a fake `VideoCapture`) is skipped when `cv2` isn't installed. They never call ElevenLabs.

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
│   ├── elevenlabs_client.py        # verdict lines, TTS with a 3 s budget (no fallback mp3s)
│   ├── presage_client.py           # live face rounds: frames in, Presage composure 0-100 out
│   ├── presage/bridge.mjs          # SmartSpectra bridge; does not open a camera (npm install here)
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
└── assets/
    └── questions/                  # optional interview-question mp3s; missing files mean a silent prompt
```

## License
MIT © 2026 Saim Hashmi
