import { useCallback, useEffect, useState } from 'react'
import { submitPlayerName } from '../data/dataSource'

const SAVED_MS = 2500

// Poker Face with the browser UI: the player types their name on the booth
// keyboard before dialing, presses Enter, then Y or N to an opt-in leaderboard photo.
// The draft lives in App (this hook), so it survives the screen crossfade.
export function useNameEntry() {
  const [draft, setDraft] = useState('')
  const [status, setStatus] = useState(null)      // null | 'saving' | 'saved' | 'error'
  const [savedName, setSavedName] = useState(null)
  const [asking, setAsking] = useState(null)       // the name waiting for the photo Y / N

  useEffect(() => {
    if (status !== 'saved') return undefined
    const t = setTimeout(() => setStatus(null), SAVED_MS)
    return () => clearTimeout(t)
  }, [status])

  // Enter: ask about the photo first; nothing is sent until the Y / N.
  const submit = useCallback(() => {
    const name = draft.replace(/\s+/g, ' ').trim()
    if (!name || status === 'saving') return
    setAsking(name)
  }, [draft, status])

  const answer = useCallback(
    (photo) => {
      if (!asking || status === 'saving') return
      setStatus('saving')
      submitPlayerName(asking, photo === true)
        .then((saved) => {
          setSavedName(saved)
          setDraft('')
          setAsking(null)
          setStatus('saved')
        })
        .catch(() => setStatus('error'))
    },
    [asking, status],
  )

  const cancel = useCallback(() => setAsking(null), [])

  return { draft, setDraft, submit, status, savedName, asking, answer, cancel }
}

