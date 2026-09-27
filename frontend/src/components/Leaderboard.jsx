import { memo, useEffect, useMemo, useState } from 'react'
import { leaderboardRows } from '../data/deriveStats'
import { API_BASE, fetchTigerLeaderboard } from '../data/dataSource'

// memo: the live dial updates the app state up to 10 times a second; history
// keeps the same reference then (dataSource.js), so the leaderboard is skipped.
// photos: players with an opt-in photo from tonight (state.photos); their names are clickable.
function Leaderboard({ history, photos = [] }) {
  const [open, setOpen] = useState(null)
  const local = useMemo(() => leaderboardRows(history), [history])
  // All-time from Tiger Data (every logged session, ranked by average gap) when it answers;
  // otherwise this machine's log. Refetched whenever a new round lands.
  const [tiger, setTiger] = useState(null)
  const rounds = history.length
  useEffect(() => {
    let live = true
    fetchTigerLeaderboard().then((board) => {
      if (live) setTiger(board && board.length ? board : null)
    })
    return () => {
      live = false
    }
  }, [rounds])
  const rows = tiger
    ? tiger.map((r) => ({
        player: r.player,
        bestGap: Math.round(r.best_gap),
        worstGap: Math.round(r.worst_gap),
        rounds: r.rounds,
      }))
    : local
  const totalRounds = tiger ? tiger.reduce((n, r) => n + r.rounds, 0) : rounds

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h3 className="font-display text-data uppercase tracking-[0.15em] text-ink">
          Leaderboard
        </h3>
        <span className="font-game text-meta text-ink-dim">
          {totalRounds} rounds played{tiger ? ' · all-time, by avg gap · Tiger Data' : ''}
        </span>
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
              {photos.includes(row.player) ? (
                <button
                  type="button"
                  onClick={() => setOpen(row.player)}
                  className="truncate text-left text-ink underline decoration-claim decoration-2 underline-offset-4"
                  title="See their face mid-question"
                >
                  {row.player} <span aria-hidden="true">📸</span>
                </button>
              ) : (
                <span className="truncate text-ink">{row.player}</span>
              )}
              <span className="text-right font-bold tabular-nums text-good">{row.bestGap}</span>
              <span className="text-right font-bold tabular-nums text-critical">
                {row.worstGap}
              </span>
              <span className="text-right tabular-nums text-ink-dim">{row.rounds}</span>
            </div>
          ))}
        </div>
      )}
      {open && <PhotoModal player={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

// The opt-in photo, served from the game's memory (GET /api/photo). Click or Esc closes it.
function PhotoModal({ player, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div
      className="anim-fade-in fixed inset-0 z-[60] flex items-center justify-center bg-void/85 p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`${player} mid-question`}
      onClick={onClose}
    >
      <figure className="flex flex-col items-center gap-3 rounded-2xl border border-ink-faint/60 bg-surface p-5">
        <img
          src={`${API_BASE}/api/photo?player=${encodeURIComponent(player)}`}
          alt={`${player}, 3 seconds into the interview question`}
          className="max-h-[70vh] max-w-[80vw] rounded-xl"
        />
        <figcaption className="font-display text-title text-ink">{player}, mid-question</figcaption>
        <p className="font-game text-meta text-ink-dim">Opt-in photo, on this laptop only. Click or Esc to close.</p>
      </figure>
    </div>
  )
}

export default memo(Leaderboard)
