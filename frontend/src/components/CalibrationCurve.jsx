import { useEffect, useRef } from 'react'
import { currentOrLastPlayer, playerSeries } from '../data/deriveStats'
import { severityFor, SEVERITY_LEVELS } from '../data/severity'
import { useMeasuredWidth } from '../hooks/useMeasuredWidth'

const H = 170
const PAD = { top: 18, right: 14, bottom: 24, left: 30 }

const GRID_VALUES = [0, 50, 100]

// The one chart the PRD calls out as the technical-execution differentiator:
// "funny toy" -> "measurable effect." No hover/tooltip is possible on this
// passive booth display (see the dataviz skill's interaction.md), so every
// point's value is labeled directly rather than gated behind a tooltip.
export default function CalibrationCurve({ state }) {
  const [containerRef, W] = useMeasuredWidth(480)
  const CHART_W = W - PAD.left - PAD.right
  const CHART_H = H - PAD.top - PAD.bottom

  const player = currentOrLastPlayer(state)
  const series = playerSeries(state.history, player)

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
        <h3 className="font-display text-xs uppercase tracking-[0.3em] text-ink-dim">
          Calibration Curve
        </h3>
        {player && <span className="font-game text-xs text-ink-faint">{player}</span>}
      </div>

      <div ref={containerRef} className="w-full">
      {points.length < 2 ? (
        <p className="font-game text-sm text-ink-faint">Needs at least 2 rounds to plot.</p>
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
                    className="fill-ink-faint"
                    fontSize={8}
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
                    r={isLast ? 7 : 5}
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
                    y={labelAbove ? p.y - 10 : p.y + 16}
                    textAnchor="middle"
                    fontSize={isLast ? 10 : 8}
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
              <span key={l.key} className="flex items-center gap-1 font-game text-[0.6rem] text-ink-faint">
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full"
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
