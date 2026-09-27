# Hill's Kitchen — 5-minute judging script

Hack the Hill III. Say the lines. Do the actions in brackets. Read only what the screen shows. Do not invent a score, play stand-in audio, or open a fake board.

## 0:00 — The claim (about 45 seconds)

This demonstrates that your face gives off signals you don't control and can't accurately predict. We are showing that live.

It is not interview training. It is not a clinical stress test. It does not help anyone land a job. This does not measure whether someone would pass an interview. It does not diagnose stress, anxiety, or health. One round will not make anyone more composed.

The claim we will defend is the one in front of you. You say how composed you expect to look. We measure your face. You do not edit that reading, and if the reading does not come back, we do not replace it.

## 0:45 — Live demo (about 2 minutes)

[One person. Hand them the dial. Keep the browser on the live view.]

Set the dial from 0 to 100 for how composed you expect to look. Zero means you expect your face to give you away. One hundred means you expect to look completely composed. Press the button to lock that number.

[Wait for the lock. Start one webcam round: Poker Face or Straight Face. Do not start with reflexes.]

Look at the webcam and hold still. Poker Face is the short hold. Straight Face runs until your face changes or the window ends. We run one of those, not both.

[Point at the screen while the round runs.]

The box on the face is OpenCV. It only shows that a face is in frame. It does not score the round.

The reality check is Presage SmartSpectra, an on-device vitals and expression SDK. The API key only authorizes the session. Frames are not uploaded for scoring. The only photo is opt-in: press Y after your name, and one frame from mid-question sits in memory on this laptop for the leaderboard until the game stops.

ElevenLabs speaks only after both measurements are back: the locked dial claim, and the Presage reading. The voice does not invent a score.

[Read the claim, the result, and the gap off the screen. The gap is the absolute difference between the claim and the performance. The score is 100 minus that gap. If a number is not on the screen, do not say one.]

If Presage does not return a result, the screen says the result is unavailable. If ElevenLabs does not return audio, the screen says the verdict is unavailable. There is no canned audio and no mock leaderboard. A failure stays a failure.

## 2:45 — How it works (about 50 seconds)

A rotary dial and a button are on an Arduino. The board sends the locked claim. It does not score the face.

A USB webcam is on the computer that runs the Python loop. That loop waits for the claim and the Presage reading, then asks ElevenLabs to speak. The browser shows the face box, then the comparison or an unavailable state. Nothing recorded earlier plays in its place.

A reflex round is in the software: lock a claim, wait for a cue, press the button. That is a backup only. It does not measure the face, and it is not this demo.

## 3:35 — Decisions (about 70 seconds)

We cut the accelerometer round and the ultrasonic round. The accelerometer measured hand tremor. The ultrasonic round would have measured distance, how far a person moved. Neither is a signal on the face, so neither tests the claim you just heard. They are not in the live demo. The ultrasonic round was never in that loop.

We do not score a smile percentage. Counting frames that look like a smile, or scoring raw frame-to-frame change, follows pixels, light, and camera distance. Measurement is Presage, on the device, not that heuristic. OpenCV draws the face box and stops there.

ElevenLabs is only the verdict. It does not see the frames, it does not compute the gap, and it is not a backup measurement. If it fails, the verdict stays unavailable. We would rather show that than play an old clip and pretend this round just spoke.

## 4:45 — Close (about 15 seconds)

One person. One claim about their own face. One live check against a signal they do not control. If the services answered, you heard a verdict of those two measurements. If they did not, the screen said unavailable. That is the project. Thank you.
