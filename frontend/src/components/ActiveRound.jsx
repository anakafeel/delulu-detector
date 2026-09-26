import { motion } from 'motion/react'
import { useSettledValue } from '../hooks/useSettledValue'
import { ANNOUNCE_SETTLE_MS } from './ClaimAnnouncer'
import CameraFeed from './CameraFeed'

const SIZE = 280
const STROKE = 16
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// Covers both the 'predicting' (dial turning) and 'performing' (challenge
// happening, no more claim input) phases of a round.
export default function ActiveRound({ screen, activeRound, player, liveClaim, camera }) {
  // The claim is live from the dial ({"type":"dial"}); unknown only with an older sketch.
  const hasClaim = liveClaim !== null && liveClaim !== undefined
  const value = hasClaim ? liveClaim : 0
  const isPerforming = screen === 'performing'
  // Accessible name for the ring: the settled value, not every step of the knob.
  const labelClaim = useSettledValue(hasClaim ? value : null, isPerforming ? 0 : ANNOUNCE_SETTLE_MS)

  if (!activeRound) return null
  const dialColor = isPerforming ? 'var(--color-reality)' : 'var(--color-claim)'
  const offset = CIRCUMFERENCE * (1 - value / 100)
  // The face rounds: show the player their own face (with the OpenCV overlay) next to the dial.
  const showCamera = activeRound.uses_camera === true
  // Straight Face: the dial's 0-100 stands for 0-claim_max_s seconds.
  const claimSeconds = activeRound.claim_max_s && hasClaim ? (value / 100) * activeRound.claim_max_s : null

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <p className="font-game text-sm uppercase tracking-[0.4em] text-ink-dim">{player}</p>

      <div key={activeRound.round_id} className="anim-fade-in-up flex flex-col items-center gap-2">
        {activeRound.label && (
          <span className="font-game text-xs uppercase tracking-[0.5em] text-claim">Round {activeRound.label}</span>
        )}
        <h2 className="font-display text-4xl text-ink">{activeRound.round_name}</h2>
      </div>

      <p className="font-game text-ink-dim">{activeRound.prompt}</p>

      <div className="flex flex-wrap items-center justify-center gap-10">
        {showCamera && <CameraFeed camera={camera} isPerforming={isPerforming} />}
        <div
          className="relative"
          style={{ width: SIZE, height: SIZE }}
          role="img"
          aria-label={
            labelClaim === null
              ? 'Claim: not known yet'
              : `Claim: ${labelClaim} out of 100${
                  activeRound.claim_max_s
                    ? ` (${((labelClaim / 100) * activeRound.claim_max_s).toFixed(1)} seconds)`
                    : ''
                }${isPerforming ? ', locked' : ''}`
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
            {claimSeconds !== null && (
              <span className="font-game text-lg tabular-nums text-ink-dim">= {claimSeconds.toFixed(1)} s</span>
            )}
            {isPerforming && (
              <motion.span
                className="mt-1 h-2 w-2 rounded-full bg-reality"
                animate={{ opacity: [1, 0.2, 1] }}
                transition={{ duration: 0.8, repeat: Infinity }}
              />
            )}
          </div>
        </div>
      </div>

      <p key={screen} className="anim-fade-in font-game text-sm uppercase tracking-[0.35em] text-ink-dim">
        {isPerforming ? 'Measuring reality...' : 'Setting the claim...'}
      </p>
    </div>
  )
}
