// frontend/src/components/DeluluCharacter.jsx
<img src="/character/delulu.svg" alt="" />
import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import DeluluSvg from './DeluluSvg'   // or drop this and use <img> below

const REACTIONS = {
  validated: {
    body: { rotate: [0, -2, 2, 0], y: [0, -4, 0] },
    head: { rotate: [-3, 3, -3] },
    transition: { duration: 1.2, ease: 'easeInOut' },
    glow: 'var(--color-good)',
  },
  mild: {
    body: { rotate: [0, -3, 3, 0] },
    head: { rotate: [0, 10, -5, 0] },
    transition: { duration: 0.9, ease: 'easeOut' },
    glow: 'var(--color-warning)',
  },
  spicy: {
    body: { x: [0, -6, 6, -3, 3, 0], y: [0, 2, 0] },
    head: { rotate: [0, -8, 8, 0] },
    transition: { duration: 0.6, ease: 'easeOut' },
    glow: 'var(--color-serious)',
  },
  delulu: {
    body: { x: [0, -10, 10, -8, 8, -4, 4, 0], rotate: [0, -3, 3, -2, 2, 0] },
    head: { rotate: [0, -14, 14, -10, 10, 0] },
    transition: { duration: 0.9, ease: 'easeOut' },
    glow: 'var(--color-critical)',
  },
  false_start: {
    body: { y: [0, -6, 0] },
    head: { rotate: [0, 6, -6, 0] },
    transition: { duration: 1.0, ease: 'easeInOut' },
    glow: 'var(--color-warning)',
  },
  timeout: {
    body: { opacity: [1, 0.85, 1] },
    head: { rotate: [0, 3, -3, 0] },
    transition: { duration: 1.4, ease: 'easeInOut' },
    glow: 'var(--color-ink-faint)',
  },
}

export default function DeluluCharacter({
  tier = 'validated',
  speaking = false,
  size = 220,
}) {
  const reaction = REACTIONS[tier] ?? REACTIONS.validated
  const reduce = useReducedMotion()

  // Re-key on tier change so the animation restarts for each new verdict.
  const [pulse, setPulse] = useState(0)
  useEffect(() => setPulse((p) => p + 1), [tier])

  const bodyAnim = reduce ? {} : reaction.body
  const headAnim = reduce ? {} : reaction.head

  return (
    <div className="relative" style={{ width: size, height: size * 1.6 }}>
      <motion.div
        className="absolute left-1/2 top-1/2 -z-10 h-3/4 w-3/4 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-30 blur-3xl"
        animate={{ background: reaction.glow, scale: speaking ? [1, 1.08, 1] : 1 }}
        transition={{ duration: 1.2, repeat: speaking ? Infinity : 0 }}
      />

      <motion.div
        key={pulse}
        className="h-full w-full origin-bottom"
        animate={bodyAnim}
        transition={reaction.transition}
      >
        <motion.div
          className="h-full w-full origin-bottom"
          animate={headAnim}
          transition={reaction.transition}
        >
          <Character speaking={speaking} />
        </motion.div>
      </motion.div>
    </div>
  )
}

function Character({ speaking }) {
  // Option A — inline SVG, per-part control.
  return (
    <DeluluSvg
      className="h-full w-full object-contain"
      data-speaking={speaking ? 'true' : 'false'}
    />
  )

  // Option B — image tag, whole-image only. Delete the above and uncomment:
  // return <img src="/character/delulu.svg" alt="" className="h-full w-full object-contain" />
}