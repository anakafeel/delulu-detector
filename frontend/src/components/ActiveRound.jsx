import { motion } from 'motion/react'

const SIZE = 280
const STROKE = 16
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// Covers both the 'predicting' (dial turning) and 'performing' (challenge
// happening, no more claim input) phases of a round.
export default function ActiveRound({ screen, activeRound, player, liveClaim }) {
  if (!activeRound) return null

  // Rounds 1-2 only reveal the locked claim with the result, so it can be unknown here.
  const hasClaim = liveClaim !== null && liveClaim !== undefined
  const value = hasClaim ? liveClaim : 0
  const isPerforming = screen === 'performing'
  const dialColor = isPerforming ? 'var(--color-reality)' : 'var(--color-claim)'
  const offset = CIRCUMFERENCE * (1 - value / 100)

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <p className="font-game text-sm uppercase tracking-[0.4em] text-ink-dim">{player}</p>

      <h2 key={activeRound.round_id} className="anim-fade-in-up font-display text-4xl text-ink">
        {activeRound.round_name}
      </h2>

      <p className="font-game text-ink-dim">{activeRound.prompt}</p>

      <div className="relative" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} className="-rotate-90">
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

        <div className="absolute inset-0 flex flex-col items-center justify-center">
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
