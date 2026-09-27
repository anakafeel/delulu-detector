import { memo, useMemo } from 'react'
import { leaderboardRows } from '../data/deriveStats'

// memo: the live dial updates the app state up to 10 times a second; history
// keeps the same reference then (dataSource.js), so the leaderboard is skipped.
function Leaderboard({ history }) {
  const rows = useMemo(() => leaderboardRows(history), [history])
  const totalRounds = history.length

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h3 className="font-display text-data uppercase tracking-[0.15em] text-ink">
          Leaderboard
        </h3>
        <span className="font-game text-meta text-ink-dim">{totalRounds} rounds played</span>
      </div>

      {rows.length === 0 ? (
        <p className="font-game text-data text-ink-dim">No rounds yet. Be the first.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          <div className="grid grid-cols-[1.6rem_1fr_3.5rem_4.5rem_2.5rem] gap-2 px-2 font-game text-meta uppercase tracking-wide text-ink-dim">
            <span />
            <span>Player</span>
            <span className="text-right">Best</span>
            <span className="text-right">Worst</span>
            <span className="text-right">Rds</span>
          </div>

          {rows.map((row, i) => (
            <div
              key={row.player}
              className="anim-fade-in-up grid grid-cols-[1.6rem_1fr_3.5rem_4.5rem_2.5rem] items-center gap-2 rounded-md border border-ink-faint/30 bg-surface px-2 py-2 font-game text-data"
            >
              <span
                className="text-meta font-bold"
                style={{ color: i === 0 ? 'var(--color-good)' : 'var(--color-ink-dim)' }}
              >
                {i + 1}
              </span>
              <span className="truncate text-ink">{row.player}</span>
              <span className="text-right font-bold tabular-nums text-good">{row.bestGap}</span>
              <span className="text-right font-bold tabular-nums text-critical">
                {row.worstGap}
              </span>
              <span className="text-right tabular-nums text-ink-dim">{row.rounds}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default memo(Leaderboard)
