import { motion } from 'motion/react'
import { GAME_ROUNDS } from '../data/roundDefs'
import NameEntry from './NameEntry'
import logo from '../assets/logo.png'

const MARQUEE_TEXT = GAME_ROUNDS.map((r) => `ROUND ${r.label}: ${r.round_name.toUpperCase()}`).join('   ///   ')

// names: the name-entry state (App), when this session asks players for their name.
export default function IdleScreen({ names, onHelp }) {
  return (
    <div className="relative flex h-full flex-col items-center justify-center overflow-hidden">
      <Glow className="left-[8%] top-[15%] bg-claim" delay={0} />
      <Glow className="right-[10%] top-[55%] bg-reality" delay={2.4} />

      <img
        src={logo}
        alt="Hill's Kitchen logo: a fork and chef's knife crossed under a flame, on a mountain"
        className="anim-fade-scale-in mb-4 h-40 w-40 rounded-2xl shadow-[0_0_60px_-10px_rgba(255,60,30,0.55)]"
        draggable={false}
      />
      <p className="anim-fade-in-up font-game text-data uppercase tracking-[0.5em] text-ink-dim">
        Hill's Kitchen
      </p>

      <h1 className="anim-fade-scale-in mt-4 text-center font-display text-6xl leading-tight text-ink [text-shadow:0_0_24px_var(--color-claim),0_0_60px_rgba(34,229,255,0.35)] md:text-7xl">
        Step up to
        <br />
        the rig
      </h1>

      {names ? (
        <div className="anim-fade-in relative z-10 mt-8 flex w-full justify-center" style={{ animationDelay: '0.3s' }}>
          <NameEntry
            entry={names}
            variant="prompt"
            lead="Call your composure. Your face will fact-check you. Who's first?"
            onHelp={onHelp}
          />
        </div>
      ) : (
        <div
          className="anim-fade-in mt-8 flex items-center gap-3 font-game text-data uppercase tracking-[0.25em] text-ink-dim"
          style={{ animationDelay: '0.4s' }}
        >
          <span>call your composure. your face will fact-check you.</span>
          <motion.span
            className="inline-block h-6 w-3 bg-claim"
            animate={{ opacity: [1, 1, 0, 0] }}
            transition={{ duration: 1, repeat: Infinity, times: [0, 0.5, 0.5, 1] }}
          />
        </div>
      )}

      <div className="absolute bottom-8 w-full overflow-hidden border-y border-ink-faint/40 py-3">
        <motion.div
          className="flex w-max gap-0 whitespace-nowrap font-display text-data tracking-[0.3em] text-ink-dim"
          animate={{ x: ['0%', '-50%'] }}
          transition={{ duration: 26, repeat: Infinity, ease: 'linear' }}
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
