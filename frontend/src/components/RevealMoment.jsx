import { useEffect } from 'react'
import confetti from 'canvas-confetti'
import { severityFor } from '../data/severity'
import { useCountUp } from '../hooks/useCountUp'
import { compareToTonight } from '../data/compare'

const SHAKE_AMPLITUDE = { good: 0, warning: 4, serious: 9, critical: 16 }
const CONFETTI_COUNT = { good: 90, warning: 70, serious: 110, critical: 160 }

export default function RevealMoment({ result, history = [] }) {
  const severity = result ? severityFor(result.gap) : null

  useEffect(() => {
    if (!result || !severity) return
    confetti({
      particleCount: CONFETTI_COUNT[severity.key],
      spread: severity.key === 'critical' ? 100 : 65,
      startVelocity: severity.key === 'critical' ? 55 : 40,
      origin: { y: 0.5 },
      colors: [severity.color, '#f5f4f0', 'var(--color-claim)'].map(resolveColor),
      scalar: severity.key === 'critical' ? 1.2 : 1,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.round_id])

  if (!result || !severity) {
    return (
      <div className="flex h-full flex-col items-center justify-center">
        <QuietLine label="Scoring your face" />
      </div>
    )
  }

  const amplitude = SHAKE_AMPLITUDE[severity.key]
  const verdictText = visibleVerdict(result)
  const composure = result.actual_unit?.trim() === 'composure'

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-5 overflow-hidden px-6 text-center">
      <div key={`flash-${result.round_id}`} className="anim-flash pointer-events-none absolute inset-0 z-10" style={{ background: severity.color }} />

      <div
        key={result.round_id}
        className={amplitude ? 'anim-shake flex flex-col items-center gap-5' : 'flex flex-col items-center gap-5'}
        style={{ '--shake-amp': `${amplitude}px` }}
      >
        <p className="font-game text-meta uppercase tracking-[0.3em] text-ink-dim">
          <span className="font-display text-data normal-case tracking-normal text-ink">{result.player}</span>
          {' '}· {result.round_name} · Result
        </p>

        <div className="flex items-center gap-10">
          <Stat label="Claimed" value={result.claim} color="var(--color-claim)" />
          <div className="font-display text-title text-ink-dim">vs</div>
          <Stat
            label={composure ? 'Composure' : 'Reality'}
            value={result.actual}
            color="var(--color-reality)"
            sub={composure ? null : `${result.actual_raw}${result.actual_unit}`}
          />
        </div>

        <div className="flex flex-wrap items-center justify-center gap-4">
          <GapBadge gap={result.gap} color={severity.color} tag={severity.tag} />
          {result.gap_exact != null && result.score != null && (
            <span className="font-game text-data text-ink-dim">
              Score <span className="font-bold tabular-nums text-ink">{result.score}</span>
            </span>
          )}
        </div>
        <MathLine result={result} composure={composure} />

        {verdictText ? (
          <p
            className="anim-stamp-in max-w-[min(64rem,100%)] px-4 font-display text-headline text-ink"
            style={{ textShadow: `0 0 30px ${severity.color}` }}
          >
            {verdictText}
          </p>
        ) : (
          <QuietLine label="Verdict on its way" />
        )}

        <HowYouCompare result={result} history={history} />
        <p className="font-game text-meta text-ink-faint">
          Press <kbd className="rounded border border-ink-faint px-1.5 text-ink-dim">?</kbd> for how this is calculated
        </p>
      </div>
    </div>
  )
}

// The whole calculation, with the Pi's one-decimal numbers so it adds up exactly.
function MathLine({ result, composure }) {
  if (result.gap_exact == null || result.actual_exact == null) return null
  const reality = composure ? 'composure' : 'reality'
  return (
    <p className="font-game text-meta tabular-nums text-ink-dim">
      gap = |{result.claim} claim − {fmt(result.actual_exact)} {reality}| = {fmt(result.gap_exact)} · score = 100 − gap
    </p>
  )
}

function fmt(n) {
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

// Real counts over the rounds logged tonight, with the sample size said out loud.
function HowYouCompare({ result, history }) {
  const c = compareToTonight(result, history)
  if (!c) return null
  const kind = result.round_name
  let line
  if (c.others === 0) {
    line = <>First {kind} round logged tonight. Nothing to compare with yet.</>
  } else {
    line = (
      <>
        Better calibrated than <b className="text-ink">{c.closer}</b> of the {c.others} other {kind} round{c.others === 1 ? '' : 's'} tonight
        {c.tied > 0 && <> ({c.tied} tied)</>}
        {' · '}
        {c.isBest ? (
          <b className="text-good">tonight's best gap</b>
        ) : (
          <>tonight's best gap: <b className="text-ink">{fmt(c.best)}</b></>
        )}
      </>
    )
  }
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border border-ink-faint/50 bg-surface/80 px-6 py-3">
      <p className="font-game text-data text-ink-dim">{line}</p>
      <p className="font-game text-meta text-ink-faint">
        Based on {c.total} {kind} round{c.total === 1 ? '' : 's'} logged tonight
        {c.small ? ', a small sample that grows as people play' : ''}.
      </p>
    </div>
  )
}

function QuietLine({ label }) {
  return (
    <p className="flex items-center gap-3 font-game text-data uppercase tracking-[0.3em] text-ink-dim">
      <span className="quiet-pulse inline-block h-3 w-3 rounded-full bg-reality" />
      {label}
    </p>
  )
}

// The Pi's spoken line, or the fixed fallback when it has none. Never a canned roast.
function visibleVerdict(result) {
  if (result.verdict_status === 'unavailable') return 'verdict unavailable'
  const text = typeof result.verdict_text === 'string' ? result.verdict_text.trim() : ''
  if (text) return result.verdict_text
  if (result.verdict_status === 'pending') return ''
  return 'verdict unavailable'
}

function Stat({ label, value, color, sub }) {
  const animated = useCountUp(value, { duration: 800 })
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="font-game text-data font-bold uppercase tracking-widest" style={{ color }}>{label}</span>
      <span
        className="font-game text-stat font-bold tabular-nums"
        style={{ color, textShadow: `0 0 20px ${color}` }}
      >
        {animated}
      </span>
      {sub && <span className="font-game text-meta text-ink-dim">{sub}</span>}
    </div>
  )
}

function GapBadge({ gap, color, tag }) {
  const animated = useCountUp(gap, { duration: 800, delay: 150 })
  return (
    <div
      className="anim-pop-in flex items-center gap-3 rounded-full border-4 px-6 py-2 font-game text-title"
      style={{ borderColor: color, boxShadow: `0 0 22px ${color}55` }}
    >
      <span className="uppercase tracking-widest text-ink-dim">Gap</span>
      <span className="font-bold tabular-nums" style={{ color }}>
        {animated}
      </span>
      <span className="uppercase tracking-widest" style={{ color }}>
        {tag}
      </span>
    </div>
  )
}

// canvas-confetti wants resolved hex/rgb, not CSS var() strings.
function resolveColor(value) {
  if (!value.startsWith('var(')) return value
  const probe = document.createElement('span')
  probe.style.color = value
  document.body.appendChild(probe)
  const resolved = getComputedStyle(probe).color
  document.body.removeChild(probe)
  return resolved
}
