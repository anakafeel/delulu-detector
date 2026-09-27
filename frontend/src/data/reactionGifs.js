// Reaction GIFs for the reveal, picked by file name from src/assets/reactions/ (see the
// README there). Local files only: no network at the venue, nothing committed.
const FILES = import.meta.glob('../assets/reactions/*.{gif,webp,png}', {
  eager: true,
  query: '?url',
  import: 'default',
})

const BY_PREFIX = {}
for (const [path, url] of Object.entries(FILES)) {
  const name = path.split('/').pop()
  const prefix = name.split('-')[0].toLowerCase()
  ;(BY_PREFIX[prefix] ??= []).push({ name, url })
}
for (const list of Object.values(BY_PREFIX)) list.sort((a, b) => a.name.localeCompare(b.name))

// Stable per round: re-renders of the same reveal never swap the GIF.
function pick(list, key) {
  let h = 0
  for (const ch of String(key)) h = (h * 31 + ch.charCodeAt(0)) | 0
  return list[Math.abs(h) % list.length]
}

export function reactionGifFor(result) {
  if (!result || result.gap == null) return null
  const numbers = [result.claim, result.actual, result.score]
  const tier = String(result.tier ?? '').toLowerCase()
  const order = [numbers.includes(67) && '67', tier, 'any'].filter(Boolean)
  for (const prefix of order) {
    const list = BY_PREFIX[prefix]
    if (list?.length) return pick(list, result.round_id)
  }
  return null
}
