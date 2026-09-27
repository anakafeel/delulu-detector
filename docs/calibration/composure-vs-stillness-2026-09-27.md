# Does "composure" reward a blank, checked-out face? (2026-09-27)

Status: **signal identified from the SDK schema; the hardware trials below have not been run yet.**
No scoring change was made. Nothing here should be pitched as settled until the table at the
bottom is filled in.

## What the number actually is

- `pi/presage/bridge.mjs` requests `faceMetrics` from `@smartspectra/node-sdk` 3.3.0 and, for each
  `metrics` event, takes `face.expression[last].scores[]` and keeps the entry with
  `type == NEUTRAL (6)`. Its `confidence` (0-100) is the sample. `presage_client.py` averages the
  samples in the window; `scoring.score_composure_round` uses that mean unchanged as performance.
- Per the SDK's own schema (`js/messages/generated.d.ts`): `Expression.scores` is the "confidence
  distribution across all expression types", from an 8-class facial-expression model
  (`ANGRY, CONTEMPT, DISGUST, FEAR, HAPPY, NEUTRAL, SAD, SURPRISE`), "used for facial expression
  analysis and emotion detection". `ExpressionScore.confidence` is a percentage.
- So "composure" = **how confidently the model classifies the face's appearance as the NEUTRAL
  expression class**, averaged over the window.

What that means for the concern:

- It is **not** a movement-magnitude or expression-change-frequency measure. It is a per-sample
  classification of what the face looks like. A frozen, perfectly still smile should score low
  (HAPPY, not NEUTRAL); stillness by itself is not what it rewards. (To be confirmed: trial C.)
- It **is** blind to internal state. A deliberately blank, checked-out face is the textbook
  NEUTRAL class, so it should score high. A calm person who is naturally expressive while
  engaged (small smiles, raised brows) moves probability into HAPPY / SURPRISE and scores lower.
  By construction it cannot tell "calm and engaged" from "blank and disengaged".
- Whether that is a bug depends on the claim it is scored against:
  - Poker Face's claim is "how unreadable is your face" (the dial prompt; `roundDefs.js`:
    "Claimed poker face going into a tough interview question"). For that claim, neutral-expression
    confidence is the right quantity: an unreadable face *is* a neutral-looking one.
  - The word **"composure"** (UI labels, `docs/devpost.md`: "how composed they expect to look")
    implies calm inside. That overclaims. The number is expression neutrality, not calm.

## Is there a better signal in the SDK?

Everything the SDK can return (3.3.0 schema): face (blinking, talking, landmarks, the expression
distribution), breathing (rate, traces, amplitude, apnea, inhale/exhale ratio, ...), cardio
(pulse rate, arterial pressure trace, HRV: `rmssd`, `meanNn`, `sdnn`, **`baevsky`** = Baevsky's
Stress Index), EDA trace, micromotion (glutes, knees).

- There is no field called composure, stress, valence or arousal in the face bundle.
- The only stress-type signal is **Baevsky's Stress Index**, derived from heart-rate variability.
  HRV needs a long run of clean beat-to-beat intervals (ultra-short HRV is usually quoted at
  30-60 s minimum, standard at minutes). The Poker Face window is 6 s, so it cannot produce a
  meaningful value for one round, and it is a different metric from facial neutrality anyway.
  Not a drop-in replacement; not switched to.

## The test that has to run before this ships (real hardware, ~5 minutes)

Setup: the normal rig (`./start.sh`), same person, same seat, same lighting, same question pool,
fresh `data/sessions.db` (move the old one aside first). Dial the same claim (e.g. 50) every time
so only composure varies. Two rounds of each trial, in the order A B C A B C, to average out
question and fatigue effects.

| Trial | What the player does for the whole 6 s window | Tests |
| --- | --- | --- |
| A. Blank | Consciously checked out: slack neutral face, eyes unfocused, no reaction to the question | the concern |
| B. Calm, engaged | Genuinely relaxed and listening, reacting naturally (small smile, brows, nods), answering in their head | the concern |
| C. Still smile | Holds one small smile, head completely still | stillness vs. neutrality |

Read each round's composure from the reveal (or `sessions.db`, column `actual`), and the new
`presage_samples` in `extra` (rounds with very few samples are unreliable; note them).

How to read the result:

- **A clearly above B** (mean difference well beyond the spread between the two repeats of the
  same trial, roughly 15+ points): confirmed. The number rewards a blank face over a calm engaged
  one. Expected, given what the signal is.
- **C low** (well below A): it is reading expression, not stillness. **C high**: it is tracking
  stillness, which would contradict the schema and is a real bug to chase in the bridge.
- A approximately B: the concern doesn't show up in practice at this window length; say so.

Results (fill in):

| Round | Trial | Claim | Composure | presage_samples |
| --- | --- | --- | --- | --- |
| 1 | A |  |  |  |
| 2 | B |  |  |  |
| 3 | C |  |  |  |
| 4 | A |  |  |  |
| 5 | B |  |  |  |
| 6 | C |  |  |  |

## If A beats B (the expected outcome)

The SDK has no signal that separates calm from blank in 6 s, so the honest response is the
wording, not a new formula: call the number what it is (expression neutrality, "how neutral your
face looked") wherever it is labelled composure, and say it plainly if a judge asks. That is a
framing change, not a scoring change, and it does not affect the per-player baseline question
below.

## Separate problem: resting faces differ

Some people's resting face reads as less NEUTRAL (a natural smile, heavy brows). A per-player
baseline would correct for that offset. It is a different bug: a baseline subtracts each
person's resting level, but a blank face would still beat an engaged one after the subtraction.
Neither fix substitutes for the other.
