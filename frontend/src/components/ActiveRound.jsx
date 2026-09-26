import { motion } from 'motion/react'
import { useSettledValue } from '../hooks/useSettledValue'
import { ANNOUNCE_SETTLE_MS } from './ClaimAnnouncer'
import CameraFeed from './CameraFeed'

const SIZE = 280

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
  // The face rounds: show the player their own face (with the OpenCV overlay) next to the dial.
  const showCamera = activeRound.uses_camera === true
  // Straight Face: the dial's 0-100 stands for 0-claim_max_s seconds.
  const claimSeconds = activeRound.claim_max_s && hasClaim ? (value / 100) * activeRound.claim_max_s : null

  if (showCamera) {
    return (
      <div className="relative h-full w-full">
        <CameraFeed camera={camera} isPerforming={isPerforming} />
        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-5">
          <div className="text-left">
            <p className="font-game text-xs uppercase tracking-[0.4em] text-ink">{player}</p>
            <h2 className="font-display text-3xl text-ink">{activeRound.round_name}</h2>
          </div>
          <Dial
            size={168}
            value={value}
            hasClaim={hasClaim}
            dialColor={dialColor}
            isPerforming={isPerforming}
            labelClaim={labelClaim}
            claimSeconds={claimSeconds}
            claimMaxS={activeRound.claim_max_s}
          />
        </div>
      </div>
    )
  }

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

      <Dial
        size={SIZE}
        value={value}
        hasClaim={hasClaim}
        dialColor={dialColor}
        isPerforming={isPerforming}
        labelClaim={labelClaim}
        claimSeconds={claimSeconds}
        claimMaxS={activeRound.claim_max_s}
      />

      <p key={screen} className="anim-fade-in font-game text-sm uppercase tracking-[0.35em] text-ink-dim">
        {isPerforming ? 'Measuring reality...' : 'Setting the claim...'}
      </p>
    </div>
  )
}

function Dial({ size, value, hasClaim, dialColor, isPerforming, labelClaim, claimSeconds, claimMaxS }) {
  const stroke = Math.max(10, Math.round(size * 0.057))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - value / 100)
  return (
    <div
      className="relative"
      style={{ width: size, height: size }}
      role="img"
      aria-label={
        labelClaim === null
          ? 'Claim: not known yet'
          : `Claim: ${labelClaim} out of 100${
              claimMaxS ? ` (${((labelClaim / 100) * claimMaxS).toFixed(1)} seconds)` : ''
            }${isPerforming ? ', locked' : ''}`
      }
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-surface-2)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={dialColor}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: isPerforming ? 0.4 : 0.12, ease: 'linear' }}
          style={{ filter: `drop-shadow(0 0 12px ${dialColor})` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
        <span className="font-game font-bold tabular-nums text-ink" style={{ fontSize: size * 0.32 }}>
          {hasClaim ? value : '?'}
        </span>
        {claimSeconds !== null && (
          <span className="font-game tabular-nums text-ink-dim" style={{ fontSize: size * 0.1 }}>
            = {claimSeconds.toFixed(1)} s
          </span>
        )}
      </div>
    </div>
  )
}
