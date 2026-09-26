// The one file to touch when the data source changes. Everything else in the
// app talks to `subscribe`, never to fetch/mock details directly.
//
// Live (default): the Pi game loop (python pi/main.py --ui) serves its state.
//   1. EventSource on /api/events (Server-Sent Events): the full state on every
//      real change, plus small `dial` events ({"liveClaim": N}) while the knob
//      turns, and small `live` events ({"camera": {mode, face, smiling, ...}}, the
//      face rounds' live OpenCV numbers, up to 4/s), both merged in without
//      touching history/leaderboard
//   2. while that is down, polling /api/state every second (EventSource keeps
//      reconnecting in the background; polling stops once it is back)
// Mock: open the app with ?mock=1, or build/run with VITE_USE_MOCK=1.
// In dev, vite.config.js proxies /api to the Python server; the built app is
// served by the Python server itself, so /api is same-origin there.
// VITE_API_BASE (e.g. http://192.168.1.20:8765) points at a Pi elsewhere.
import { createMockSimulator } from './mockSimulator'
import { toUiState } from './liveAdapter'

const params = new URLSearchParams(window.location.search)
export const USE_MOCK = params.has('mock')
  ? params.get('mock') !== '0'
  : import.meta.env.VITE_USE_MOCK === '1'

export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')
const POLL_MS = 1000
const OFFLINE_STATE = toUiState({ screen: 'idle', history: [] })

let mockInstance = null

export function subscribe(callback) {
  if (USE_MOCK) {
    if (!mockInstance) mockInstance = createMockSimulator()
    return mockInstance.subscribe((state) => callback({ ...state, connection: 'mock' }))
  }
  return subscribeLive(callback)
}

// Keeps the previous converted value (same reference) when the raw JSON part
// is unchanged, so memoized components (Leaderboard, CalibrationCurve) skip
// re-rendering when only something else in the state changed.
function sharedPart() {
  let key = null
  let value
  return (raw, convert) => {
    const nextKey = JSON.stringify(raw ?? null)
    if (nextKey !== key) {
      key = nextKey
      value = convert()
    }
    return value
  }
}

// A full snapshot only has the camera's slow part ({available, mode}); keep the
// last `live` numbers while the mode is the same, so the readout doesn't blink.
function keepLiveCamera(prev, next) {
  if (!next || !prev || prev.mode !== next.mode || prev.available !== next.available || prev.kind !== next.kind) {
    return next
  }
  return { ...prev, ...next }
}

function subscribeLive(callback) {
  let closed = false
  let last = null
  let pollTimer = null
  let source = null
  const history = sharedPart()
  const leaderboard = sharedPart()
  const latestResult = sharedPart()

  const deliver = (raw) => {
    if (closed) return
    const next = toUiState(raw)
    last = {
      ...next,
      history: history(raw.history, () => next.history),
      leaderboard: leaderboard(raw.leaderboard, () => next.leaderboard),
      latestResult: latestResult(raw.latestResult, () => next.latestResult),
      camera: keepLiveCamera(last?.camera, next.camera),
    }
    callback({ ...last, connection: 'live' })
  }
  // `event: dial`: only the live claim moved. Everything else keeps its reference.
  const deliverDial = (raw) => {
    if (closed || !last) return
    const liveClaim = raw.liveClaim ?? null
    if (liveClaim === last.liveClaim) return
    last = { ...last, liveClaim }
    callback({ ...last, connection: 'live' })
  }
  // `event: live`: the camera's fast numbers. Merged into state.camera; nothing else changes.
  const deliverLive = (raw) => {
    if (closed || !last || !raw?.camera) return
    last = { ...last, camera: { ...last.camera, ...raw.camera } }
    callback({ ...last, connection: 'live' })
  }
  const markOffline = () => {
    if (!closed) callback({ ...(last ?? OFFLINE_STATE), connection: 'offline' })
  }

  const poll = () =>
    fetch(`${API_BASE}/api/state`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(deliver)
      .catch(markOffline)
  const startPolling = () => {
    if (pollTimer || closed) return
    poll()
    pollTimer = setInterval(poll, POLL_MS)
  }
  const stopPolling = () => {
    clearInterval(pollTimer)
    pollTimer = null
  }

  let retryTimer = null
  const connect = () => {
    if (closed) return
    source = new EventSource(`${API_BASE}/api/events`)
    source.onopen = stopPolling
    source.onmessage = (event) => {
      try {
        deliver(JSON.parse(event.data))
        stopPolling()
      } catch {
        // ignore a garbled event; the next one replaces it
      }
    }
    source.addEventListener('live', (event) => {
      try {
        deliverLive(JSON.parse(event.data))
      } catch {
        // ignore a garbled event; the next one replaces it
      }
    })
    source.addEventListener('dial', (event) => {
      try {
        deliverDial(JSON.parse(event.data))
      } catch {
        // ignore a garbled event; the next one replaces it
      }
    })
    source.onerror = () => {
      startPolling()
      // EventSource retries by itself after a dropped connection, but gives up
      // for good on an HTTP error (e.g. the dev proxy's 502 while Python is down).
      if (source.readyState === EventSource.CLOSED && !retryTimer) {
        retryTimer = setTimeout(() => {
          retryTimer = null
          connect()
        }, 3000)
      }
    }
  }

  if (typeof EventSource === 'undefined') startPolling()
  else connect()

  return () => {
    closed = true
    stopPolling()
    clearTimeout(retryTimer)
    source?.close()
  }
}
