import { toUiState } from './liveAdapter'

// Frontend-only stand-in for the Python game. No Arduino, no camera, no API.
// Turn it on with `npm run dev:preview`, or open any build with ?preview=1.
// Keys 1–4 pin a screen. Key 0 resumes the automatic walk.

const HISTORY = [
  row('poker_face', 5, 1, 'Saim', 69, 36, 33, 'Claimed 69, held a 36.'),
  row('poker_face', 5, 2, 'Saim', 20, 93, 73, 'Claimed 20, reality 93.'),
  row('straight_face', 6, 3, 'Saim', 20, 15, 5, 'Claim 20, reality 15.'),
]

const SCENES = [
  { screen: 'idle', ms: 2500 },
  { screen: 'predicting', round: 'poker_face', type: 5, ms: 3500, dial: [12, 28, 47, 63, 72] },
  { screen: 'performing', round: 'poker_face', type: 5, ms: 4000, claim: 72, composure: [70, 58, 44, 36] },
  { screen: 'reveal', round: 'poker_face', type: 5, ms: 4500, claim: 72, actual: 36, gap: 36 },
  { screen: 'predicting', round: 'straight_face', type: 6, ms: 3000, dial: [8, 20, 40] },
  { screen: 'performing', round: 'straight_face', type: 6, ms: 4000, claim: 40, composure: [55, 40, 22] },
  { screen: 'reveal', round: 'straight_face', type: 6, ms: 4500, claim: 40, actual: 22, gap: 18 },
  { screen: 'predicting', round: 'reflex', type: 1, ms: 2500, dial: [40, 70, 88] },
  { screen: 'performing', round: 'reflex', type: 1, ms: 2000, claim: 88 },
  { screen: 'reveal', round: 'reflex', type: 1, ms: 4000, claim: 88, actual: 310, gap: 42, unit: 'ms' },
]

const KEY_TO_SCENE = { 1: 0, 2: 1, 3: 2, 4: 3 }

export function previewEnabled() {
  if (import.meta.env.VITE_UI_PREVIEW === '1') return true
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
    const tick = scene.dial?.[Math.min(step, (scene.dial?.length ?? 1) - 1)]
      ?? scene.composure?.[Math.min(step, (scene.composure?.length ?? 1) - 1)]
    const raw = sceneState(scene, tick)
    callback({
      ...toUiState(raw),
      camera: raw.camera,
      connection: 'preview',
      preview: true,
      pinned,
    })
  }

  const arm = () => {
    clearTimeout(timer)
    if (pinned || closed) return
    const scene = SCENES[index]
    const frames = scene.dial?.length || scene.composure?.length || 1
    const slice = Math.max(400, Math.round(scene.ms / frames))
    timer = setTimeout(() => {
      step += 1
      const limit = scene.dial?.length || scene.composure?.length || 1
      if (step >= limit) {
        index = (index + 1) % SCENES.length
        step = 0
      }
      emit()
      arm()
    }, slice)
  }

  const onKey = (event) => {
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
  emit()
  arm()

  return () => {
    closed = true
    clearTimeout(timer)
    window.removeEventListener('keydown', onKey)
  }
}

function sceneState(scene, tick) {
  const active = scene.screen === 'idle' || scene.screen === 'reveal'
    ? null
    : { round_id: scene.round, round_type_id: scene.type }
  const claim = scene.claim ?? (scene.screen === 'predicting' ? tick : null)
  const camera = scene.type === 1 || scene.screen === 'idle' || scene.screen === 'reveal'
    ? null
    : {
        available: true,
        previewFrame: true,
        mode: scene.screen === 'performing' ? 'measuring' : 'preview',
        kind: scene.type === 6 ? 'straight' : 'poker',
        face: true,
        smiling: false,
        composure: scene.screen === 'performing' ? tick : 80,
        phase: scene.type === 6 && scene.screen === 'performing' ? 'holding' : undefined,
        held_s: scene.type === 6 && scene.screen === 'performing' ? 3.2 : undefined,
      }
  const latest = scene.screen === 'reveal'
    ? row(scene.round, scene.type, 9, 'Saim', scene.claim, scene.actual, scene.gap, 'Preview verdict.', scene.unit)
    : null
  return {
    screen: scene.screen,
    player: 'Saim',
    activeRound: active,
    liveClaim: claim,
    latestResult: latest,
    history: HISTORY,
    camera,
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
