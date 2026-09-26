import { useState } from 'react'
import { useGameState } from './data/useGameState'
import IdleScreen from './components/IdleScreen'
import ActiveRound from './components/ActiveRound'
import RevealMoment from './components/RevealMoment'
import Leaderboard from './components/Leaderboard'
import CalibrationCurve from './components/CalibrationCurve'

const CONNECTION = {
  live: { label: 'Live', color: 'bg-good' },
  mock: { label: 'Demo', color: 'bg-warning' },
  offline: { label: 'Offline', color: 'bg-ink-faint' },
}

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
      return <IdleScreen history={state.history} />
  }
}

export default function App() {
  const state = useGameState()
  const [showLeaderboard, setShowLeaderboard] = useState(true)
  const [showCalibration, setShowCalibration] = useState(true)
  const connection = CONNECTION[state.connection] ?? { label: 'Connecting', color: 'bg-warning' }

  return (
    <div className="app-shell relative flex min-h-screen flex-col bg-void px-4 py-4 text-ink lg:h-screen lg:min-h-0 lg:overflow-hidden lg:px-5">
      <header className="relative z-10 mb-4 flex shrink-0 items-center justify-between border-b border-ink-faint/35 pb-3">
        <span className="font-display text-base text-ink sm:text-lg">
          Delulu<span className="text-claim">.</span>Detector
        </span>
        <span className="flex items-center gap-2 font-game text-xs text-ink-dim" role="status">
          <span className={`h-2 w-2 ${connection.color}`} />
          {connection.label}
        </span>
      </header>

      <div className="relative z-10 grid flex-1 grid-cols-1 gap-4 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(310px,370px)]">
        <main className="game-screen relative min-h-[620px] overflow-hidden border border-ink-faint/35 bg-surface sm:min-h-[560px] lg:min-h-0">
          <div
            key={state.screen === 'reveal' ? `reveal-${state.latestResult?.round_id}` : state.screen}
            className="h-full"
          >
            <Stage state={state} />
          </div>
          {state.notice && state.screen === 'predicting' && (
            <p className="anim-fade-in absolute inset-x-4 bottom-4 border border-critical/60 bg-surface px-4 py-2 text-center font-game text-sm text-critical sm:inset-x-6 sm:bottom-6">
              {state.notice.message}
            </p>
          )}
        </main>

        <aside aria-label="Session data panels" className="flex min-h-[180px] flex-col overflow-y-auto border border-ink-faint/35 bg-surface px-4 lg:min-h-0">
          <div className="flex items-center justify-between border-b border-ink-faint/35 py-3">
            <span className="font-game text-xs font-semibold text-ink">Session data</span>
            <span className="font-game text-[10px] tabular-nums text-ink-faint">{state.history.length} scored</span>
          </div>

          {(!showLeaderboard || !showCalibration) && (
            <div className="flex flex-wrap gap-2 border-b border-ink-faint/25 py-3" role="group" aria-label="Restore hidden widgets">
              {!showLeaderboard && (
                <button
                  type="button"
                  onClick={() => setShowLeaderboard(true)}
                  className="widget-restore"
                >
                  <span aria-hidden="true">+</span> Leaderboard
                </button>
              )}
              {!showCalibration && (
                <button
                  type="button"
                  onClick={() => setShowCalibration(true)}
                  className="widget-restore"
                >
                  <span aria-hidden="true">+</span> Calibration curve
                </button>
              )}
            </div>
          )}

          {showLeaderboard && (
            <div className="border-b border-ink-faint/25 py-4">
              <Leaderboard history={state.history} onClose={() => setShowLeaderboard(false)} />
            </div>
          )}
          {showCalibration && (
            <div className="py-4">
              <CalibrationCurve state={state} onClose={() => setShowCalibration(false)} />
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
