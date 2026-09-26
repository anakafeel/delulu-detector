import { useEffect, useRef, useState } from 'react'

// Tracks a container's rendered CSS pixel width so an SVG's viewBox can be
// set to match it 1:1 — otherwise viewBox units get magnified/shrunk by
// whatever the container size happens to be, throwing off font-size and
// stroke-width (both are scaled by the viewBox->viewport transform).
export function useMeasuredWidth(fallback = 480) {
  const ref = useRef(null)
  const [width, setWidth] = useState(fallback)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return [ref, width]
}
