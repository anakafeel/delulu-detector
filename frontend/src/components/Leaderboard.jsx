import { leaderboardRows } from '../data/deriveStats'

export default function Leaderboard({ history, onClose }) {
  const rows = leaderboardRows(history)
  const totalRounds = history.length

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-sm font-semibold text-ink">Leaderboard</h2>
        <div className="flex items-center gap-2">
          <span className="font-game text-[10px] tabular-nums text-ink-dim">{totalRounds} scored</span>
          <button
            type="button"
            onClick={onClose}
            className="widget-close"
            aria-label="Close leaderboard"
            title="Close leaderboard"
          >
            <span aria-hidden="true">&times;</span>
          </button>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="border-l-2 border-claim/70 py-2 pl-3">
          <p className="font-game text-xs text-ink-dim">No scored rounds yet.</p>
          <p className="mt-1 font-game text-[10px] text-ink-faint">The first result sets the pace.</p>
        </div>
      ) : (
        <div className="min-w-0">
          <div className="grid grid-cols-[minmax(0,1fr)_3.25rem_3.5rem_2.25rem] gap-2 border-b border-ink-faint/35 px-1 pb-2 font-game text-[9px] font-semibold text-ink-faint">
            <span>PLAYER</span>
            <span className="text-right">BEST</span>
            <span className="text-right">WIDEST</span>
            <span className="text-right">RDS</span>
          </div>
          {rows.map((row, index) => (
            <div
              key={row.player}
              className="grid grid-cols-[minmax(0,1fr)_3.25rem_3.5rem_2.25rem] items-center gap-2 border-b border-ink-faint/20 px-1 py-2 font-game text-xs"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className={`w-4 shrink-0 tabular-nums ${index === 0 ? 'text-[#d5bafa]' : 'text-ink-faint'}`}>
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span className="truncate text-ink">{row.player}</span>
              </span>
              <span className="text-right font-semibold tabular-nums text-good">{row.bestGap}</span>
              <span className="text-right tabular-nums text-critical">{row.worstGap}</span>
              <span className="text-right tabular-nums text-ink-dim">{row.rounds}</span>
            </div>
          ))}
          <p className="mt-2 font-game text-[9px] text-ink-faint">Gap points: lower is closer.</p>
        </div>
      )}
    </section>
  )
}
