// frontend/src/components/RoundProgressGrid.jsx
import { motion } from 'motion/react'
import { ROUND_DEFS } from '../data/roundDefs'

const STATUS_STYLE = {
  done:     { ring: 'border-good',     dot: 'bg-good',     text: 'text-good',     label: 'DONE' },
  current:  { ring: 'border-claim',    dot: 'bg-claim',    text: 'text-claim',    label: 'NOW' },
  upcoming: { ring: 'border-ink-faint/30', dot: 'bg-ink-faint', text: 'text-ink-faint', label: 'NEXT' },
  locked:   { ring: 'border-ink-faint/15', dot: 'bg-ink-faint/40', text: 'text-ink-faint/60', label: '—' },
}

function statusFor(round, activeRound, history) {
  if (activeRound?.round_id === round.round_id) return 'current'
  const played = history.some((h) => h.round_name === round.round_name)
  if (played) return 'done'
  return 'upcoming'
}

export default function RoundProgressGrid({ activeRound, history }) {
  const total = ROUND_DEFS.length
  const done = history.filter((h) =>
    ROUND_DEFS.some((r) => r.round_name === h.round_name)
  ).length
  const pct = total ? Math.round((done / total) * 100) : 0

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h3 className="font-display text-xs uppercase tracking-[0.3em] text-ink-dim">
          Gauntlet
        </h3>
        <span className="font-game text-xs text-ink-faint">
          {done}/{total} cleared
        </span>
      </div>

      {/* Progress bar */}
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-claim to-reality"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 20 }}
          style={{ boxShadow: '0 0 12px var(--color-claim)' }}
        />
      </div>

      {/* Round grid */}
      <div className="grid grid-cols-2 gap-2">
        {ROUND_DEFS.map((round, i) => {
          const status = statusFor(round, activeRound, history)
          const s = STATUS_STYLE[status]
          const isCurrent = status === 'current'
          return (
            <motion.div
              key={round.round_id}
              className={`relative flex flex-col gap-1 rounded-lg border bg-surface px-3 py-2 ${s.ring}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
            >
              {isCurrent && (
                <motion.span
                  className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-claim"
                  animate={{ scale: [1, 1.4, 1], opacity: [1, 0.6, 1] }}
                  transition={{ duration: 1.2, repeat: Infinity }}
                  style={{ boxShadow: '0 0 10px var(--color-claim)' }}
                />
              )}
              <div className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
                <span className={`font-game text-[0.6rem] uppercase tracking-widest ${s.text}`}>
                  {s.label}
                </span>
              </div>
              <span className="font-game text-xs leading-tight text-ink">
                {round.round_name}
              </span>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}