// MOCK ONLY. Simulates the Pi backend's game loop locally so the UI has
// something realistic to render before real hardware/serial data exists.
// Nothing in this file is part of the real data contract — see dataSource.js
// for the one place that gets swapped out when a live source exists.
import { ROUND_DEFS } from './roundDefs'
import { mockVerdict } from './verdicts'

const PLAYER_NAMES = [
  'Player 7', 'Jordan K.', 'The Guy From Table 3', 'Priya S.',
  'Overconfident Dave', 'Marcus', 'Table 12', 'Riley',
]

const TIMINGS = {
  idle: 4000,
  predicting: 3200,
  performing: 1700,
  reveal: 4800,
}

const ROUNDS_PER_SESSION_MIN = 3
const ROUNDS_PER_SESSION_MAX = 4

function shuffle(arr) {
  const copy = [...arr]
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[copy[i], copy[j]] = [copy[j], copy[i]]
  }
  return copy
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n))
}

// Maps a 0-100 "actual performance, normalized" value to a plausible raw
// sensor reading per round. Backend owns the real mapping; this only needs
// to look sane on screen.
function deriveRaw(roundId, actualNormalized) {
  switch (roundId) {
    case 'reflex':
      return Math.round(600 - (actualNormalized / 100) * 450) // 150-600ms
    case 'steady_hands':
      return +(35 + ((100 - actualNormalized) / 100) * 465).toFixed(1) // mg RMS (35 = 100, 500 = 0)
    case 'retreat':
      return Math.round(((100 - actualNormalized) / 100) * 40) // cm
    case 'poker_face':
      return +(40 - (actualNormalized / 100) * 37).toFixed(1) // % smiling (3% = 100, 40% = 0)
    case 'straight_face_timer':
      return +((actualNormalized / 100) * 60).toFixed(1) // s held
    default:
      return actualNormalized
  }
}

class MockSimulator {
  constructor() {
    this.listeners = new Set()
    this.history = []
    this.player = null
    this.roundQueue = []
    this.phase = 'idle'
    this.phaseStart = Date.now()
    this.currentRoundDef = null
    this.claimTarget = 0
    this.latestResult = null
    this.sessionGapBias = 55
    this._tick = this._tick.bind(this)
    this._resultCounter = 0
  }

  start() {
    this.phaseStart = Date.now()
    this.timer = setInterval(this._tick, 120)
    return this
  }

  stop() {
    clearInterval(this.timer)
  }

  subscribe(cb) {
    this.listeners.add(cb)
    cb(this._buildState())
    return () => this.listeners.delete(cb)
  }

  _emit() {
    const state = this._buildState()
    this.listeners.forEach((cb) => cb(state))
  }

  _beginIdle() {
    this.phase = 'idle'
    this.phaseStart = Date.now()
    this.currentRoundDef = null
    this.player = null
  }

  _beginSession() {
    this.player = PLAYER_NAMES[Math.floor(Math.random() * PLAYER_NAMES.length)]
    const count =
      ROUNDS_PER_SESSION_MIN +
      Math.floor(Math.random() * (ROUNDS_PER_SESSION_MAX - ROUNDS_PER_SESSION_MIN + 1))
    this.roundQueue = shuffle(ROUND_DEFS).slice(0, count)
    this.sessionGapBias = 45 + Math.random() * 25
    this._beginPredicting()
  }

  _beginPredicting() {
    this.currentRoundDef = this.roundQueue.shift()
    this.phase = 'predicting'
    this.phaseStart = Date.now()
    this.claimTarget = Math.round(25 + Math.random() * 70)
  }

  _beginPerforming() {
    this.phase = 'performing'
    this.phaseStart = Date.now()
  }

  _beginReveal() {
    const roundDef = this.currentRoundDef
    const claim = this.claimTarget
    const direction = Math.random() < 0.5 ? -1 : 1
    const gapMagnitude = clamp(this.sessionGapBias + (Math.random() * 16 - 8), 3, 95)
    const actual = clamp(Math.round(claim - direction * gapMagnitude), 0, 100)
    const gap = Math.abs(claim - actual)

    this._resultCounter += 1
    const result = {
      round_id: `${roundDef.round_id}-${this._resultCounter}`,
      round_name: roundDef.round_name,
      claim,
      actual,
      actual_raw: deriveRaw(roundDef.round_id, actual),
      actual_unit: roundDef.actual_unit,
      gap,
      verdict_text: mockVerdict(gap),
      timestamp: new Date().toISOString(),
      player: this.player, // extension beyond the literal contract, needed for per-player leaderboard/curve
    }

    this.latestResult = result
    this.history = [...this.history, result]
    // simulate the player recalibrating: the gap trends down across their session
    this.sessionGapBias = clamp(this.sessionGapBias - (12 + Math.random() * 8), 4, 95)

    this.phase = 'reveal'
    this.phaseStart = Date.now()
  }

  _tick() {
    const elapsed = Date.now() - this.phaseStart
    if (this.phase === 'idle' && elapsed > TIMINGS.idle) {
      this._beginSession()
    } else if (this.phase === 'predicting' && elapsed > TIMINGS.predicting) {
      this._beginPerforming()
    } else if (this.phase === 'performing' && elapsed > TIMINGS.performing) {
      this._beginReveal()
    } else if (this.phase === 'reveal' && elapsed > TIMINGS.reveal) {
      if (this.roundQueue.length > 0) this._beginPredicting()
      else this._beginIdle()
    }
    this._emit()
  }

  _buildState() {
    const elapsed = Date.now() - this.phaseStart
    let liveClaim = null
    if (this.phase === 'predicting') {
      const t = clamp(elapsed / TIMINGS.predicting, 0, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      const wobble = t < 0.9 ? Math.sin(elapsed / 90) * 8 * (1 - t) : 0
      liveClaim = Math.round(clamp(this.claimTarget * eased + wobble, 0, 100))
    } else if (this.phase === 'performing' || this.phase === 'reveal') {
      liveClaim = this.claimTarget
    }

    return {
      screen: this.phase, // 'idle' | 'predicting' | 'performing' | 'reveal' — UI sequencing only, not in the backend contract
      player: this.player,
      activeRound: this.currentRoundDef,
      liveClaim,
      latestResult: this.latestResult,
      history: this.history,
    }
  }
}

export function createMockSimulator() {
  return new MockSimulator().start()
}
