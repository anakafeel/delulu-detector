// Static metadata for each round. Matched to the PRD's round table.
// `number` is the round type id the Pi uses (pi/main.py --round N, the Arduino's
// "round_id"); `round_id` is the string id used everywhere in this app.
// actual_unit is appended straight after the raw value on the reveal
// ("287ms", "68.2 mg RMS", "12.5% smiling"), so it carries its own spacing.
// Real units, from the Pi backend:
//   Reflex        reaction time in ms (150 ms or faster = 100, 600 ms or slower = 0)
//   Steady Hands  tremor as mg RMS over a 5 s hold (35 mg or less = 100, 500 mg or more = 0)
//   Poker Face    % of face frames with a smile over a 6 s webcam window (3% or less = 100, 40% or more = 0)
//   Retreat       parked on the Pi side; flinch distance in cm is still a guess
//   Straight Face Timer  no Pi round yet (mock only)
export const ROUND_DEFS = [
  {
    round_id: 'reflex',
    number: 1,
    round_name: 'Reflex Round',
    prompt: 'Claimed reaction speed',
    actual_unit: 'ms',
    actual_label: 'reaction time',
  },
  {
    round_id: 'steady_hands',
    number: 2,
    round_name: 'Steady Hands',
    prompt: 'Claimed steadiness',
    actual_unit: ' mg RMS',
    actual_label: 'hand tremor',
  },
  {
    round_id: 'retreat',
    number: 3,
    round_name: 'Retreat Round',
    prompt: 'Claimed unshakeability',
    actual_unit: ' cm',
    actual_label: 'flinch distance',
  },
  {
    round_id: 'poker_face',
    number: 5,
    round_name: 'Poker Face Round',
    prompt: 'Claimed poker-face confidence',
    actual_unit: '% smiling',
    actual_label: 'time spent smiling',
  },
  {
    round_id: 'straight_face_timer',
    number: null,
    round_name: 'Straight Face Timer',
    prompt: 'Claimed hold time',
    actual_unit: ' s',
    actual_label: 'seconds held',
  },
]

export function roundById(id) {
  return ROUND_DEFS.find((r) => r.round_id === id)
}

export function roundByNumber(number) {
  return ROUND_DEFS.find((r) => r.number === number)
}
