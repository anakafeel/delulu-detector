import { useEffect } from 'react'
import confetti from 'canvas-confetti'
import { severityFor } from '../data/severity'
import { useCountUp } from '../hooks/useCountUp'
import DeluluCharacter from './DeluluCharacter' // Import the character


const SHAKE_AMPLITUDE = { good: 0, warning: 4, serious: 9, critical: 16 }
const CONFETTI_COUNT = { good: 90, warning: 70, serious: 110, critical: 160 }

export default function RevealMoment({ result }) {
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
        <QuietLine label="Scoring" />
      </div>
    )
  }

  const amplitude = SHAKE_AMPLITUDE[severity.key]
  const verdictText = visibleVerdict(result)

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-6 overflow-hidden text-center">
      <div key={`flash-${result.round_id}`} className="anim-flash pointer-events-none absolute inset-0 z-10" style={{ background: severity.color }} />

      <div
        key={result.round_id}
        className={amplitude ? 'anim-shake flex flex-col items-center gap-6' : 'flex flex-col items-center gap-6'}
        style={{ '--shake-amp': `${amplitude}px` }}
      >
        <p className="font-game text-sm uppercase tracking-[0.4em] text-ink-dim">
          {result.player} · {result.round_name}
        </p>

        <div className="flex items-center gap-10">
          <Stat label="Claimed" value={result.claim} color="var(--color-claim)" />
          <div className="font-display text-2xl text-ink-faint">vs</div>
          <Stat
            label="Reality"
            value={result.actual}
            color="var(--color-reality)"
            sub={`${result.actual_raw}${result.actual_unit}`}
          />
        </div>

        <GapBadge gap={result.gap} color={severity.color} tag={severity.tag} />

        {verdictText ? (
          <p
            className="anim-stamp-in max-w-2xl px-4 font-display text-4xl leading-tight text-ink md:text-5xl"
            style={{ textShadow: `0 0 30px ${severity.color}` }}
          >
            {verdictText}
          </p>
        ) : (
          <QuietLine label="Scoring" />
        )}
        {/* Add the character reaction here */}
        <div className="mt-8">
          <DeluluCharacter 
            tier={severity.key} 
            speaking={true} 
            size={140} 
            />
        </div>
      </div>
    </div>
  )
}

function QuietLine({ label }) {
  return (
    <p className="flex items-center gap-3 font-game text-sm uppercase tracking-[0.45em] text-ink-dim">
      <span className="quiet-pulse inline-block h-2 w-2 rounded-full bg-reality" />
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
      <span className="font-game text-xs uppercase tracking-widest text-ink-dim">{label}</span>
      <span
        className="font-game text-7xl font-bold tabular-nums"
        style={{ color, textShadow: `0 0 20px ${color}` }}
      >
        {animated}
      </span>
      {sub && <span className="font-game text-sm text-ink-dim">{sub}</span>}
    </div>
  )
}

function GapBadge({ gap, color, tag }) {
  const animated = useCountUp(gap, { duration: 800, delay: 150 })
  return (
    <div
      className="anim-pop-in flex items-center gap-3 rounded-full border px-5 py-2 font-game text-lg"
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
