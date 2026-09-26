import { severityFor } from './severity'

// Roast copy bucketed by severity tier. The real verdict_text will come from
// ElevenLabs' prompt output on the Pi — this is mock variety only.
const LINES = {
  good: [
    'Scary accurate. You know yourself.',
    'Certified self-aware. Boring, but correct.',
    'No notes. You called it.',
  ],
  warning: [
    'Close enough. Minor delusion detected.',
    'Respectable miss. Barely delulu.',
    'You were basically right, annoyingly.',
  ],
  serious: [
    "Bestie... no.",
    'That confidence was not earned.',
    'The gap is starting to talk.',
  ],
  critical: [
    'Delulu is not the solulu.',
    'Your brain and your body are not on speaking terms.',
    'The gap called. It wants an apology.',
    'Certified Grade-A Delusional.',
  ],
}

export function mockVerdict(gap) {
  const { key } = severityFor(gap)
  const lines = LINES[key]
  return lines[Math.floor(Math.random() * lines.length)]
}
