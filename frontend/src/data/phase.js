// Which phase of a round is on screen. One source for the phase chip, the camera
// frame colour and the step numbers, so every screen agrees and a passer-by can
// tell the phase from the colour alone:
//   name     who's playing (Poker Face with the browser UI only)   white
//   claim    the dial is being set                                  cyan (claim)
//   read     the camera window: the face is being read live         purple (reality)
//   scoring  window closed, reveal on its way (well under a second) purple, pulsing
export const PHASES = {
  name: { label: "Who's playing", color: 'var(--color-ink)' },
  claim: { label: 'Set your claim', color: 'var(--color-claim)' },
  read: { label: 'Live read', color: 'var(--color-reality)' },
  scoring: { label: 'Scoring', color: 'var(--color-reality)', pulse: true },
}

export function roundPhase(state) {
  if (state.screen === 'predicting') return state.nameEntry && !state.playerNamed ? 'name' : 'claim'
  if (state.screen !== 'performing') return null
  const camera = state.camera
  if (!state.activeRound?.uses_camera) return 'read'
  if (camera?.mode === 'measuring') return 'read'
  return 'scoring'
}

// "Step 2 of 3". The name step only exists when the session asks for names.
export function phaseStep(phase, nameEntry) {
  const order = nameEntry ? ['name', 'claim', 'read'] : ['claim', 'read']
  const key = phase === 'scoring' ? 'read' : phase
  const i = order.indexOf(key)
  return i < 0 ? null : { step: i + 1, of: order.length }
}
