import { useEffect, useRef, useState } from 'react'

const easeOutExpo = (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t))

// Animates a displayed integer from its previous value to `target` whenever
// target changes. Plain requestAnimationFrame — no animation library — used
// for the reveal moment's claim/actual/gap numbers.
export function useCountUp(target, { duration = 900, delay = 0 } = {}) {
  const [value, setValue] = useState(target)
  const fromRef = useRef(target)

  useEffect(() => {
    const from = fromRef.current
    let raf
    let timeout
    let start = null

    const tick = (now) => {
      if (start === null) start = now
      const t = Math.min(1, (now - start) / duration)
      setValue(Math.round(from + (target - from) * easeOutExpo(t)))
      if (t < 1) raf = requestAnimationFrame(tick)
    }

    timeout = setTimeout(() => {
      raf = requestAnimationFrame(tick)
    }, delay)

    fromRef.current = target
    return () => {
      clearTimeout(timeout)
      if (raf) cancelAnimationFrame(raf)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])

  return value
}
