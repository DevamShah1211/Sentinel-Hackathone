import { useEffect, useState } from 'react'
import { Bell, Check, CheckCheck, RefreshCw } from 'lucide-react'
import { getAlerts, acknowledgeAlert, resolveAlert } from '../api/client'
import type { LiveAlert } from '../hooks/useAlertWebSocket'

interface AlertRecord {
    id: string; watchlist_id: string; detection_id: string;
    matched_at: string; match_type: string; score: number; status: string;
    acknowledged_by?: string; acknowledged_at?: string; notes?: string;
    plate_text: string; reason: string; severity: string; case_ref?: string;
    camera_name: string; camera_id: string; crop_uri?: string; detected_at?: string;
}

function SeverityIcon({ sev }: { sev: string }) {
    const map: Record<string, string> = { critical: '🔴', high: '🟠', medium: '🟡', low: '⚪' }
    return <span>{map[sev] || '⚪'}</span>
}

function AlertRow({ a, onAck, onResolve }: { a: AlertRecord; onAck: (id: string) => void; onResolve: (id: string) => void }) {
    const sevClass = `sev-${a.severity}`
    return (
        <div className={`alert-item ${a.status}`}>
            <div className={`alert-icon ${a.severity}`}>
                <SeverityIcon sev={a.severity} />
            </div>
            <div className="alert-body">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="plate-chip">{a.plate_text}</span>
                    <span className={`badge-pill ${a.severity === 'critical' ? 'pill-red' : a.severity === 'high' ? 'pill-yellow' : 'pill-blue'}`}>
                        {a.reason}
                    </span>
                    <span className={`badge-pill ${a.match_type === 'exact' ? 'pill-green' : 'pill-purple'}`}>
                        {a.match_type} {(a.score * 100).toFixed(0)}%
                    </span>
                    {a.case_ref && <span className="badge-pill pill-gray">Case: {a.case_ref}</span>}
                </div>
                <div className="alert-meta" style={{ marginTop: 6 }}>
                    📷 {a.camera_name} &nbsp;·&nbsp;
                    🕐 {new Date(a.matched_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST
                    {a.acknowledged_by && <span> &nbsp;·&nbsp; ✅ Ack by {a.acknowledged_by}</span>}
                </div>
            </div>
            {a.crop_uri && <img src={a.crop_uri} alt="crop" style={{ width: 64, height: 40, objectFit: 'cover', borderRadius: 4, border: '1px solid var(--border-light)', flexShrink: 0 }} />}
            <div className="alert-actions">
                {a.status === 'new' && (
                    <button className="btn btn-ghost btn-sm" onClick={() => onAck(a.id)} title="Acknowledge">
                        <Check size={12} />
                    </button>
                )}
                {a.status !== 'resolved' && (
                    <button className="btn btn-ghost btn-sm" onClick={() => onResolve(a.id)} title="Resolve"
                        style={{ color: 'var(--green)' }}>
                        <CheckCheck size={12} />
                    </button>
                )}
            </div>
        </div>
    )
}

interface Props {
    wsAlerts: LiveAlert[]
}

export default function AlertsPage({ wsAlerts }: Props) {
    const [dbAlerts, setDbAlerts] = useState<AlertRecord[]>([])
    const [loading, setLoading] = useState(true)
    const [statusFilter, setStatusFilter] = useState<string>('all')

    const load = async () => {
        setLoading(true)
        try {
            const params: Record<string, string> = {}
            if (statusFilter !== 'all') params.status = statusFilter
            const data = await getAlerts(params)
            setDbAlerts(data)
        } finally { setLoading(false) }
    }

    useEffect(() => { load() }, [statusFilter])

    // Merge live WS alerts with DB alerts (WS alerts appear at the top)
    const newAlertIds = new Set(dbAlerts.map(a => a.id))

    const handleAck = async (id: string) => {
        await acknowledgeAlert(id, 'operator')
        load()
    }
    const handleResolve = async (id: string) => {
        await resolveAlert(id)
        load()
    }

    const newCount = dbAlerts.filter(a => a.status === 'new').length

    return (
        <div className="page-content">
            <div className="section-header">
                <div>
                    <h1 style={{ fontSize: 20, fontWeight: 700 }}>Live Alerts</h1>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                        Real-time watchlist matches via WebSocket · Newest first
                    </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {newCount > 0 && (
                        <div className="live-indicator" style={{ gap: 6 }}>
                            <div className="pulse-dot" />
                            {newCount} new
                        </div>
                    )}
                    <select className="input" style={{ width: 'auto', padding: '6px 10px' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                        <option value="all">All Status</option>
                        <option value="new">New</option>
                        <option value="ack">Acknowledged</option>
                        <option value="resolved">Resolved</option>
                    </select>
                    <button className="btn btn-ghost btn-sm" onClick={load}>
                        <RefreshCw size={12} />
                    </button>
                </div>
            </div>

            {loading
                ? <div className="loading-overlay"><div className="spinner" /></div>
                : dbAlerts.length === 0
                    ? (
                        <div className="empty-state">
                            <Bell size={40} />
                            <p>No alerts yet</p>
                            <p style={{ fontSize: 12 }}>Watchlist matches will appear here in real-time</p>
                        </div>
                    )
                    : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            {dbAlerts.map(a => (
                                <AlertRow key={a.id} a={a} onAck={handleAck} onResolve={handleResolve} />
                            ))}
                        </div>
                    )
            }
        </div>
    )
}
