import { toUiState } from './liveAdapter'

// Frontend-only stand-in for the Python game. No Arduino, no camera, no API.
// Turn it on with `npm run dev:preview`, or open any build with ?preview=1.
// Keys 1–4 pin a screen. Key 0 resumes the automatic walk.
//
// Beats are long enough to read from the booth: idle 4s, dial 6s (the claim
// eases, it does not step), measuring 7s, a 1.5s scoring beat still on the
// performing screen, then the reveal for 7s.

const IDLE_MS = 4000
const DIAL_MS = 6000
const MEASURE_MS = 7000
const SCORING_MS = 1500
const REVEAL_MS = 7000
const TICK_MS = 100

const HISTORY = [
  row('poker_face', 5, 1, 'Saim', 69, 36, 33, 'Claimed 69, held a 36.'),
  row('poker_face', 5, 2, 'Saim', 20, 93, 73, 'Claimed 20, reality 93.'),
  row('straight_face', 6, 3, 'Saim', 20, 15, 5, 'Claim 20, reality 15.'),
]

const SCENES = [
  { screen: 'idle', ms: IDLE_MS },
  { screen: 'predicting', round: 'poker_face', type: 5, ms: DIAL_MS, dialFrom: 8, dialTo: 72 },
  {
    screen: 'performing',
    round: 'poker_face',
    type: 5,
    ms: MEASURE_MS,
    scoringMs: SCORING_MS,
    claim: 72,
    from: 70,
    to: 36,
  },
  { screen: 'reveal', round: 'poker_face', type: 5, ms: REVEAL_MS, claim: 72, actual: 36, gap: 36 },
  { screen: 'predicting', round: 'straight_face', type: 6, ms: DIAL_MS, dialFrom: 6, dialTo: 40 },
  {
    screen: 'performing',
    round: 'straight_face',
    type: 6,
    ms: MEASURE_MS,
    scoringMs: SCORING_MS,
    claim: 40,
    from: 55,
    to: 22,
  },
  { screen: 'reveal', round: 'straight_face', type: 6, ms: REVEAL_MS, claim: 40, actual: 22, gap: 18 },
  { screen: 'predicting', round: 'reflex', type: 1, ms: DIAL_MS, dialFrom: 30, dialTo: 88 },
  { screen: 'performing', round: 'reflex', type: 1, ms: MEASURE_MS, scoringMs: SCORING_MS, claim: 88 },
  { screen: 'reveal', round: 'reflex', type: 1, ms: REVEAL_MS, claim: 88, actual: 310, gap: 42, unit: 'ms' },
]

const KEY_TO_SCENE = { 1: 0, 2: 1, 3: 2, 4: 3 }

// The name typed on the preview's Poker Face screens (Straight Face and Reflex have no name step).
let previewPlayer = null
let previewEmit = null
export function setPreviewPlayer(name) {
  const clean = String(name ?? '').replace(/\s+/g, ' ').trim().slice(0, 16)
  if (!clean) return Promise.reject(new Error('empty name'))
  previewPlayer = clean
  previewEmit?.()
  return Promise.resolve(clean)
}

export function previewEnabled() {
  const flag = import.meta.env.VITE_UI_PREVIEW
  if (import.meta.env.MODE === 'preview' || flag === '1' || flag === 'true') return true
  if (typeof window === 'undefined') return false
  return new URLSearchParams(window.location.search).get('preview') === '1'
}

