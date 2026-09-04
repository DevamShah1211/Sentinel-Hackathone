import { useEffect, useState } from 'react'
import type { LiveAlert } from '../hooks/useAlertWebSocket'

interface Props {
    alert: LiveAlert
    onClose: () => void
}

export default function Toast({ alert, onClose }: Props) {
    useEffect(() => {
        const t = setTimeout(onClose, 8000)
        return () => clearTimeout(t)
    }, [onClose])

    const sevColor = alert.severity === 'critical' ? 'var(--red)'
        : alert.severity === 'high' ? 'var(--yellow)'
            : 'var(--accent)'

    return (
        <div className="toast" style={{ borderColor: sevColor, boxShadow: `0 0 20px ${sevColor}30` }}>
            <div className="toast-title" style={{ color: sevColor }}>
                🚨 WATCHLIST ALERT — {alert.reason?.toUpperCase()}
            </div>
            <div className="toast-plate">{alert.plate_text}</div>
            <div className="toast-body">
                {alert.match_type === 'fuzzy' ? '(fuzzy match) ' : ''}
                Score: {(alert.score * 100).toFixed(0)}%
                {alert.case_ref ? ` · Case: ${alert.case_ref}` : ''}
            </div>
            <div style={{ marginTop: 6, display: 'flex', justifyContent: 'flex-end' }}>
                <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12 }}>
                    Dismiss
                </button>
            </div>
        </div>
    )
}
