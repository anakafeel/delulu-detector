import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
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

  const accent = isPerforming ? 'var(--color-reality)' : 'var(--color-claim)'
  let placeholder = null
  if (!available) placeholder = 'No camera feed (a face round with the webcam and --ui)'
  else if (failed) placeholder = 'Camera reconnecting...'

  return (
    <div className="absolute inset-0 bg-black">
      <div
        className="relative h-full w-full overflow-hidden"
        style={{
          boxShadow: placeholder ? 'none' : `inset 0 0 0 2px ${accent}`,
        }}
      >
        {placeholder ? (
          <div className="flex h-full items-center justify-center p-6 text-center font-game text-xs uppercase tracking-[0.25em] text-ink-faint">
            {placeholder}
          </div>
        ) : (
          <MjpegImage key={attempt} src={`${API_BASE}/api/camera.mjpg?v=${attempt}`} onError={() => setFailed(true)} />
        )}
        {!placeholder && current?.mode === 'measuring' && (
          <span className="absolute bottom-7 right-2 flex items-center gap-1.5 rounded bg-void/70 px-2 py-0.5 font-game text-[10px] uppercase tracking-[0.3em] text-ink">
            <motion.span
              className="h-1.5 w-1.5 rounded-full bg-critical"
              animate={{ opacity: [1, 0.2, 1] }}
              transition={{ duration: 0.8, repeat: Infinity }}
            />
            Rec
          </span>
        )}
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center">
        <Readout camera={failed ? null : current} />
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

function Readout({ camera }) {
  if (!camera) return <p className="h-6" />
  if (camera.mode === 'measuring' && camera.kind === 'straight') return <StraightReadout camera={camera} />
  if (camera.mode === 'measuring') {
    const composure = camera.composure
    const text = composure === null || composure === undefined ? '--' : Math.round(composure)
    return (
      <p className="h-6 font-game text-sm uppercase tracking-[0.3em] text-ink-dim">
        Composure{' '}
        <span className="text-lg font-bold tabular-nums text-reality">{text}</span>
      </p>
    )
  }
  if (camera.mode === 'preview') {
    return (
      <p className={`h-6 font-game text-sm uppercase tracking-[0.3em] ${camera.face ? 'text-good' : 'text-warning'}`}>
        {camera.face ? 'Face found' : 'No face: move into frame'}
      </p>
    )
  }
  return <p className="h-6 font-game text-sm uppercase tracking-[0.3em] text-ink-faint">Camera starts with the round</p>
}

// Straight Face: a neutral-face baseline, then a running timer until the face changes.
function StraightReadout({ camera }) {
  const cls = 'h-6 font-game text-sm uppercase tracking-[0.3em]'
  if (typeof camera.composure === 'number') {
    return (
      <p className={`${cls} text-ink-dim`}>
        Composure{' '}
        <span className="text-lg font-bold tabular-nums text-reality">{Math.round(camera.composure)}</span>
      </p>
    )
  }
  if (camera.phase === 'changed') {
    const at = camera.changedAtS
    return (
      <p className={`${cls} text-critical`}>
        {camera.trigger === 'smile' ? 'Smile' : 'Expression change'} at{' '}
        <span className="text-lg font-bold tabular-nums">{at === null || at === undefined ? '--' : `${at.toFixed(1)} s`}</span>
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
      <span className={`text-lg font-bold tabular-nums ${hot ? 'text-warning' : 'text-reality'}`}>
        {camera.heldS.toFixed(1)} s
      </span>
    </p>
  )
}
