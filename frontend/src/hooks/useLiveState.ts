// Live PEA state over the WebSocket (backend/orchestrion/api/live.py).
// Opens /api/peas/{id}/ws, holds the latest decoded state + enabled commands per
// service, and reports the connection status. One socket per mounted PEA view.

import { useEffect, useRef, useState } from 'react'
import type { LiveMessage, LiveValue, LogEvent, ValueMeta } from '../api/types'

export type LiveStatus = 'connecting' | 'live' | 'error' | 'closed'

export interface LiveState {
  status: LiveStatus
  error: string | null
  states: Record<string, string> // service -> ServiceState name
  commandEn: Record<string, string[]> // service -> enabled Command names
  values: Record<string, LiveValue> // value TagName -> current reading
  valueMeta: Record<string, ValueMeta> // value TagName -> scaling/unit (static)
  events: LogEvent[] // the event log, oldest first (M4)
}

const CLOSED: LiveState = { status: 'closed', error: null, states: {}, commandEn: {}, values: {}, valueMeta: {}, events: [] }
const CONNECTING: LiveState = { status: 'connecting', error: null, states: {}, commandEn: {}, values: {}, valueMeta: {}, events: [] }

export function useLiveState(peaId: number | null, enabled: boolean): LiveState {
  const [live, setLive] = useState<LiveState>(CLOSED)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Not connected (no PEA, or the user disconnected) -> 'closed', never 'connecting'.
    if (peaId === null || !enabled) {
      setLive(CLOSED)
      return
    }
    // Only now, while actually opening a socket, are we 'connecting'.
    setLive(CONNECTING)

    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${scheme}://${location.host}/api/peas/${peaId}/ws`)
    socketRef.current = ws

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as LiveMessage
      setLive((prev) => {
        if (msg.type === 'snapshot') {
          // The log_snapshot arrives right after; keep prev.events until it replaces them.
          return {
            status: 'live',
            error: null,
            states: msg.states,
            commandEn: msg.command_en,
            values: msg.values,
            valueMeta: msg.value_meta,
            events: prev.events,
          }
        }
        if (msg.type === 'log_snapshot') {
          return { ...prev, events: msg.events }
        }
        if (msg.type === 'log') {
          const event: LogEvent = {
            timestamp: msg.timestamp,
            kind: msg.kind,
            message: msg.message,
            detail: msg.detail,
          }
          return { ...prev, events: [...prev.events, event] }
        }
        if (msg.type === 'update') {
          if ('name' in msg) {
            return { ...prev, values: { ...prev.values, [msg.name]: msg.value } }
          }
          const states = msg.state ? { ...prev.states, [msg.service]: msg.state } : prev.states
          const commandEn = msg.command_en
            ? { ...prev.commandEn, [msg.service]: msg.command_en }
            : prev.commandEn
          return { ...prev, states, commandEn }
        }
        if (msg.type === 'error') {
          return { ...prev, status: 'error', error: msg.detail }
        }
        // Unknown message type — ignore it rather than treating it as an error.
        return prev
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
