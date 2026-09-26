import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { useGameState } from './data/useGameState'
import IdleScreen from './components/IdleScreen'
import ActiveRound from './components/ActiveRound'
import RevealMoment from './components/RevealMoment'
import Leaderboard from './components/Leaderboard'
import CalibrationCurve from './components/CalibrationCurve'
import ClaimAnnouncer from './components/ClaimAnnouncer'

const CONNECTION_LABEL = { live: 'Live', offline: 'Offline', preview: 'Preview' }
const STAGE_MS = 700

function PreviewKeys() {
  return (
    <p className="pointer-events-none absolute left-4 top-4 z-30 font-game text-[10px] uppercase tracking-[0.2em] text-ink-dim">
      Preview, no hardware. Keys 1 idle, 2 dial, 3 measure, 4 reveal, 0 auto.
    </p>
  )
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
          camera={state.camera}
          beat={state.beat}
        />
      )
    case 'reveal':
      return <RevealMoment result={state.latestResult} />
    case 'idle':
    default:
      return <IdleScreen />
  }
}

// Predicting and performing share a key so the camera element is not remounted
// (a new <img> would drop the MJPEG stream). Idle and reveal are their own beats.
function visualKey(state) {
  if (state.screen === 'reveal') return `reveal:${state.latestResult?.round_id ?? 'open'}`
  if (state.screen === 'predicting' || state.screen === 'performing') {
    const id = state.activeRound?.round_id ?? 'round'
    return state.activeRound?.uses_camera ? `camera:${id}` : `round:${id}`
  }
  return 'idle'
}

function StageCrossfade({ stageKey, children }) {
  const [frame, setFrame] = useState(() => ({ key: stageKey, id: 1, node: children, leaving: null }))

  if (frame.key !== stageKey) {
    setFrame({
      key: stageKey,
      id: frame.id + 1,
      node: children,
      leaving: { id: frame.id, node: frame.node },
    })
  } else if (frame.node !== children) {
    setFrame({ ...frame, node: children })
  }

  const leavingId = frame.leaving?.id ?? 0
  useEffect(() => {
    if (!leavingId) return undefined
    const timer = setTimeout(() => {
      setFrame((prev) => (prev.leaving?.id === leavingId ? { ...prev, leaving: null } : prev))
    }, STAGE_MS)
    return () => clearTimeout(timer)
  }, [leavingId])

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-void">
      {frame.leaving && (
        <div key={frame.leaving.id} className="stage-leave absolute inset-0">
          {frame.leaving.node}
        </div>
      )}
      <div key={frame.id} className="stage-enter absolute inset-0">
        {children}
      </div>
    </div>
  )
}

function Notice({ message, className }) {
  return (
    <p className={`anim-fade-in rounded-md border border-critical/60 bg-surface px-4 py-2 text-center font-game text-sm text-critical ${className}`}>
      {message}
    </p>
  )
}

function CameraShell({ state }) {
  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-void p-8">
      <div className="relative h-[82vh] w-[82vw] overflow-hidden rounded-2xl border border-ink-faint/30 bg-black">
        <Stage state={state} />
      </div>
      {state.preview && <PreviewKeys />}
      {state.notice && <Notice message={state.notice.message} className="absolute inset-x-6 bottom-16 z-30" />}
    </div>
  )
}

function BoothShell({ state }) {
  return (
    <div className="relative flex h-screen flex-col bg-void p-5">
      <div className="void-grid pointer-events-none absolute inset-0 opacity-40" />
      <div className="crt-overlay" />

      <header className="relative z-10 mb-5 flex items-center justify-between px-1">
        <span className="font-display text-lg tracking-widest text-ink">
          THE<span className="text-claim">.</span>TELL
        </span>
        <span className="flex items-center gap-2 font-game text-xs uppercase tracking-[0.3em] text-ink-dim">
          <motion.span
            className={`h-2 w-2 rounded-full ${state.connection === 'offline' ? 'bg-ink-faint' : 'bg-critical'}`}
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 1.4, repeat: Infinity }}
          />
          {CONNECTION_LABEL[state.connection] ?? 'Connecting'}
          {state.preview && <PreviewKeys />}
        </span>
      </header>

      <div className="relative z-10 grid flex-1 grid-cols-[2fr_1fr] gap-5 overflow-hidden">
        <main className="relative overflow-hidden rounded-2xl border border-ink-faint/25 bg-surface/60">
          <div className="h-full">
            <Stage state={state} />
          </div>
          {state.notice && state.screen === 'predicting' && (
            <Notice message={state.notice.message} className="absolute inset-x-6 bottom-6" />
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

export default function App() {
  const state = useGameState()
  const key = visualKey(state)
  const cameraFull = key.startsWith('camera:')
  return (
    <>
      <StageCrossfade stageKey={key}>
        {cameraFull ? <CameraShell state={state} /> : <BoothShell state={state} />}
      </StageCrossfade>
      <ClaimAnnouncer screen={state.screen} liveClaim={state.liveClaim} />
    </>
  )
}
