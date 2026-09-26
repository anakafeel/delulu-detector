import { motion, useReducedMotion } from 'motion/react'
import { ROUND_DEFS } from '../data/roundDefs'

const MARQUEE_TEXT = ROUND_DEFS.map((round) => round.round_name.toUpperCase()).join('   ///   ')

export default function IdleScreen({ history = [] }) {
  const reduceMotion = useReducedMotion()
  const gaps = history
    .filter((round) => round.gap !== null && round.gap !== undefined)
    .map((round) => Number(round.gap))
    .filter(Number.isFinite)
  const bestGap = gaps.length ? Math.min(...gaps) : null
  const averageGap = gaps.length
    ? Math.round(gaps.reduce((total, gap) => total + gap, 0) / gaps.length)
    : null

  return (
    <div className="relative grid h-full grid-rows-[auto_1fr_auto] px-6 py-5 sm:px-9 sm:py-7 lg:px-11 lg:py-6">
      <div className="flex items-center justify-between border-b border-ink-faint/35 pb-3 font-game text-[11px] text-ink-dim">
        <span className="flex items-center gap-2 font-display text-xs text-reality"><span className="arcade-led" />FREE PLAY</span>
        <span>Claim <span className="text-claim">/</span> reality</span>
      </div>

      <div className="grid items-center gap-7 py-6 md:grid-cols-[1fr_0.72fr] lg:gap-10 lg:py-3">
        <section className="relative z-10">
          <p className="mb-4 flex items-center gap-2 font-game text-xs font-semibold text-claim"><span className="arcade-led arcade-led-blue" />CONFIDENCE, PUT TO THE TEST</p>
          <h1 className="font-display text-4xl uppercase leading-[1.08] text-ink sm:text-5xl lg:text-5xl 2xl:text-6xl">
            How sure
            <br />
            are <span className="text-reality">you?</span>
          </h1>
          <p className="mt-5 max-w-[30rem] font-sans text-base leading-7 text-ink-dim sm:text-lg">
            Set a confidence claim, play the round, and compare it with the result.
          </p>

          <div className="mt-8 border-t border-ink-faint/35 pt-4">
            <p className="mb-3 font-game text-[10px] font-semibold text-ink-faint">THIS SESSION</p>
            <div className="grid grid-cols-3 gap-3 sm:gap-5">
              <Readout label="Scored rounds" value={gaps.length} />
              <Readout label="Best gap" value={bestGap === null ? '—' : bestGap} suffix={bestGap === null ? '' : ' pts'} />
              <Readout label="Average gap" value={averageGap === null ? '—' : averageGap} suffix={averageGap === null ? '' : ' pts'} />
            </div>
          </div>
        </section>

        <aside className="narrator-stage relative min-h-[300px] border-4 border-[#334967] sm:min-h-[340px]" aria-label="Narrator stage">
          <span className="absolute left-4 top-4 font-display text-[10px] font-semibold text-[#334258]">NARRATOR <span className="font-game font-normal">// VOICE REVEAL</span></span>
          {/* Reserved for the animated narrator character. */}
        </aside>
      </div>

      <section className="border-t border-ink-faint/35 pt-4" aria-label="Round format">
        <div className="arcade-readouts grid grid-cols-3 gap-3">
          <DemoFact value="0-100" label="confidence scale" />
          <DemoFact value="5 sec" label="steady-hands hold" />
          <DemoFact value="500" label="samples per hold" />
        </div>
        <div className="mt-4 overflow-hidden border-y border-claim/25 py-2" role="img" aria-label={`Available rounds: ${MARQUEE_TEXT}`}>
          <motion.div
            className="flex w-max whitespace-nowrap font-display text-[10px] text-ink-dim"
            animate={reduceMotion ? undefined : { x: ['0%', '-50%'] }}
            transition={reduceMotion ? undefined : { duration: 26, repeat: Infinity, ease: 'linear' }}
            aria-hidden="true"
          >
            <span className="px-4"><span className="text-reality">FREE PLAY</span> <span className="text-claim">///</span> {MARQUEE_TEXT}</span>
            <span className="px-4"><span className="text-reality">FREE PLAY</span> <span className="text-claim">///</span> {MARQUEE_TEXT}</span>
          </motion.div>
        </div>
      </section>
    </div>
  )
}

function Readout({ label, value, suffix = '' }) {
  return (
    <div className="min-w-0">
      <div className="font-display text-xl tabular-nums text-ink sm:text-2xl">
        {value}<span className="font-game text-[10px] font-normal text-ink-faint">{suffix}</span>
      </div>
      <div className="mt-1 font-game text-[9px] leading-4 text-ink-dim sm:text-[10px]">{label}</div>
    </div>
  )
}

function DemoFact({ value, label }) {
  return (
    <div className="border-l border-ink-faint/50 pl-3">
      <div className="font-display text-sm tabular-nums text-ink sm:text-base">{value}</div>
      <div className="mt-1 font-game text-[9px] leading-4 text-ink-dim sm:text-[10px]">{label}</div>
    </div>
  )
}
