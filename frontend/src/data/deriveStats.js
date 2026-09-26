// Pure helpers that turn the flat `history` array (list of round results)
// into what the leaderboard and calibration curve need to render. No fetching,
// no state — easy to unit test later if there's time.

export function leaderboardRows(history) {
  const byPlayer = new Map()
  for (const r of history) {
    const key = r.player ?? 'Unknown'
    if (!byPlayer.has(key)) {
      byPlayer.set(key, { player: key, gaps: [], rounds: 0 })
    }
    const entry = byPlayer.get(key)
    entry.gaps.push(r.gap)
    entry.rounds += 1
  }

  return Array.from(byPlayer.values())
    .map((entry) => ({
      player: entry.player,
      bestGap: Math.min(...entry.gaps),
      worstGap: Math.max(...entry.gaps),
      rounds: entry.rounds,
    }))
    .sort((a, b) => a.bestGap - b.bestGap)
}

// Rounds played by the given player, in play order — the series behind the
// calibration curve for whoever is currently at the rig (or most recently was).
export function playerSeries(history, playerName) {
  if (!playerName) return []
  return history.filter((r) => r.player === playerName)
}

export function currentOrLastPlayer(state) {
  if (state.player) return state.player
  const last = state.history[state.history.length - 1]
  return last?.player ?? null
}
