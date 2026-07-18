// Live PEA state over the WebSocket (backend/orchestrion/api/live.py).
// Opens /api/peas/{id}/ws, holds the latest decoded state + enabled commands per
// service, and reports the connection status. One socket per mounted PEA view.

import { useEffect, useRef, useState } from 'react'
import type { LiveMessage } from '../api/types'

export type LiveStatus = 'connecting' | 'live' | 'error' | 'closed'

export interface LiveState {
  status: LiveStatus
  error: string | null
  states: Record<string, string> // service -> ServiceState name
  commandEn: Record<string, string[]> // service -> enabled Command names
}

const INITIAL: LiveState = { status: 'connecting', error: null, states: {}, commandEn: {} }

export function useLiveState(peaId: number | null, enabled: boolean): LiveState {
  const [live, setLive] = useState<LiveState>(INITIAL)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (peaId === null || !enabled) {
      setLive(INITIAL)
      return
    }
    setLive(INITIAL)

    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${scheme}://${location.host}/api/peas/${peaId}/ws`)
    socketRef.current = ws

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as LiveMessage
      setLive((prev) => {
        if (msg.type === 'snapshot') {
          return { status: 'live', error: null, states: msg.states, commandEn: msg.command_en }
        }
        if (msg.type === 'update') {
          const states = msg.state ? { ...prev.states, [msg.service]: msg.state } : prev.states
          const commandEn = msg.command_en
            ? { ...prev.commandEn, [msg.service]: msg.command_en }
            : prev.commandEn
          return { ...prev, states, commandEn }
        }
        // error
        return { ...prev, status: 'error', error: msg.detail }
      })
    }
    ws.onerror = () =>
      setLive((prev) => (prev.status === 'live' ? prev : { ...prev, status: 'error' }))
    ws.onclose = () =>
      setLive((prev) =>
        prev.status === 'error' ? prev : { ...prev, status: 'closed' },
      )

    return () => {
      ws.onmessage = ws.onerror = ws.onclose = null
      ws.close()
      socketRef.current = null
    }
  }, [peaId, enabled])

  return live
}
