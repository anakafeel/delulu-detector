import { motion } from 'motion/react'
import { useGameState } from './data/useGameState'
import IdleScreen from './components/IdleScreen'
import ActiveRound from './components/ActiveRound'
import RevealMoment from './components/RevealMoment'
import Leaderboard from './components/Leaderboard'
import CalibrationCurve from './components/CalibrationCurve'
import ClaimAnnouncer from './components/ClaimAnnouncer'

const CONNECTION_LABEL = { live: 'Live', mock: 'Mock', offline: 'Offline' }

function Stage({ state }) {
  switch (state.screen) {
    case 'predicting':
    case 'performing':
      return (
        <ActiveRound
          screen={state.screen}
          activeRound={state.activeRound}
          player={state.player}
          liveClaim={state.liveClaim}
        />
      )
    case 'reveal':
      return <RevealMoment result={state.latestResult} />
    case 'idle':
    default:
      return <IdleScreen />
  }
}

export default function App() {
  const state = useGameState()

  return (
    <div className="relative flex h-screen flex-col bg-void p-5">
      <div className="void-grid pointer-events-none absolute inset-0 opacity-40" />
      <div className="crt-overlay" />

      <header className="relative z-10 mb-5 flex items-center justify-between px-1">
        <span className="font-display text-lg tracking-widest text-ink">
          DELULU<span className="text-claim">.</span>DETECTOR
        </span>
        <span className="flex items-center gap-2 font-game text-xs uppercase tracking-[0.3em] text-ink-dim">
          <motion.span
            className={`h-2 w-2 rounded-full ${state.connection === 'offline' ? 'bg-ink-faint' : 'bg-critical'}`}
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 1.4, repeat: Infinity }}
          />
          {CONNECTION_LABEL[state.connection] ?? 'Connecting'}
        </span>
      </header>

      <div className="relative z-10 grid flex-1 grid-cols-[2fr_1fr] gap-5 overflow-hidden">
        <main className="relative overflow-hidden rounded-2xl border border-ink-faint/25 bg-surface/60">
          <div
            key={state.screen === 'reveal' ? `reveal-${state.latestResult?.round_id}` : state.screen}
            className="anim-fade-scale-in h-full"
          >
            <Stage state={state} />
          </div>
          <ClaimAnnouncer screen={state.screen} liveClaim={state.liveClaim} />
          {state.notice && state.screen === 'predicting' && (
            <p className="anim-fade-in absolute inset-x-6 bottom-6 rounded-md border border-critical/60 bg-surface px-4 py-2 text-center font-game text-sm text-critical">
              {state.notice.message}
            </p>
          )}
        </main>

        <aside className="flex flex-col gap-5 overflow-y-auto rounded-2xl border border-ink-faint/25 bg-surface/60 p-5">
          <Leaderboard history={state.history} />
          <div className="border-t border-ink-faint/20 pt-5">
            <CalibrationCurve player={state.player} history={state.history} />
          </div>
        </aside>
      </div>
    </div>
  )
}
