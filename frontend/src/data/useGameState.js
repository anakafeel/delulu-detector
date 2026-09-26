import { useEffect, useState } from 'react'
import { subscribe } from './dataSource'

const EMPTY_STATE = {
  screen: 'idle',
  player: null,
  activeRound: null,
  liveClaim: null,
  latestResult: null,
  history: [],
}

export function useGameState() {
  const [state, setState] = useState(EMPTY_STATE)

  useEffect(() => {
    const unsubscribe = subscribe(setState)
    return unsubscribe
  }, [])

  return state
}
