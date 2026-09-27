import { useEffect, useState } from 'react'
import { API_BASE } from '../data/dataSource'

const RETRY_MS = 3000

// The face rounds (Poker Face, Straight Face): the webcam, as MJPEG from the Pi
// (GET /api/camera.mjpg). The Pi already mirrors the frames like a selfie and
// draws the face / smile boxes and the live numbers (smile %, or the seconds
// held, the level bar and the "expression change" marker), so no CSS flip here
// (it would mirror the text).
// `camera` is state.camera: {available, mode: 'measuring' | 'preview' | null,
// kind: 'poker' | 'straight'} from the full state, plus the fast numbers
// {face, smiling, smilePct} / {phase, heldS, changedAtS, trigger, level}
// merged in from the small SSE `live` events (dataSource.js).
export default function CameraFeed({ camera, isPerforming }) {
  const [attempt, setAttempt] = useState(0)
  const [failed, setFailed] = useState(false)
  const available = camera?.available === true
  const current = available ? camera : null

  // A dropped stream (Pi restarted, network blip): try again after a moment.
  useEffect(() => {
    if (!failed) return undefined
    const t = setTimeout(() => {
      setFailed(false)
      setAttempt((a) => a + 1)
    }, RETRY_MS)
    return () => clearTimeout(t)
  }, [failed])

  let placeholder = null
  if (!available) placeholder = 'No camera feed (a face round with the webcam and --ui)'
  else if (failed) placeholder = 'Camera reconnecting...'

  return (
    <div className="absolute inset-0 bg-black">
      {/* The phase frame (ActiveRound) is the border now: cyan claim, purple live read. */}
      <div className="relative h-full w-full overflow-hidden">
        {current?.previewFrame ? (
          <PreviewFrame />
        ) : placeholder ? (
          <div className="flex h-full items-center justify-center p-6 text-center font-game text-data uppercase tracking-[0.2em] text-ink-dim">
            {placeholder}
          </div>
        ) : (
          <MjpegImage key={attempt} src={`${API_BASE}/api/camera.mjpg?v=${attempt}`} onError={() => setFailed(true)} />
        )}
      </div>
      <div key={readoutKey(current, isPerforming)} className="pointer-events-none absolute inset-x-0 bottom-5 flex justify-center anim-fade-in">
        <Readout camera={failed ? null : current} isPerforming={isPerforming} />
      </div>
    </div>
  )
}

// Chrome keeps an MJPEG request open after its <img> is removed; clearing src
// on unmount closes it, so the Pi stops streaming (and previewing) at once.
function MjpegImage({ src, onError }) {
  const [img, setImg] = useState(null)
  useEffect(
    () => () => {
      if (img) img.src = ''
    },
    [img],
  )
  return (
    <img
      ref={setImg}
      src={src}
      onError={onError}
      alt="Live camera"
      className="h-full w-full object-contain"
      draggable={false}
    />
  )
}

function PreviewFrame() {
  return (
    <div className="relative h-full w-full bg-[radial-gradient(circle_at_50%_42%,#3a3428_0%,#12110f_62%)]">
      <div className="absolute left-1/2 top-[38%] h-[46%] w-[34%] -translate-x-1/2 rounded-[40%] border-2 border-reality/80" />
    </div>
  )
}

function readoutKey(camera, isPerforming) {
  if (!camera) return 'none'
  if (camera.mode === 'scoring') return 'scoring'
  if (isPerforming && camera.mode !== 'measuring' && camera.mode !== 'preview') return 'scoring'
  return camera.mode || 'camera'
}

function Readout({ camera, isPerforming }) {
  if (!camera) return <p className="h-10" />
  if (camera.mode === 'scoring') return <LoadingReadout label="Reading the face" detail="Scoring" />
  // Claim locked, window already closed, reveal not up yet: don't fall through to an empty line.
  if (isPerforming && camera.mode !== 'measuring' && camera.mode !== 'preview') {
    return <LoadingReadout label="Scoring" />
  }
  if (camera.mode === 'measuring' && camera.kind === 'straight') return <StraightReadout camera={camera} />
  // Poker Face: the live composure is the big ring (ActiveRound); here, the time left.
  if (camera.mode === 'measuring') return <WindowLeft remaining={camera.remainingS} total={camera.windowS} />
  if (camera.mode === 'preview') {
    return (
      <p className={`rounded-lg bg-void/80 px-4 py-1 font-game text-data uppercase tracking-[0.2em] ${camera.face ? 'text-good' : 'text-warning'}`}>
        {camera.face ? 'Face found' : 'No face: move into frame'}
      </p>
    )
  }
  return <p className="rounded-lg bg-void/80 px-4 py-1 font-game text-data uppercase tracking-[0.2em] text-ink-dim">Camera starts with the round</p>
}

function LoadingReadout({ label, detail }) {
  return (
    <p className="flex items-center gap-3 rounded-lg bg-void/80 px-4 py-1 font-game text-data uppercase tracking-[0.2em] text-ink-dim">
      <span className="quiet-pulse inline-block h-3 w-3 rounded-full bg-reality" />
      {label}
      {detail ? <span className="text-ink-faint">· {detail}</span> : null}
    </p>
  )
}

// Seconds left in the measured window, as a number and a draining bar.
function WindowLeft({ remaining, total }) {
  if (typeof remaining !== 'number') return <LoadingReadout label="Reading your face" />
  const frac = total > 0 ? Math.max(0, Math.min(1, remaining / total)) : 0
  return (
    <div className="flex w-[min(40rem,80%)] items-center gap-4 rounded-lg bg-void/80 px-4 py-2">
      <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full bg-reality" style={{ width: `${frac * 100}%`, transition: 'width 250ms linear' }} />
      </div>
      <span className="font-game text-data font-bold tabular-nums text-ink">{remaining.toFixed(1)} s</span>
    </div>
  )
}

// Straight Face: a neutral-face baseline, then a running timer until the face changes.
function StraightReadout({ camera }) {
  const cls = 'rounded-lg bg-void/80 px-4 py-1 font-game text-data uppercase tracking-[0.2em]'
  if (typeof camera.composure === 'number') {
    return (
      <p className={`${cls} text-ink-dim`}>
        Composure{' '}
        <span className="font-bold tabular-nums text-reality">{Math.round(camera.composure)}</span>
      </p>
    )
  }
  if (camera.phase === 'changed') {
    const at = camera.changedAtS
    return (
      <p className={`${cls} text-critical`}>
        {camera.trigger === 'smile' ? 'Smile' : 'Expression change'} at{' '}
        <span className="font-bold tabular-nums">{at === null || at === undefined ? '--' : `${at.toFixed(1)} s`}</span>
      </p>
    )
  }
  if (camera.phase === 'baseline' || camera.heldS === null || camera.heldS === undefined) {
    return <p className={`${cls} text-ink-dim`}>Reading your neutral face...</p>
  }
  const hot = typeof camera.level === 'number' && camera.level >= 0.8
  return (
    <p className={`${cls} text-ink-dim`}>
      Straight face{' '}
      <span className={`font-bold tabular-nums ${hot ? 'text-warning' : 'text-reality'}`}>
        {camera.heldS.toFixed(1)} s
      </span>
    </p>
  )
}
