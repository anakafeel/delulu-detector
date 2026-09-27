import { useRef } from 'react'

const NAME_MAX = 16          // the Pi keeps this many characters (config.UI_PLAYER_NAME_MAX)

// The name field (state: hooks/useNameEntry.js).
// variant "prompt": the big ask (attract screen, or nobody has typed a name yet).
// variant "compact": a name is set; a slim "not you?" bar so the next player can change it.
export default function NameEntry({ entry, variant, player, lead, onHelp }) {
  const inputRef = useRef(null)

  // No mouse at the booth: keep the keyboard on this field while it is on screen.
  const refocus = () => requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }))

  const onKeyDown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      entry.submit()
    } else if (event.key === '?') {
      event.preventDefault()                 // "?" opens the explainer, it's not part of a name
      onHelp?.()
    } else if (event.key === 'Escape') {
      entry.setDraft('')
    }
  }

  const field = (
    <input
      ref={inputRef}
      autoFocus
      value={entry.draft}
      maxLength={NAME_MAX}
      onChange={(e) => entry.setDraft(e.target.value)}
      onKeyDown={onKeyDown}
      onBlur={refocus}
      spellCheck={false}
      autoComplete="off"
      aria-label="Your name"
      placeholder={variant === 'prompt' ? 'your name' : 'new name'}
      className={
        variant === 'prompt'
          ? 'w-full rounded-xl border-4 border-ink bg-void px-6 py-4 text-center font-display text-title text-ink placeholder:text-ink-faint focus:outline-none'
          : 'w-[12ch] rounded-lg border-2 border-ink-faint bg-void px-3 py-1.5 font-display text-data text-ink placeholder:text-ink-faint focus:border-ink focus:outline-none'
      }
    />
  )

  const status = <Status entry={entry} />

  if (variant === 'compact') {
    return (
      <div className="pointer-events-auto flex items-center gap-3 rounded-xl border border-ink-faint/60 bg-void/85 px-4 py-2 font-game text-meta text-ink-dim">
        <span>
          Not <span className="font-bold text-ink">{player}</span>? Type your name
        </span>
        {field}
        <kbd className="rounded border border-ink-faint px-2 py-0.5 text-ink">Enter</kbd>
        {status}
      </div>
    )
  }

  return (
    <div className="pointer-events-auto flex w-[min(46rem,90%)] flex-col items-center gap-4 rounded-2xl border border-ink/40 bg-void/90 px-8 py-6 text-center shadow-[0_0_60px_-10px_var(--color-ink)]">
      <p className="font-display text-title text-ink">{lead}</p>
      {field}
      <p className="font-game text-data text-ink-dim">
        Type your name, press <kbd className="rounded border border-ink-faint px-2 text-ink">Enter</kbd>
      </p>
      {status}
    </div>
  )
}

function Status({ entry }) {
  if (entry.status === 'error') {
    return <p className="font-game text-data text-critical">Didn't save. Press Enter again.</p>
  }
  if (entry.status === 'saved' && entry.savedName) {
    return <p className="anim-fade-in font-game text-data text-good">Locked in: {entry.savedName}</p>
  }
  return null
}
