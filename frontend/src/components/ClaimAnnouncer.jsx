import { useSettledValue } from '../hooks/useSettledValue'

// Screen-reader only. Lives outside the per-screen wrapper in App so the live
// region stays mounted (a freshly inserted live region is often not read).
// While the knob turns it announces the claim once it settles (~0.8 s, at
// most every ~2.4 s); the locked claim is announced straight away.
export const ANNOUNCE_SETTLE_MS = 800

function claimText(screen, claim) {
  const known = claim !== null && claim !== undefined
  if (screen === 'predicting') return known ? `Claim ${claim} out of 100` : 'Claim not set yet'
  if (screen === 'performing') {
    return known ? `Claim locked at ${claim}. Measuring reality.` : 'Claim locked. Measuring reality.'
  }
  return ''
}

export default function ClaimAnnouncer({ screen, liveClaim }) {
  const text = claimText(screen, liveClaim)
  const settled = useSettledValue(text, screen === 'predicting' ? ANNOUNCE_SETTLE_MS : 0)
  return (
    <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {settled}
    </p>
  )
}
