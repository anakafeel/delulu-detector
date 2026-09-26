import { useSettledValue } from '../hooks/useSettledValue'
import { useFollowNumber } from '../hooks/useFollowNumber'
import { ANNOUNCE_SETTLE_MS } from './ClaimAnnouncer'
import CameraFeed from './CameraFeed'

const SIZE = 280
const DIAL_FOLLOW_MS = 200

// Covers both the 'predicting' (dial turning) and 'performing' (challenge
// happening, no more claim input) phases of a round.
export default function ActiveRound({ screen, activeRound, player, liveClaim, camera, beat }) {
  // The claim is live from the dial ({"type":"dial"}); unknown only with an older sketch.
  const hasClaim = liveClaim !== null && liveClaim !== undefined
  const value = hasClaim ? liveClaim : 0
  const isPerforming = screen === 'performing'
  // Accessible name for the ring: the settled value, not every step of the knob.
  const labelClaim = useSettledValue(hasClaim ? value : null, isPerforming ? 0 : ANNOUNCE_SETTLE_MS)
  const scoring = beat === 'scoring' || camera?.mode === 'scoring'
  const showCamera = activeRound?.uses_camera === true
  // Claim is locked and the camera window has already closed: reveal numbers are not here yet.
  const windowClosed = showCamera && isPerforming && !scoring && (camera?.mode == null)

  if (!activeRound) return null
  const dialColor = isPerforming ? 'var(--color-reality)' : 'var(--color-claim)'
  // Straight Face: the dial's 0-100 stands for 0-claim_max_s seconds.
  const claimMaxS = activeRound.claim_max_s

  if (showCamera) {
    return (
      <div className="relative h-full w-full">
        <CameraFeed camera={camera} isPerforming={isPerforming} />
        {(scoring || windowClosed) && <ScoreBeat />}
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between p-5">
          <div className="text-left">
            <p className="font-game text-xs uppercase tracking-[0.4em] text-ink">{player}</p>
            <h2 className="font-display text-3xl text-ink">{activeRound.round_name}</h2>
          </div>
          <Dial
            size={168}
            value={hasClaim ? value : null}
            dialColor={dialColor}
            isPerforming={isPerforming}
            labelClaim={labelClaim}
            claimMaxS={claimMaxS}
          />
        </div>
      </div>
    )
  }

  const status = !isPerforming ? 'Setting the claim...' : scoring || !hasClaim ? 'Scoring' : 'Measuring reality...'

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
        value={hasClaim ? value : null}
        dialColor={dialColor}
        isPerforming={isPerforming}
        labelClaim={labelClaim}
        claimMaxS={claimMaxS}
      />

      <p
        key={status}
        className={`anim-fade-in flex items-center gap-3 font-game uppercase tracking-[0.35em] text-ink-dim ${
          isPerforming && (scoring || !hasClaim) ? 'text-lg' : 'text-sm'
        }`}
      >
        {isPerforming && (scoring || !hasClaim) && <span className="quiet-pulse inline-block h-2 w-2 rounded-full bg-reality" />}
        {status}
      </p>
    </div>
  )
}

function ScoreBeat() {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
      <p className="anim-fade-in flex items-center gap-3 rounded-full border border-ink-faint/50 bg-void/80 px-7 py-3 font-game text-lg uppercase tracking-[0.42em] text-ink">
        <span className="quiet-pulse inline-block h-2.5 w-2.5 rounded-full bg-reality" />
        Reading the face
        <span className="text-ink-dim">· Scoring</span>
      </p>
    </div>
  )
}

function Dial({ size, value, dialColor, isPerforming, labelClaim, claimMaxS }) {
  const followed = useFollowNumber(value, DIAL_FOLLOW_MS)
  const shown = followed == null ? 0 : followed
  const display = followed == null ? '?' : Math.round(followed)
  const stroke = Math.max(10, Math.round(size * 0.057))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - shown / 100)
  const seconds = claimMaxS && followed != null ? (followed / 100) * claimMaxS : null
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
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            stroke: dialColor,
            filter: `drop-shadow(0 0 12px ${dialColor})`,
            transition: 'stroke 400ms ease, filter 400ms ease',
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
        <span className="font-game font-bold tabular-nums text-ink" style={{ fontSize: size * 0.32 }}>
          {display}
        </span>
        {seconds !== null && (
          <span className="font-game tabular-nums text-ink-dim" style={{ fontSize: size * 0.1 }}>
            = {seconds.toFixed(1)} s
          </span>
        )}
      </div>
    </div>
  )
}
