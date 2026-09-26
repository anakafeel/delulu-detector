// Presage SmartSpectra bridge. Python pushes BGR frames on stdin from the
// camera vision.py already opened. This process does not open a camera.
// Stdout is one JSON object per line. A missing key, a failed start, or an
// SDK error is an error line and a non-zero exit. This process never invents
// a composure number.

import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const {
  SmartSpectraSDK,
  PixelFormat,
  SmartSpectraLogLevel,
  faceMetrics,
  decodeMetrics,
} = require('@smartspectra/node-sdk')

const NEUTRAL = 6
const HEADER = 24

function emit(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`)
}

function neutralConfidence(metrics) {
  const obj = typeof metrics.toObject === 'function' ? metrics.toObject() : metrics
  const list = obj?.face?.expression || []
  if (!list.length) return null
  const scores = list[list.length - 1]?.scores || []
  for (const score of scores) {
    const type = score?.type
    if (type === NEUTRAL || type === 'NEUTRAL') {
      const confidence = score.confidence
      if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return null
      return confidence
    }
  }
  return null
}

const apiKey = (process.env.SMARTSPECTRA_API_KEY || process.env.PRESAGE_API_KEY || '').trim()
if (!apiKey) {
  emit({ type: 'error', message: 'SMARTSPECTRA_API_KEY is not set' })
  process.exit(2)
}

const sdk = new SmartSpectraSDK({
  apiKey,
  requestedMetrics: [...faceMetrics],
  enableTelemetry: false,
  logLevel: SmartSpectraLogLevel.kInfo,
})

let fatal = null
sdk.on('error', (code, message, retryable) => {
  fatal = message || `SmartSpectra error ${code}`
  emit({ type: 'error', code, message: fatal, retryable: !!retryable })
})
sdk.on('validationStatus', (code, _ts, hint) => {
  if (fatal) return
  emit({ type: 'validation', code, hint: hint || '' })
})
sdk.on('metrics', (buf) => {
  if (fatal) return
  let metrics
  try {
    metrics = decodeMetrics(buf)
  } catch (err) {
    fatal = `could not decode Presage metrics: ${err.message || err}`
    emit({ type: 'error', message: fatal })
    return
  }
  if (Buffer.isBuffer(metrics)) {
    fatal = 'Presage metrics decoder returned a raw buffer'
    emit({ type: 'error', message: fatal })
    return
  }
  const composure = neutralConfidence(metrics)
  if (composure === null) return
  emit({ type: 'sample', composure })
})

try {
  sdk.useCustomInput()
  sdk.start()
} catch (err) {
  emit({
    type: 'error',
    code: err.code,
    message: err.message || String(err),
  })
  process.exit(1)
}
emit({ type: 'ready' })

const stdin = process.stdin
stdin.resume()
let pending = Buffer.alloc(0)

function takeFrames() {
  while (pending.length >= HEADER) {
    if (pending.toString('ascii', 0, 4) !== 'FRM1') {
      emit({ type: 'error', message: 'bad frame header from the camera pipe' })
      process.exit(1)
    }
    const width = pending.readUInt32LE(4)
    const height = pending.readUInt32LE(8)
    const stride = pending.readUInt32LE(12)
    const timestampUs = Number(pending.readBigUInt64LE(16))
    const nbytes = stride * height
    if (!width || !height || !stride || nbytes <= 0 || nbytes > 32 * 1024 * 1024) {
      emit({ type: 'error', message: 'refusing a frame with an impossible size' })
      process.exit(1)
    }
    if (pending.length < HEADER + nbytes) return
    const frame = Buffer.from(pending.subarray(HEADER, HEADER + nbytes))
    pending = pending.subarray(HEADER + nbytes)
    if (fatal) return
    const accepted = sdk.sendFrame(frame, width, height, stride, PixelFormat.kRGB, timestampUs)
    if (!accepted) {
      fatal = 'Presage rejected a frame'
      emit({ type: 'error', message: fatal })
    }
  }
}

stdin.on('data', (chunk) => {
  pending = Buffer.concat([pending, chunk])
  takeFrames()
})
stdin.on('end', () => {
  sdk.stopAsync().catch(() => {}).finally(() => process.exit(fatal ? 1 : 0))
})
