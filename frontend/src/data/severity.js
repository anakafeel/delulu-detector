// Single source of truth for "how bad is this gap" — feeds verdict copy,
// the reveal moment's color/shake intensity, the leaderboard, and the
// calibration curve's dot colors. Thresholds match the status color scale
// validated in index.css (good/warning/serious/critical). The cut-offs match
// the Pi's verdict tiers (pi/config.py GAP_TIERS: validated <= 10, mild <= 25,
// spicy <= 45, else delulu) so the badge agrees with the narrator.
export const SEVERITY_LEVELS = [
  { max: 10, key: 'good', color: 'var(--color-good)', tag: 'Sharp' },
  { max: 25, key: 'warning', color: 'var(--color-warning)', tag: 'Slipping' },
  { max: 45, key: 'serious', color: 'var(--color-serious)', tag: 'Rough' },
  { max: 101, key: 'critical', color: 'var(--color-critical)', tag: 'Delulu' },
]

export function severityFor(gap) {
  return SEVERITY_LEVELS.find((l) => gap <= l.max) ?? SEVERITY_LEVELS[SEVERITY_LEVELS.length - 1]
}
