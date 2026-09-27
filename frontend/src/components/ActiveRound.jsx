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
  return Math.round(Math.min(168, Math.max(110, h * 0.16)))
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
    const needName = !isPerforming && nameEntry && !playerNamed
    // Three regions that never overlap: the camera (left), the numbers (right), and the
    // question strip (bottom, fixed height, so the video never resizes when it appears).
    return (
      <div className="grid h-full w-full grid-cols-[1fr_auto] grid-rows-[1fr_auto] bg-void">
        <div className="relative min-h-0 min-w-0 overflow-hidden bg-black">
          {/* The camera only exists once the claim is locked: no feed on the name or dial steps. */}
          {isPerforming ? (
            <CameraFeed camera={camera} isPerforming={isPerforming} />
          ) : (
            <BeforeCamera needName={needName} names={names} onHelp={onHelp} />
          )}
          <div
            className={`phase-frame pointer-events-none absolute inset-0 z-10 ${PHASES[phase].pulse ? 'quiet-pulse' : ''}`}
            style={{ '--phase-color': PHASES[phase].color }}
          />
          {(scoring || windowClosed) && <ScoreBeat />}
        </div>

        <aside className="row-span-2 flex w-[clamp(11rem,16vw,15rem)] flex-col items-center gap-3 overflow-hidden border-l border-ink-faint/30 p-4 text-center">
          <PhaseChip phase={phase} nameEntry={nameEntry} />
          <p className="max-w-full truncate font-display text-2xl text-ink">{player}</p>
          <p className="font-game text-meta uppercase tracking-[0.2em] text-ink-dim">
            {activeRound.label ? `Round ${activeRound.label} · ` : ''}
            {activeRound.round_name}
          </p>
          {!needName && (
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
          )}
          {reading && (
            <Ring label="Composure" sub="live, so far" color="var(--color-reality)">
              <ComposureRing size={size} value={camera?.composure} />
            </Ring>
          )}
          {reading && <PresageLive camera={camera} />}
        </aside>

        <div className="flex h-32 min-w-0 items-center border-t border-ink-faint/30 px-6">
          {question ? (
            <QuestionStrip key={question} text={question} />
          ) : isPerforming ? (
            <p className="font-game text-data text-ink-dim">Look at the camera and keep a straight face.</p>
          ) : needName ? (
            <p className="font-game text-data text-ink">Type your name and press Enter. The dial and camera come next.</p>
          ) : (
            <div className="flex w-full flex-wrap items-center justify-between gap-3">
              <p className="font-game text-data text-ink">
                Turn the dial: how unreadable is your face? Press the button to lock it and start the camera.
              </p>
              {nameEntry && <NameEntry entry={names} variant="compact" player={player} onHelp={onHelp} />}
            </div>
          )}
        </div>
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
      className="anim-fade-in flex items-center gap-2 rounded-full border-2 bg-void/85 px-3 py-1 font-display text-meta uppercase"
      style={{ borderColor: def.color, color: def.color }}
    >
      {phase === 'read' && <span className="quiet-pulse inline-block h-2.5 w-2.5 rounded-full bg-critical" aria-hidden="true" />}
      {def.pulse && <span className="quiet-pulse inline-block h-2.5 w-2.5 rounded-full" style={{ background: def.color }} aria-hidden="true" />}
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

// The live question, in its own strip under the camera. Long questions step down a size
// and wrap to two lines instead of growing into the video.
function QuestionStrip({ text }) {
  const size = text.length > 70 ? 'text-2xl' : 'text-question'
  return (
    <div className="anim-fade-in flex min-w-0 items-center gap-5">
      <span className="shrink-0 border-l-8 border-claim pl-3 font-game text-meta uppercase tracking-[0.3em] text-claim">
        Question
      </span>
      <p className={`line-clamp-2 font-display ${size} text-ink`}>{text}</p>
    </div>
  )
}

// Before the claim locks there is no camera on screen, only the next step.
function BeforeCamera({ needName, names, onHelp }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      {needName ? (
        <NameEntry entry={names} variant="prompt" lead="Before the camera reads you: who's in the hot seat?" onHelp={onHelp} />
      ) : (
        <>
          <p className="font-display text-3xl text-ink">Camera is off</p>
          <p className="font-game text-data text-ink-dim">It starts the moment you lock your claim with the button.</p>
        </>
      )}
    </div>
  )
}

// Shown only while Presage's numbers are actually arriving for this window.
function PresageLive({ camera }) {
  const live = camera?.mode === 'measuring' && typeof camera?.composure === 'number'
  return (
    <p className="flex items-center gap-2 font-game text-meta text-ink-dim">
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${live ? 'quiet-pulse bg-reality' : 'bg-ink-faint'}`}
        aria-hidden="true"
      />
      {live ? 'Presage SmartSpectra · live' : camera?.mode === 'measuring' ? 'Presage: waiting for first read' : 'Presage SmartSpectra'}
    </p>
  )
}

function ScoreBeat() {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
      <p className="anim-fade-in flex items-center gap-3 rounded-full border-2 border-reality bg-void/85 px-7 py-3 font-game text-data uppercase tracking-[0.3em] text-ink">
        <span className="quiet-pulse inline-block h-2.5 w-2.5 rounded-full bg-reality" />
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
