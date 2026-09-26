// Static metadata for each round, matched to The Tell's PRD round table.
// `number` is the internal round type id the Pi uses (pi/main.py --round N, the
// Arduino's "round_id"; stored in the session log, so it never changes);
// `label` is the round number shown on screen (Round 1 / 2 / 3, PRD order);
// `round_id` is the string id used everywhere in this app.
// actual_unit is appended straight after the raw value on the reveal
// ("287ms", "12.5% smiling", "6.4 s held"), so it carries its own spacing.
// Real units, from the Pi backend:
//   Reflex         reaction time in ms (150 ms or faster = 100, 600 ms or slower = 0)
//   Poker Face     % of face frames with a smile over a 6 s webcam window (3% or less = 100, 40% or more = 0)
//   Straight Face  seconds until the face visibly changed under rapid-fire questions
//                  (dial 0-100 = 0-claim_max_s seconds, 20 s by default; the Pi sends the real max)
// Legacy rounds (cut from The Tell, `legacy: true`) stay here only so old session
// rows still render; they're left out of GAME_ROUNDS (idle marquee, mock rotation).
export const ROUND_DEFS = [
  {
    round_id: 'reflex',
    number: 1,
    label: 1,
    round_name: 'Reflex Round',
    prompt: 'Claimed reaction speed under pressure',
    actual_unit: 'ms',
    actual_label: 'reaction time',
  },
  {
    round_id: 'poker_face',
    number: 5,
    label: 2,
    round_name: 'Poker Face',
    prompt: 'Claimed poker face going into a tough interview question',
    uses_camera: true,
    actual_unit: '% smiling',
    actual_label: 'time spent smiling',
  },
  {
    round_id: 'straight_face',
    number: 6,
    label: 3,
    round_name: 'Straight Face Under Pressure',
    prompt: 'Claimed seconds of straight face under rapid-fire questions',
    uses_camera: true,
    claim_max_s: 20,
    actual_unit: ' s held',
    actual_label: 'seconds until the face changed',
  },
  {
    round_id: 'steady_hands',
    number: 2,
    legacy: true,
    round_name: 'Steady Hands',
    prompt: 'Claimed steadiness',
    actual_unit: ' mg RMS',
    actual_label: 'hand tremor',
  },
  {
    round_id: 'retreat',
    number: 3,
    legacy: true,
    round_name: 'Retreat Round',
    prompt: 'Claimed unshakeability',
    actual_unit: ' cm',
    actual_label: 'flinch distance',
  },
]

// The Tell's game, in play order.
export const GAME_ROUNDS = ROUND_DEFS.filter((r) => !r.legacy)

export function roundById(id) {
  return ROUND_DEFS.find((r) => r.round_id === id)
}

export function roundByNumber(number) {
  return ROUND_DEFS.find((r) => r.number === number)
}
