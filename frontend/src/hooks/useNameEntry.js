import { useCallback, useEffect, useState } from 'react'
import { submitPlayerName } from '../data/dataSource'

const SAVED_MS = 2500

// Poker Face with the browser UI: the player types their name on the booth
// keyboard before dialing. One field, Enter to lock it in. The draft lives in App
// (this hook), so it survives the screen crossfade between idle and the dial.
export function useNameEntry() {
  const [draft, setDraft] = useState('')
  const [status, setStatus] = useState(null)      // null | 'saving' | 'saved' | 'error'
  const [savedName, setSavedName] = useState(null)

  useEffect(() => {
    if (status !== 'saved') return undefined
    const t = setTimeout(() => setStatus(null), SAVED_MS)
    return () => clearTimeout(t)
  }, [status])

  const submit = useCallback(() => {
    const name = draft.replace(/\s+/g, ' ').trim()
    if (!name || status === 'saving') return
    setStatus('saving')
    submitPlayerName(name)
      .then((saved) => {
        setSavedName(saved)
        setDraft('')
        setStatus('saved')
      })
      .catch(() => setStatus('error'))
  }, [draft, status])

  return { draft, setDraft, submit, status, savedName }
}

