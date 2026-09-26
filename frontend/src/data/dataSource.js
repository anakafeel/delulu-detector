// The one file to touch when the data source changes. Everything else in the
// app talks to `subscribe`, never to fetch/mock details directly.
//
// Live (default): the Pi game loop (python pi/main.py --ui) serves its state.
//   1. EventSource on /api/events (Server-Sent Events, pushed on every change)
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

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')
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

function subscribeLive(callback) {
  let closed = false
  let last = null
  let pollTimer = null
  let source = null

  const deliver = (raw) => {
    if (closed) return
    last = toUiState(raw)
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
