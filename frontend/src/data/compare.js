// "How you compare", from the rounds actually logged (data/sessions.db, reset
// before the demo so it holds tonight's plays only). No percentile, no implied
// population: plain counts over the real sample, which is said out loud.
// Only the same round type is compared (a Reflex gap and a Poker Face gap are
// different measurements).
export const SMALL_SAMPLE = 10

export function compareToTonight(result, history) {
  if (!result || result.gap == null || !result.round_key) return null
  const others = history.filter(
    (r) => r.round_key === result.round_key && r.round_id !== result.round_id && r.gap != null,
  )
  const gap = result.gap_exact ?? result.gap
  const gapOf = (r) => r.gap_exact ?? r.gap
  const closer = others.filter((r) => gapOf(r) > gap).length
  const tied = others.filter((r) => gapOf(r) === gap).length
  const best = others.length ? Math.min(...others.map(gapOf)) : null
  return {
    others: others.length,
    total: others.length + 1,
    closer,
    tied,
    best,
    isBest: best === null || gap <= best,
    small: others.length + 1 < SMALL_SAMPLE,
  }
}
