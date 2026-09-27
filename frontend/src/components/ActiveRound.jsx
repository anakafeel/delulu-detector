import { useSettledValue } from '../hooks/useSettledValue'
import { useFollowNumber } from '../hooks/useFollowNumber'
import { ANNOUNCE_SETTLE_MS } from './ClaimAnnouncer'
import CameraFeed from './CameraFeed'
import NameEntry from './NameEntry'
import { PHASES, phaseStep, roundPhase } from '../data/phase'

const SIZE = 280
const DIAL_FOLLOW_MS = 200
// Composure arrives up to 4 times a second (a running mean from Presage): a short chase
// keeps it moving smoothly without holding the number back.
const COMPOSURE_FOLLOW_MS = 300

function ringSize() {
  const h = typeof window === 'undefined' ? 900 : window.innerHeight
  return Math.round(Math.min(240, Math.max(150, h * 0.19)))
}

// Covers both the 'predicting' (dial turning) and 'performing' (challenge
// happening, no more claim input) phases of a round.
export default function ActiveRound({
  screen, activeRound, player, playerNamed, nameEntry, liveClaim, camera, beat, notice, names, onHelp,
}) {
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
  const dialColor = 'var(--color-claim)'
  // Straight Face: the dial's 0-100 stands for 0-claim_max_s seconds.
  const claimMaxS = activeRound.claim_max_s

  if (showCamera) {
    const phase = roundPhase({ screen, nameEntry, playerNamed, camera, activeRound }) ?? 'claim'
    const reading = phase === 'read' || phase === 'scoring'
    const size = ringSize()
    const question = isPerforming && notice?.level === 'info' ? notice.message : null
    const askName = !isPerforming && nameEntry
    return (
      <div className="relative h-full w-full">
        <CameraFeed camera={camera} isPerforming={isPerforming} />
        {/* On top of the video: an inset shadow on the parent would paint under it. */}
        <div
          className={`phase-frame pointer-events-none absolute inset-0 z-10 rounded-2xl ${PHASES[phase].pulse ? 'quiet-pulse' : ''}`}
          style={{ '--phase-color': PHASES[phase].color }}
        />
        {(scoring || windowClosed) && <ScoreBeat />}
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-6 p-6">
          <div className="flex flex-col items-start gap-3 text-left">
            <PhaseChip phase={phase} nameEntry={nameEntry} />
            <p className="rounded-lg bg-void/70 px-3 py-1 font-display text-title text-ink">{player}</p>
            <p className="rounded bg-void/70 px-3 py-0.5 font-game text-meta uppercase tracking-[0.3em] text-ink-dim">
              {activeRound.label ? `Round ${activeRound.label} · ` : ''}
              {activeRound.round_name}
            </p>
            {askName && playerNamed && (
              <NameEntry entry={names} variant="compact" player={player} onHelp={onHelp} />
            )}
          </div>
          <div className="flex items-start gap-5">
            <Ring label="Claim" sub={isPerforming ? 'locked' : 'turn the dial'} color="var(--color-claim)">
              <Dial
                size={size}
                value={hasClaim ? value : null}
                dialColor={dialColor}
                isPerforming={isPerforming}
                labelClaim={labelClaim}
                claimMaxS={claimMaxS}
              />
            </Ring>
            {reading && (
              <Ring label="Composure" sub="live, so far" color="var(--color-reality)">
                <ComposureRing size={size} value={camera?.composure} />
              </Ring>
            )}
          </div>
        </div>
        {askName && !playerNamed && (
          <div className="pointer-events-none absolute inset-x-0 bottom-24 z-30 flex justify-center">
            <NameEntry
              entry={names}
              variant="prompt"
              lead="Before the camera reads you: who's in the hot seat?"
              onHelp={onHelp}
            />
          </div>
        )}
        {askName && playerNamed && (
          <p className="pointer-events-none absolute inset-x-0 bottom-24 z-20 text-center">
            <span className="rounded-xl bg-void/80 px-6 py-3 font-game text-data text-ink">
              Turn the dial: how unreadable is your face? Press the button to lock it.
            </span>
          </p>
        )}
        {question && <QuestionCard key={question} text={question} />}
      </div>
    )
  }

  const status = !isPerforming ? 'Setting the claim...' : scoring || !hasClaim ? 'Scoring' : 'Measuring reality...'

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <p className="font-display text-title text-ink">{player}</p>

      <div key={activeRound.round_id} className="anim-fade-in-up flex flex-col items-center gap-2">
        {activeRound.label && (
          <span className="font-game text-meta uppercase tracking-[0.4em] text-claim">Round {activeRound.label}</span>
        )}
        <h2 className="font-display text-title text-ink">{activeRound.round_name}</h2>
      </div>

      <p className="font-game text-data text-ink-dim">{activeRound.prompt}</p>

      <Dial
        size={SIZE}
        value={hasClaim ? value : null}
        dialColor={isPerforming ? 'var(--color-reality)' : 'var(--color-claim)'}
        isPerforming={isPerforming}
        labelClaim={labelClaim}
        claimMaxS={claimMaxS}
      />

      <p
        key={status}
        className="anim-fade-in flex items-center gap-3 font-game text-data uppercase tracking-[0.3em] text-ink-dim"
      >
        {isPerforming && (scoring || !hasClaim) && <span className="quiet-pulse inline-block h-3 w-3 rounded-full bg-reality" />}
        {status}
      </p>
    </div>
  )
}