export function subscribePreview(callback) {
  let closed = false
  let index = 0
  let pinned = false
  let step = 0
  let timer = null

  const emit = () => {
    if (closed) return
    const scene = SCENES[index]
    const sample = sampleScene(scene, step)
    const raw = sceneState(scene, sample)
    callback({
      ...toUiState(raw),
      camera: raw.camera,
      beat: raw.beat,
      connection: 'preview',
      preview: true,
      pinned,
    })
  }

  const arm = () => {
    clearTimeout(timer)
    if (pinned || closed) return
    const scene = SCENES[index]
    const total = scene.ms + (scene.scoringMs || 0)
    const smooth = scene.dialTo != null || scene.to != null
    // A scoring beat with no moving number (reflex) still has to land, not get skipped.
    const holdScore = !smooth && scene.scoringMs > 0 && step < scene.ms
    const wait = smooth ? TICK_MS : holdScore ? scene.ms - step : Math.max(0, total - step)
    timer = setTimeout(() => {
      if (smooth) step += TICK_MS
      else if (holdScore) step = scene.ms
      else step = total
      if (step >= total) {
        index = (index + 1) % SCENES.length
        step = 0
      }
      emit()
      arm()
    }, wait)
  }

  const onKey = (event) => {
    if (event.target?.tagName === 'INPUT') return        // typing a name, not switching scenes
    if (event.key === '0') {
      pinned = false
      emit()
      arm()
      return
    }
    const jump = KEY_TO_SCENE[event.key]
    if (jump === undefined) return
    pinned = true
    index = jump
    step = 0
    clearTimeout(timer)
    emit()
  }

  window.addEventListener('keydown', onKey)
  previewEmit = emit
  emit()
  arm()

  return () => {
    closed = true
    previewEmit = null
    clearTimeout(timer)
    window.removeEventListener('keydown', onKey)
  }
}

function easeInOut(t) {
  const x = Math.min(1, Math.max(0, t))
  return x < 0.5 ? 2 * x * x : 1 - ((-2 * x + 2) ** 2) / 2
}

function sampleScene(scene, elapsed) {
  const reading = scene.screen === 'performing' && scene.scoringMs > 0 && elapsed >= scene.ms
  const span = scene.ms > 0 ? scene.ms : 1
  const eased = easeInOut(Math.min(1, elapsed / span))
  let tick = null
  if (scene.dialTo != null) {
    tick = Math.round(scene.dialFrom + (scene.dialTo - scene.dialFrom) * eased)
  } else if (scene.to != null) {
    const from = scene.from ?? scene.to
    tick = Math.round(from + (scene.to - from) * (reading ? 1 : eased))
  }
  const remaining = scene.screen === 'performing' && !reading ? Math.max(0, (scene.ms - elapsed) / 1000) : null
  return { tick, reading, remaining }
}

function sceneState(scene, sample) {
  const active = scene.screen === 'idle' || scene.screen === 'reveal'
    ? null
    : { round_id: scene.round, round_type_id: scene.type }
  const claim = scene.claim ?? (scene.screen === 'predicting' ? sample.tick : null)
  const faceRound = scene.type === 5 || scene.type === 6
  let mode = 'preview'
  if (sample.reading) mode = 'scoring'
  else if (scene.screen === 'performing') mode = 'measuring'
  const camera = !faceRound || scene.screen === 'idle' || scene.screen === 'reveal'
    ? null
    : {
        available: true,
        previewFrame: true,
        mode,
        kind: scene.type === 6 ? 'straight' : 'poker',
        face: true,
        smiling: false,
        composure: scene.screen === 'performing' ? sample.tick : 80,
        remainingS: sample.remaining ?? undefined,
        windowS: scene.ms / 1000,
        phase: scene.type === 6 && scene.screen === 'performing' && !sample.reading ? 'holding' : undefined,
        held_s: scene.type === 6 && scene.screen === 'performing' && !sample.reading ? 3.2 : undefined,
      }
  const latest = scene.screen === 'reveal'
    ? row(scene.round, scene.type, 9, 'Saim', scene.claim, scene.actual, scene.gap, 'Preview verdict.', scene.unit)
    : null
  const nameEntry = scene.type === 5
  return {
    screen: scene.screen,
    player: nameEntry ? previewPlayer ?? 'Guest' : 'Saim',
    nameEntry,
    playerNamed: nameEntry && previewPlayer !== null,
    activeRound: active,
    liveClaim: claim,
    latestResult: latest,
    history: HISTORY,
    camera,
    beat: sample.reading ? 'scoring' : null,
    notice: scene.screen === 'performing' && scene.type === 5
      ? { level: 'info', message: 'Why should we hire you, and not literally anyone else?' }
      : null,
  }
}

function row(round, type, id, player, claim, actual, gap, verdict, unit) {
  return {
    round_key: round,
    round_type_id: type,
    round_id: `${round}-${id}`,
    player,
    claim,
    actual,
    actual_raw: actual,
    actual_unit: unit || (type === 1 ? 'ms' : 'composure'),
    gap,
    score: Math.max(0, Math.round(100 - gap)),
    verdict_text: verdict,
    verdict_status: 'ready',
  }
}
