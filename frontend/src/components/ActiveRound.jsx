import { motion } from 'motion/react'
import { useSettledValue } from '../hooks/useSettledValue'
import { ANNOUNCE_SETTLE_MS } from './ClaimAnnouncer'

const SIZE = 280
const STROKE = 16
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// Covers both the 'predicting' (dial turning) and 'performing' (challenge
// happening, no more claim input) phases of a round.
export default function ActiveRound({ screen, activeRound, player, liveClaim }) {
  // The claim is live from the dial ({"type":"dial"}); unknown only with an older sketch.
  const hasClaim = liveClaim !== null && liveClaim !== undefined
  const value = hasClaim ? liveClaim : 0
  const isPerforming = screen === 'performing'
  // Accessible name for the ring: the settled value, not every step of the knob.
  const labelClaim = useSettledValue(hasClaim ? value : null, isPerforming ? 0 : ANNOUNCE_SETTLE_MS)

  if (!activeRound) return null
  const dialColor = isPerforming ? 'var(--color-reality)' : 'var(--color-claim)'
  const offset = CIRCUMFERENCE * (1 - value / 100)

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <p className="font-game text-sm uppercase tracking-[0.4em] text-ink-dim">{player}</p>

      <h2 key={activeRound.round_id} className="anim-fade-in-up font-display text-4xl text-ink">
        {activeRound.round_name}
      </h2>

      <p className="font-game text-ink-dim">{activeRound.prompt}</p>

      <div
        className="relative"
        style={{ width: SIZE, height: SIZE }}
        role="img"
        aria-label={
          labelClaim === null
            ? 'Claim: not known yet'
            : `Claim: ${labelClaim} out of 100${isPerforming ? ', locked' : ''}`
        }
      >
        <svg width={SIZE} height={SIZE} className="-rotate-90" aria-hidden="true">
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="var(--color-surface-2)"
            strokeWidth={STROKE}
          />
          <motion.circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={dialColor}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: isPerforming ? 0.4 : 0.12, ease: 'linear' }}
            style={{ filter: `drop-shadow(0 0 12px ${dialColor})` }}
          />
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
          <span className="font-game text-7xl font-bold tabular-nums text-ink">{hasClaim ? value : '?'}</span>
          {isPerforming && (
            <motion.span
              className="mt-1 h-2 w-2 rounded-full bg-reality"
              animate={{ opacity: [1, 0.2, 1] }}
              transition={{ duration: 0.8, repeat: Infinity }}
            />
          )}
        </div>
      </div>

      <p key={screen} className="anim-fade-in font-game text-sm uppercase tracking-[0.35em] text-ink-dim">
        {isPerforming ? 'Measuring reality...' : 'Setting the claim...'}
      </p>
    </div>
  )
}
