import { motion, useReducedMotion } from 'motion/react'

// Define reactions based on the verdict severity
const REACTIONS = {
  validated: {
    body: { rotate: [0, -2, 2, 0], y: [0, -4, 0] },
    transition: { duration: 1.2, ease: 'easeInOut' },
    glow: 'var(--color-good)',
    message: "You nailed it. I'm impressed."
  },
  mild: {
    body: { rotate: [0, -3, 3, 0] },
    transition: { duration: 0.9, ease: 'easeOut' },
    glow: 'var(--color-warning)',
    message: "Not bad, but you're slipping."
  },
  spicy: {
    body: { x: [0, -6, 6, -3, 3, 0], y: [0, 2, 0] },
    transition: { duration: 0.6, ease: 'easeOut' },
    glow: 'var(--color-serious)',
    message: "Oof. That gap is spicy."
  },
  delulu: {
    body: { x: [0, -10, 10, -8, 8, -4, 4, 0], rotate: [0, -3, 3, -2, 2, 0] },
    transition: { duration: 0.9, ease: 'easeOut' },
    glow: 'var(--color-critical)',
    message: "Completely delulu. Reality check failed."
  },
}

export default function DeluluCharacter({ 
  tier = 'validated', 
  speaking = false, 
  waving = false,
  smiling = false,
  size = 220 
}) {
  const reaction = REACTIONS[tier] ?? REACTIONS.validated
  const reduce = useReducedMotion()

  // Simulate smiling by slightly scaling up and bouncing
  const smileAnim = smiling && !reduce ? { scale: [1, 1.05, 1], transition: { duration: 2, repeat: Infinity } } : {}
  
  // Simulate waving by rotating the whole character slightly
  const waveAnim = waving && !reduce ? { rotate: [0, 5, -5, 0], transition: { duration: 1.5, repeat: Infinity } } : {}

  return (
    <div className="relative flex flex-col items-center" style={{ width: size }}>
      {/* Speech Bubble */}
      {(speaking || reaction.message) && (
        <motion.div
          initial={{ opacity: 0, y: 10, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="absolute -top-16 z-20 mb-4 max-w-[200px] rounded-2xl border border-ink-faint/30 bg-surface/90 px-4 py-2 text-center font-game text-sm text-ink backdrop-blur-sm"
        >
          {reaction.message}
          <div className="absolute -bottom-2 left-1/2 h-4 w-4 -translate-x-1/2 rotate-45 border-b border-r border-ink-faint/30 bg-surface/90" />
        </motion.div>
      )}

      {/* Character Container */}
      <motion.div
        className="relative"
        style={{ width: size, height: size * 1.6 }}
        animate={{ ...smileAnim, ...waveAnim }}
      >
        {/* Glow effect based on severity */}
        <motion.div
          className="absolute left-1/2 top-1/2 -z-10 h-3/4 w-3/4 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-30 blur-3xl"
          animate={{ background: reaction.glow }}
          transition={{ duration: 0.5 }}
        />

        {/* The Character Image */}
        <motion.img
          src="/public/delulu_character.svg"
          alt="Delulu Character"
          className="h-full w-full object-contain drop-shadow-2xl"
          animate={reduce ? {} : reaction.body}
          transition={reaction.transition}
        />
      </motion.div>
    </div>
  )
}