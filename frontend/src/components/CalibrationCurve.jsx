import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { fetchTigerCurve } from '../data/dataSource'
import { currentOrLastPlayer, playerSeries } from '../data/deriveStats'
import { severityFor, SEVERITY_LEVELS } from '../data/severity'
import { useMeasuredWidth } from '../hooks/useMeasuredWidth'

const H = 240
const PAD = { top: 30, right: 18, bottom: 30, left: 44 }

const GRID_VALUES = [0, 50, 100]

// The one chart the PRD calls out as the technical-execution differentiator:
// "funny toy" -> "measurable effect." No hover/tooltip is possible on this
// passive booth display (see the dataviz skill's interaction.md), so every
// point's value is labeled directly rather than gated behind a tooltip.
// Takes only what it plots (not the whole state) and is memoized, so live dial
// updates don't re-render the chart.
function CalibrationCurve({ player: currentPlayer, history }) {
  const [containerRef, W] = useMeasuredWidth(480)
  const CHART_W = W - PAD.left - PAD.right
  const CHART_H = H - PAD.top - PAD.bottom

  const player = currentOrLastPlayer({ player: currentPlayer, history })
  const local = useMemo(() => playerSeries(history, player), [history, player])
  // Tiger Data when it answers (all sessions, by round number); else this log's rounds in order.
  // Refetched when a new round lands (history length) or the player changes.
  const [tiger, setTiger] = useState(null)
  const rounds = history.length
  useEffect(() => {
    let live = true
    fetchTigerCurve(player).then((curve) => {
      if (live) setTiger(curve && curve.length ? { player, curve } : null)
    })
    return () => {
      live = false
    }
  }, [player, rounds])
  const fromTiger = tiger?.player === player
  const series = fromTiger ? tiger.curve.map((c) => ({ gap: c.avg_gap })) : local

  const points = series.map((r, i) => ({
    x: PAD.left + (series.length === 1 ? CHART_W / 2 : (i / (series.length - 1)) * CHART_W),
    y: PAD.top + CHART_H - (r.gap / 100) * CHART_H,
    gap: r.gap,
    severity: severityFor(r.gap),
  }))

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')

  const pathRef = useRef(null)
  useEffect(() => {
    const el = pathRef.current
    if (!el || !linePath) return
    const length = el.getTotalLength()
    el.style.transition = 'none'
    el.style.strokeDasharray = `${length}`
    el.style.strokeDashoffset = `${length}`
    el.getBoundingClientRect()
    requestAnimationFrame(() => {
      el.style.transition = 'stroke-dashoffset 0.9s ease-out'
      el.style.strokeDashoffset = '0'
    })
  }, [linePath])

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <h3 className="font-display text-data uppercase tracking-[0.15em] text-ink">
          Calibration curve
        </h3>
        {player && (
          <span className="font-game text-meta text-ink-dim">
            {player} · {fromTiger ? 'avg gap by round, all sessions · Tiger Data' : 'gap per round'}
          </span>
        )}
      </div>

      <div ref={containerRef} className="w-full">
      {points.length < 2 ? (
        <p className="font-game text-data text-ink-dim">Play 2 rounds to see your gap shrink (or not).</p>
      ) : (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block">
            {GRID_VALUES.map((v) => {
              const y = PAD.top + CHART_H - (v / 100) * CHART_H
              return (
                <g key={v}>
                  <line
                    x1={PAD.left}
                    x2={W - PAD.right}
                    y1={y}
                    y2={y}
                    stroke="var(--color-surface-2)"
                    strokeWidth={1}
                  />
                  <text
                    x={PAD.left - 6}
                    y={y}
                    textAnchor="end"
                    dominantBaseline="middle"
                    className="fill-ink-dim"
                    fontSize={16}
                    fontFamily="var(--font-game)"
                  >
                    {v}
                  </text>
                </g>
              )
            })}

            <path
              ref={pathRef}
              d={linePath}
              fill="none"
              stroke="var(--color-claim)"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ filter: 'drop-shadow(0 0 6px var(--color-claim))' }}
            />

            {points.map((p, i) => {
              const isLast = i === points.length - 1
              const labelAbove = i % 2 === 0
              return (
                <g key={i}>
                  <circle
                    className="chart-dot"
                    cx={p.x}
                    cy={p.y}
                    r={isLast ? 9 : 6}
                    fill={p.severity.color}
                    stroke="var(--color-surface)"
                    strokeWidth={2}
                    style={{
                      animationDelay: `${0.1 + i * 0.08}s`,
                      filter: isLast ? `drop-shadow(0 0 6px ${p.severity.color})` : undefined,
                    }}
                  />
                  <text
                    x={p.x}
                    y={labelAbove ? p.y - 14 : p.y + 26}
                    textAnchor="middle"
                    fontSize={isLast ? 22 : 17}
                    fontWeight={isLast ? 700 : 400}
                    fontFamily="var(--font-game)"
                    fill={isLast ? p.severity.color : 'var(--color-ink-dim)'}
                  >
                    {p.gap}
                  </text>
                </g>
              )
            })}
          </svg>

          <div className="flex flex-wrap gap-x-3 gap-y-1 px-1">
            {SEVERITY_LEVELS.map((l) => (
              <span key={l.key} className="flex items-center gap-1.5 font-game text-meta text-ink-dim">
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ background: l.color }}
                />
                {l.tag}
              </span>
            ))}
          </div>
        </>
      )}
      </div>
    </div>
  )
}

export default memo(CalibrationCurve)
