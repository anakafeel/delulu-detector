import { motion } from 'motion/react'
import { GAME_ROUNDS } from '../data/roundDefs'
import DeluluCharacter from './DeluluCharacter'


const MARQUEE_TEXT = GAME_ROUNDS.map((r) => `ROUND ${r.label}: ${r.round_name.toUpperCase()}`).join('   ///   ')

export default function IdleScreen() {
  return (
    <div className="relative flex h-full flex-col items-center justify-center overflow-hidden">
      <Glow className="left-[8%] top-[15%] bg-claim" delay={0} />
      <Glow className="right-[10%] top-[55%] bg-reality" delay={2.4} />

      <p className="anim-fade-in-up font-game text-sm uppercase tracking-[0.5em] text-ink-dim">
        The Tell
      </p>

      <h1 className="anim-fade-scale-in mt-4 text-center font-display text-6xl leading-tight text-ink [text-shadow:0_0_24px_var(--color-claim),0_0_60px_rgba(34,229,255,0.35)] md:text-7xl">
        Step up to
        <br />
        the rig
      </h1>

      {/* Delulu Greeter */}
      <div className="mt-8 mb-4">
        <DeluluCharacter 
          tier="validated" 
          speaking={true} 
          waving={true} 
          smiling={true} 
          size={180} 
        />
      </div>

      <div
        className="anim-fade-in mt-8 flex items-center gap-3 font-game text-lg uppercase tracking-[0.3em] text-ink-dim"
        style={{ animationDelay: '0.4s' }}
      >
        <span>call your composure. your face will fact-check you.</span>
        <motion.span
          className="inline-block h-5 w-3 bg-claim"
          animate={{ opacity: [1, 1, 0, 0] }}
          transition={{ duration: 1, repeat: Infinity, times: [0, 0.5, 0.5, 1] }}
        />
      </div>

      <div className="absolute bottom-10 w-full overflow-hidden border-y border-ink-faint/40 py-3">
        <motion.div
          className="flex w-max gap-0 whitespace-nowrap font-display text-sm tracking-[0.35em] text-ink-faint"
          animate={{ x: ['0%', '-50%'] }}
          transition={{ duration: 22, repeat: Infinity, ease: 'linear' }}
        >
          <span className="px-4">{MARQUEE_TEXT}</span>
          <span className="px-4">{MARQUEE_TEXT}</span>
        </motion.div>
      </div>
    </div>
  )
}

function Glow({ className, delay }) {
  return (
    <motion.div
      className={`absolute h-72 w-72 rounded-full opacity-20 blur-[100px] ${className}`}
      animate={{ opacity: [0.12, 0.28, 0.12], scale: [1, 1.15, 1] }}
      transition={{ duration: 6, repeat: Infinity, delay, ease: 'easeInOut' }}
    />
  )
}
