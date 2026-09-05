import { useEffect, useRef, useState, useCallback } from 'react'

export interface LiveAlert {
    alert_id: string
    plate_text: string
    match_type: string
    score: number
    reason: string
    severity: string
    case_ref?: string
    camera_id: string
    detected_at: string
    crop_uri?: string
    matched_at: string
}

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/alerts`

export type WsStatus = 'connecting' | 'live' | 'reconnecting'

export function useAlertWebSocket() {
    const [alerts, setAlerts] = useState<LiveAlert[]>([])
    const [connected, setConnected] = useState(false)
    // Distinguish the first connect from a dropped one, so the indicator does not
    // read "RECONNECTING" during the second it takes to open on page load.
    const [status, setStatus] = useState<WsStatus>('connecting')
    const ws = useRef<WebSocket | null>(null)
    const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()
    const backoff = useRef(2000)

    const connect = useCallback(() => {
        ws.current = new WebSocket(WS_URL)

        ws.current.onopen = () => {
            setConnected(true)
            setStatus('live')
            backoff.current = 2000
        }

        ws.current.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data)
                if (msg.type === 'alert') {
                    setAlerts(prev => [msg.data as LiveAlert, ...prev.slice(0, 99)])
                }
            } catch (_) { }
        }

        ws.current.onclose = () => {
            setConnected(false)
            setStatus(prev => (prev === 'connecting' ? 'connecting' : 'reconnecting'))
            backoff.current = Math.min(backoff.current * 2, 30000)
            reconnectTimer.current = setTimeout(connect, backoff.current)
        }

        ws.current.onerror = () => {
            ws.current?.close()
        }
    }, [])

    useEffect(() => {
        connect()
        // Keep-alive ping every 25s
        const ping = setInterval(() => {
            if (ws.current?.readyState === WebSocket.OPEN) {
                ws.current.send(JSON.stringify({ action: 'ping' }))
            }
        }, 25000)
        return () => {
            clearInterval(ping)
            clearTimeout(reconnectTimer.current)
            ws.current?.close()
        }
    }, [connect])

    const clearAlert = useCallback((alertId: string) => {
        setAlerts(prev => prev.filter(a => a.alert_id !== alertId))
    }, [])

    return { alerts, connected, status, clearAlert }
}
