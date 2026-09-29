# What the Hill

<p align="center">
  <img src="frontend/src/assets/logo.png" width="220" alt="What the Hill logo: an orange fox in a green shirt and tie, scuba tank on his back, holding a finger to his lips underwater">
</p>

Hack the Hill III booth game. You put a number on your poker face. A camera checks it while you answer one hard interview question.

Turn a dial from 0 to 100 for how unreadable you think you will look. A webcam and [Presage](https://presagetech.com/) watch your face. [ElevenLabs](https://elevenlabs.io) asks the question, then says how far off you were. The screen shows the same numbers.

[whatthehill.wiki](http://whatthehill.wiki) · [github.com/anakafeel/what-the-hill](https://github.com/anakafeel/what-the-hill)

https://github.com/user-attachments/assets/0c7d0bfa-c6e2-439c-b1c3-08c3ee1eee85

anakafeel's Poker Face round: claim 68, composure 0, gap 68. About 20 seconds. The clip is in the repo at [`brag-output/brag.mp4`](brag-output/brag.mp4).

> We are not claiming this lands you the interview. Your face leaks signals you don't control and can't predict. Seeing that live is funny and a little uncomfortable.

## What you do

Poker Face at the booth:

- **Predict.** Type a name (up to 16 characters). Y keeps a leaderboard photo. N or Enter skips it. Turn the dial, 0 to 100. Press the button to lock the number. Lock it before you type a name and that turn does not count.
- **Perform.** The camera starts after the lock. ElevenLabs asks one interview question, out loud and on screen. You answer on camera. Presage reads your face while the question is up.
- **Reveal.** You get claim, composure, gap, and score. The narrator says the verdict. The leaderboard keeps best gap, worst gap, rounds played, and average score.

Press ? on the booth for the same math in plain language.

Three rounds:

- **Reflex.** Backup when you cannot use the camera. No face reading. It times the button after a cue.
- **Poker Face.** The demo. One question, about 6 seconds. Your claim against how neutral the face looked.
- **Straight Face Under Pressure.** Same face reading. Hold it while questions come fast, up to 20 seconds.

## What the number means

**Composure** is how neutral the face looked, 0 to 100, averaged while the question is on screen.

**Gap** is the absolute difference between the claim and that number. A bigger gap means you were more wrong about your own face.

**Score** is 100 minus the gap.

| Gap | Tier |
| --- | --- |
| 0 to 10 | validated |
| up to 25 | mild |
| up to 45 | spicy |
| above that | delulu |

If the camera or Presage returns nothing, that round is skipped. If the voice fails, the screen says so.

- No stress, honesty, interview skill, or heart rate.
- Not a lie detector, a coach, a clinical tool, or a way to identify someone.
- A blank face and a calm face can both look neutral.

## Try it

You need Python, Node 20.19+ (or 22.12+), and a browser. The first run needs no Arduino and no Presage key.

On Debian or Ubuntu, if `venv` or `mpg123` is missing:

```bash
sudo apt install -y python3-venv mpg123
```

```bash
git clone https://github.com/anakafeel/what-the-hill
cd what-the-hill
python3 -m venv .venv
source .venv/bin/activate
pip install -r pi/requirements.txt
cd frontend && npm install && npm run build && cd ..
cp .env.example .env
```

Keep `opencv-python` below version 5. OpenCV 5 removed the face detector this project uses. Python serves the page you just built. `mpg123` plays the voice.

### No hardware

```bash
python pi/main.py --mock --round 5 --player Tester --ui
```

Open http://127.0.0.1:8765. `--mock` fakes the dial and the camera. It does not call Presage, so no Presage key is needed. Add `--no-audio` if you want it quiet.

### Full booth

Live face rounds also need Presage installed, and the Arduino in [Hardware](#hardware):

```bash
cd pi/presage && npm install && cd ../..
```

Put the keys in `.env`:

- `ELEVENLABS_API_KEY` speaks the question and the verdict.
- `SMARTSPECTRA_API_KEY` (or `PRESAGE_API_KEY`) is required for live Poker Face and Straight Face. Without it, those rounds exit before the first claim.
- `TIGER_DATA_URL` is optional. If it is set, scored rounds are copied there too. SQLite at `data/sessions.db` is the log the game uses.

Anything else you might override is in `.env.example`.

Serial port access (log out and back in afterward):

```bash
sudo usermod -aG dialout $USER
```

Then, with the board on `/dev/ttyACM0`:

```bash
python pi/main.py --port /dev/ttyACM0 --round 5 --camera 2 --ui
```

Same URL. Camera index 2 is the booth laptop's Logitech. Other machines often use `0`. Players type their names on screen, so leave `--player` off for this one.

## Hardware

Sketch: `arduino/delulu_gauntlet/delulu_gauntlet.ino` (the folder name matches the sketch, which is what the Arduino IDE requires). UNO R4 WiFi or a classic Uno. Install the Grove LCD library before you compile. The LCD itself is optional.

```bash
arduino-cli core install arduino:renesas_uno
arduino-cli lib install "Grove - LCD RGB Backlight"
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi arduino/delulu_gauntlet
arduino-cli upload --fqbn arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 arduino/delulu_gauntlet
```

Classic Uno: install `arduino:avr` and pass `--fqbn arduino:avr:uno` instead. Stop the game before you upload. The game holds the port.

Arduino IDE: install the board core and the Grove LCD library, open the sketch, pick the board and port, Upload.

| Part | Where |
| --- | --- |
| Dial | A0 |
| Button | D2 |
| Grove LCD (optional) | I2C |
| Buzzer (optional) | D6 |
| Webcam | USB on the computer, not the Arduino |

Grove buttons use the default in the sketch (pressed means high). A button wired to ground needs `BUTTON_ACTIVE_LOW` set to `1` at the top of the sketch. The wrong setting locks the dial on its own.

## Run

From the repo root, venv active. `--round 1` is Reflex, `--round 5` is Poker Face, `--round 6` is Straight Face Under Pressure.

```bash
python pi/main.py --mock --round 5 --player Tester --ui
python pi/main.py --port /dev/ttyACM0 --round 5 --camera 2 --ui
python pi/main.py --port /dev/ttyACM0 --round 6 --camera 2 --player Tester --ui
python pi/main.py --port /dev/ttyACM0 --round 1 --player Tester --ui
```

Poker Face with `--ui` asks for the name. Reflex and Straight Face use `--player`.

| Flag | What it does |
| --- | --- |
| `--ui` | Serve the page at http://127.0.0.1:8765 |
| `--round` | `1` Reflex, `5` Poker Face, `6` Straight Face |
| `--camera` | Webcam index. Booth Logitech is `2`. Other machines often use `0` |
| `--port` | Arduino serial port, often `/dev/ttyACM0` |
| `--mock` | Fake dial and camera. Does not call Presage |
| `--no-audio` | Do not play the voice |
| `--player` | Name written to the log when the screen is not asking |

Changing the page, from `frontend/`:

- `npm run dev:preview` walks the screens. No Arduino, no camera.
- `npm run dev` uses a game already running with `--ui`.
- `npm run build` writes the files Python serves.

## Privacy

- Frames stay in memory and are not saved.
- Presage runs on this machine. The key only authorizes it.
- The log stores numbers, not faces.
- The browser preview stays on this machine.
- The leaderboard photo is opt-in: one frame, memory only, gone when the game stops.

## License

MIT © 2026 Saim Hashmi