function PhaseChip({ phase, nameEntry }) {
  const def = PHASES[phase]
  const step = phaseStep(phase, nameEntry)
  return (
    <p
      key={phase}
      className="anim-fade-in flex items-center gap-3 rounded-full border-4 bg-void/85 px-5 py-2 font-display text-data uppercase"
      style={{ borderColor: def.color, color: def.color }}
    >
      {phase === 'read' && <span className="quiet-pulse inline-block h-4 w-4 rounded-full bg-critical" aria-hidden="true" />}
      {def.pulse && <span className="quiet-pulse inline-block h-4 w-4 rounded-full" style={{ background: def.color }} aria-hidden="true" />}
      {step && <span className="text-ink-dim">{step.step}/{step.of}</span>}
      {def.label}
    </p>
  )
}

function Ring({ label, sub, color, children }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl bg-void/70 px-4 pb-3 pt-2">
      <p className="flex flex-col items-center font-game text-data font-bold uppercase tracking-[0.25em]" style={{ color }}>
        {label}
        <span className="font-game text-meta font-normal normal-case tracking-normal text-ink-dim">{sub ?? '\u00a0'}</span>
      </p>
      {children}
    </div>
  )
}

// The live read: Presage's running composure for this window. It moves while the
// question plays; before the first classified frame it says it is still reading.
function ComposureRing({ size, value }) {
  const known = typeof value === 'number'
  const followed = useFollowNumber(known ? value : null, COMPOSURE_FOLLOW_MS)
  const stroke = Math.max(10, Math.round(size * 0.057))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const shown = followed == null ? 0 : followed
  return (
    <div
      className="relative"
      style={{ width: size, height: size }}
      role="img"
      aria-label={known ? `Composure so far: ${Math.round(value)} out of 100` : 'Reading your face'}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-surface-2)" strokeWidth={stroke} />
        {known && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - shown / 100)}
            style={{ stroke: 'var(--color-reality)', filter: 'drop-shadow(0 0 12px var(--color-reality))' }}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
        {known ? (
          <span className="font-game font-bold tabular-nums text-ink" style={{ fontSize: size * 0.32 }}>
            {Math.round(shown)}
          </span>
        ) : (
          <span className="flex flex-col items-center gap-2 font-game text-meta uppercase tracking-[0.2em] text-reality">
            <span className="quiet-pulse inline-block h-4 w-4 rounded-full bg-reality" />
            reading
          </span>
        )}
      </div>
    </div>
  )
}

function QuestionCard({ text }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-20 z-20 flex justify-center px-6">
      <div className="anim-fade-in-up w-[min(100%,72rem)] rounded-2xl border-l-8 border-claim bg-void/90 px-8 py-5 text-left">
        <p className="font-game text-meta uppercase tracking-[0.35em] text-claim">The question</p>
        <p className="mt-1 font-display text-headline text-ink">{text}</p>
      </div>
    </div>
  )
}

function ScoreBeat() {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
      <p className="anim-fade-in flex items-center gap-4 rounded-full border-4 border-reality bg-void/85 px-10 py-4 font-display text-title uppercase text-ink">
        <span className="quiet-pulse inline-block h-5 w-5 rounded-full bg-reality" />
        Scoring your face
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
          <span className="font-game tabular-nums text-ink-dim" style={{ fontSize: Math.max(16, size * 0.1) }}>
            = {seconds.toFixed(1)} s
          </span>
        )}
      </div>
    </div>
  )
}
