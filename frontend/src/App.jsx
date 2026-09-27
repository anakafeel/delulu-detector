import { useCallback, useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { useGameState } from './data/useGameState'
import IdleScreen from './components/IdleScreen'
import ActiveRound from './components/ActiveRound'
import RevealMoment from './components/RevealMoment'
import Leaderboard from './components/Leaderboard'
import CalibrationCurve from './components/CalibrationCurve'
import ClaimAnnouncer from './components/ClaimAnnouncer'
import HowItWorks from './components/HowItWorks'
import { useNameEntry } from './hooks/useNameEntry'

const CONNECTION_LABEL = { live: 'Live', offline: 'Offline', preview: 'Preview' }
const STAGE_MS = 700

function PreviewKeys() {
  return (
    <p className="pointer-events-none fixed bottom-1 left-4 z-30 font-game text-meta uppercase tracking-[0.15em] text-ink-dim">
      Preview, no hardware. Keys 1 idle, 2 dial, 3 measure, 4 reveal, 0 auto.
    </p>
  )
}

function Stage({ state, names, onHelp }) {
  switch (state.screen) {
    case 'predicting':
    case 'performing':
      return (
        <ActiveRound
          screen={state.screen}
          activeRound={state.activeRound}
          player={state.player}
          playerNamed={state.playerNamed}
          nameEntry={state.nameEntry}
          liveClaim={state.liveClaim}
          camera={state.camera}
          beat={state.beat}
          notice={state.notice}
          names={names}
          onHelp={onHelp}
        />
      )
    case 'reveal':
      return <RevealMoment result={state.latestResult} history={state.history} />
    case 'idle':
    default:
      return <IdleScreen names={state.nameEntry ? names : null} onHelp={onHelp} />
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

// Problems only (sensor error, question unavailable). The live question is an "info"
// notice and is drawn as the headline question card inside the round (ActiveRound).
function Notice({ notice, className }) {
  if (!notice || notice.level === 'info') return null
  return (
    <p className={`anim-fade-in rounded-xl border-2 border-critical bg-void/95 px-6 py-3 text-center font-game text-data text-critical ${className}`}>
      {notice.message}
    </p>
  )
}

function CameraShell({ state, names, onHelp }) {
  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-void p-8">
      <div className="relative h-[82vh] w-[82vw] overflow-hidden rounded-2xl bg-black">
        <Stage state={state} names={names} onHelp={onHelp} />
      </div>
      {state.preview && <PreviewKeys />}
      <Notice notice={state.notice} className="absolute inset-x-10 top-1/2 z-30 -translate-y-1/2" />
    </div>
  )
}

function BoothShell({ state, names, onHelp }) {
  return (
    <div className="relative flex h-screen flex-col bg-void p-5">
      <div className="void-grid pointer-events-none absolute inset-0 opacity-40" />
      <div className="crt-overlay" />

      <header className="relative z-10 mb-5 flex items-center justify-between px-1">
        <span className="font-display text-title tracking-widest text-ink">
          THE<span className="text-claim">.</span>TELL
        </span>
        <button
          type="button"
          onClick={onHelp}
          className="rounded-full border-2 border-ink-faint px-4 py-1 font-game text-meta text-ink-dim"
        >
          <kbd className="font-bold text-ink">?</kbd> How it's scored
        </button>
        <span className="flex items-center gap-2 font-game text-meta uppercase tracking-[0.2em] text-ink-dim">
          <motion.span
            className={`h-3 w-3 rounded-full ${state.connection === 'offline' ? 'bg-ink-faint' : 'bg-critical'}`}
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
            <Stage state={state} names={names} onHelp={onHelp} />
          </div>
          {state.screen === 'predicting' && <Notice notice={state.notice} className="absolute inset-x-6 bottom-6" />}
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

// "How this is calculated": ? toggles it (the name field forwards its ?), Esc closes it,
// and it closes by itself when a round starts, so it never covers the live read.
function useExplainer(screen) {
  const [open, setOpen] = useState(false)
  const toggle = useCallback(() => setOpen((o) => !o), [])
  const [shownFor, setShownFor] = useState(screen)
  if (shownFor !== screen) {
    setShownFor(screen)
    if (open && screen === 'performing') setOpen(false)
  }
  useEffect(() => {
    const onKey = (event) => {
      if (event.target?.tagName === 'INPUT') return          // the name field handles its own keys
      if (event.key === '?') toggle()
      else if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle])
  return { open, toggle, close: () => setOpen(false) }
}

export default function App() {
  const state = useGameState()
  const names = useNameEntry()
  const help = useExplainer(state.screen)
  const key = visualKey(state)
  const cameraFull = key.startsWith('camera:')
  return (
    <>
      <StageCrossfade stageKey={key}>
        {cameraFull ? (
          <CameraShell state={state} names={names} onHelp={help.toggle} />
        ) : (
          <BoothShell state={state} names={names} onHelp={help.toggle} />
        )}
      </StageCrossfade>
      {help.open && <HowItWorks onClose={help.close} />}
      <ClaimAnnouncer screen={state.screen} liveClaim={state.liveClaim} />
    </>
  )
}
