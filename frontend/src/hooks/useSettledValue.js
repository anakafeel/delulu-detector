import { useEffect, useRef, useState } from 'react'

// `value`, but only once it has stopped changing for `delayMs` (and at least
// every `maxWaitMs` while it keeps changing). For screen-reader text that
// follows the live dial: a knob sends up to 10 values a second, which would be
// far too chatty to announce one by one. delayMs 0 = follow immediately.
export function useSettledValue(value, delayMs, maxWaitMs = delayMs * 3) {
  const [settled, setSettled] = useState(value)
  const pendingSince = useRef(null)

  useEffect(() => {
    if (Object.is(value, settled)) {
      pendingSince.current = null
      return undefined
    }
    const now = Date.now()
    if (pendingSince.current === null) pendingSince.current = now
    const wait = Math.max(0, Math.min(delayMs, pendingSince.current + maxWaitMs - now))
    const timer = setTimeout(() => {
      pendingSince.current = null
      setSettled(value)
    }, wait)
    return () => clearTimeout(timer)
  }, [value, settled, delayMs, maxWaitMs])

  return settled
}
