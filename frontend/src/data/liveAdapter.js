// Turns the Pi's /api/state JSON (pi/ui_server.py) into exactly what the
// components already render. The Pi sends the same shape as the mock
// ({screen, player, activeRound, liveClaim, latestResult, history}); this only
// fills in display details from roundDefs.js and handles rounds without a gap.
import { roundById, roundByNumber } from './roundDefs'

// Fallback display units for the Pi's raw unit codes, if a round isn't in roundDefs.
const UNIT_SUFFIX = { ms: 'ms', mg_rms: ' mg RMS', smile_pct: '% smiling' }

function defFor(key, number) {
  return roundById(key) ?? roundByNumber(number) ?? null
}

function toActiveRound(active) {
  if (!active) return null
  const def = defFor(active.round_id, active.round_type_id)
  return def ? { ...def, round_type_id: active.round_type_id } : { prompt: '', ...active }
}

function failedLabel(r) {
  if (r.false_start) return 'FALSE START'
  if (r.timeout) return 'TIMEOUT'
  return 'NO READING'
}

// A false start / timeout has no measured performance and no gap on the Pi
// (it scores 0). Shown as reality 0 / gap 100 so the reveal reads as a fail;
// such rounds are left out of `history`, like the Pi's own leaderboard does
// for best/worst gap.
export function toUiResult(r) {
  if (!r) return null
  const def = defFor(r.round_key, r.round_type_id)
  const scored = r.gap !== null && r.gap !== undefined
  return {
    ...r,
    round_name: def?.round_name ?? r.round_name,
    claim: Math.round(r.claim ?? 0),
    actual: scored ? Math.round(r.actual ?? 0) : 0,
    actual_raw: scored ? r.actual_raw : failedLabel(r),
    actual_unit: scored ? (def?.actual_unit ?? UNIT_SUFFIX[r.actual_unit] ?? r.actual_unit ?? '') : '',
    gap: scored ? Math.round(r.gap) : 100,
    verdict_text: r.verdict_text ?? '',
  }
}

export function toUiState(s) {
  return {
    ...s,
    screen: s.screen ?? 'idle',
    player: s.player ?? null,
    activeRound: toActiveRound(s.activeRound),
    liveClaim: s.liveClaim ?? null,
    latestResult: toUiResult(s.latestResult),
    history: (s.history ?? []).filter((r) => r.gap !== null && r.gap !== undefined).map(toUiResult),
  }
}
