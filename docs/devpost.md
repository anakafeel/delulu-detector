# Hill's Kitchen

Hack the Hill III. Paste the sections below into the Devpost text fields.

## What it is

Hill's Kitchen demonstrates that your face gives off signals you do not control and cannot accurately predict, and it does that live.

One person sets a rotary dial from 0 to 100 for how composed they expect to look, then presses a button to lock the claim. They do one webcam round: Poker Face or Straight Face. Presage SmartSpectra, an on-device vitals and expression SDK, is the reality check. The API key only authorizes the session. Frames are not uploaded for scoring. OpenCV only draws the face box. The locked claim and the Presage reading are compared as a gap, the absolute difference between claim and performance. The score is 100 minus that gap. ElevenLabs speaks the verdict only after both measurements return.

If Presage fails, the screen says the result is unavailable. If ElevenLabs fails, the screen says the verdict is unavailable. There is no canned audio and no mock leaderboard.

A reflex round exists only as a backup if a face round cannot be run. It is not the demonstration.

## The honest limit

This is not interview training. It is not a clinical stress test, and it is not a medical device. It does not diagnose stress, anxiety, or any health condition. It does not measure whether someone would get a job, and it does not help anyone land a job. A session is one self-report compared with one face measurement. It is not a coach, a treatment, or a hiring tool.

## Why measurement is Presage SmartSpectra

A smile-percentage heuristic counts frames where a detector thinks it sees a smile, or it scores raw change between frames. That number moves with lighting, distance, and pixel noise. It is not the measurement used here.

Presage SmartSpectra runs on the computer as an on-device vitals and expression SDK. The API key only authorizes the session. Frames are not uploaded for scoring. A player can opt in (press Y after typing their name) to one leaderboard photo from mid-question; it stays in memory on the booth laptop and is gone when the game stops. OpenCV’s only job on screen is to draw the face box so the person can see they are in frame.

## Why ElevenLabs is only the verdict

ElevenLabs does not measure the face and does not compute the score. It speaks after the dial claim and the Presage reading have both returned. If that call fails, the screen says the verdict is unavailable. There is no pre-recorded substitute. Speech cannot cover a missing result.

## Why the accelerometer and ultrasonic sensors were cut

The accelerometer round measured hand tremor. The ultrasonic round would have measured distance. Both are body movement, not a facial signal, so they do not test the claim. They were cut from the live demonstration. The ultrasonic round was never in the live loop.

## Hardware

A rotary dial and a button are on an Arduino. A USB webcam is on the computer running the Python loop. A browser UI shows the round.

## Source

The repository is public under the MIT license: https://github.com/anakafeel/delulu-detector

The project is Hill's Kitchen. The repository name is unchanged.
