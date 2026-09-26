import { useEffect, useRef, useState } from 'react'

// Short ease-out chase for a value that arrives ~10 times a second (the claim
// knob). Each frame moves from the number already on screen toward the latest
// target, so a new tick never restarts a long tween and the dial doesn't lag.
const TAU_DIVISOR = 3.5

function missingNumber(value) {
  return value == null || Number.isNaN(value)
}

export function useFollowNumber(target, ms = 200) {
  const [shown, setShown] = useState(target)
  const [tracked, setTracked] = useState(target)
  const shownRef = useRef(target)

  const missing = missingNumber(target)
  const trackedMissing = missingNumber(tracked)
  if (!Object.is(target, tracked)) {
    setTracked(target)
    // Snap only when there was nothing to chase (first claim, or the claim dropped).
    if (missing || trackedMissing) setShown(missing ? null : target)
  }

  useEffect(() => {
    if (missingNumber(target)) {
      shownRef.current = null
      return undefined
    }
    if (missingNumber(shownRef.current)) {
      shownRef.current = target
      return undefined
    }
    if (Math.abs(shownRef.current - target) < 0.05) {
      shownRef.current = target
      return undefined
    }

    const tau = Math.max(1, ms) / TAU_DIVISOR
    let raf = 0
    let last = null
    const tick = (now) => {
      const cur = shownRef.current
      if (missingNumber(cur)) return
      if (last == null) last = now
      const dt = Math.min(48, now - last)
      last = now
      const next = cur + (target - cur) * (1 - Math.exp(-dt / tau))
      if (Math.abs(target - next) < 0.05) {
        shownRef.current = target
        setShown(target)
        return
      }
      shownRef.current = next
      setShown(next)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])

  return missing ? null : shown
}
