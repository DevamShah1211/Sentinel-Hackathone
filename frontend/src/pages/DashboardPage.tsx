import { useEffect, useState } from 'react'
import { BarChart2, Car, Download, RefreshCw } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { getAnalyticsSummary, getTopPlates, getDetectionsByHour, downloadReport, saveBlob } from '../api/client'

interface Summary {
    cameras: { total: number; live: number; offline: number }
    detections: { total: number; last_24h: number; unique_plates_24h: number }
    alerts: { total: number; new: number }
    watchlist: { active_entries: number }
    generated_at: string
}

function StatusRow({ label, value, tone }: {
    label: string; value: string; tone: 'ok' | 'warn' | 'alert'
}) {
    return (
        <div className="status-row">
            <span className={`status-dot ${tone}`} aria-hidden="true" />
            <div>
                <div className="status-row-label">{label}</div>
                <div className="status-row-value">{value}</div>
            </div>
        </div>
    )
}

export default function DashboardPage() {
    const [summary, setSummary] = useState<Summary | null>(null)
    const [topPlates, setTopPlates] = useState<{ plate_text: string; count: number }[]>([])
    const [hourly, setHourly] = useState<{ hour: string; count: number }[]>([])
    const [loading, setLoading] = useState(true)

    const load = async () => {
        setLoading(true)
        try {
            const [s, tp, h] = await Promise.all([getAnalyticsSummary(), getTopPlates(), getDetectionsByHour()])
            setSummary(s)
            setTopPlates(tp)
            setHourly(h.map((r: { hour: string; count: number }) => ({
                hour: new Date(r.hour).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
                count: r.count,
            })))
        } catch (_) { }
        finally { setLoading(false) }
    }

    useEffect(() => { load() }, [])

    const handleDownload = async (format: 'xlsx' | 'pdf') => {
        // Exports are audited; the purpose travels with the request.
        const blob = await downloadReport(format, {
            actor: 'operator', purpose: 'submission-artefact',
        })
        saveBlob(blob, `sentinel_anpr_report_${Date.now()}.${format}`)
    }

    if (loading) return <div className="page-content"><div className="loading-overlay"><div className="spinner" /><span>Loading dashboard…</span></div></div>

    return (
        <div className="page-content">
            <div className="page-head">
                <div>
                    <h1>Command Centre</h1>
                    <div className="page-sub">
                        Statewide camera registry and ANPR index · Model 1 + Model 2
                    </div>
                </div>
                <div className="page-head-actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload('xlsx')}><Download size={13} /> XLSX Report</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload('pdf')}><Download size={13} /> PDF Report</button>
                    <button className="btn btn-ghost btn-sm" onClick={load}><RefreshCw size={13} /></button>
                </div>
            </div>

            {/* Stat grid */}
            {summary && (
                <div className="stat-grid">
                    <div className="stat-card">
                        <div className="stat-label">Total Cameras</div>
                        <div className="stat-value blue">{summary.cameras.total}</div>
                        <div className="stat-sub">{summary.cameras.live} live · {summary.cameras.offline} offline</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Detections (24h)</div>
                        <div className="stat-value green">{summary.detections.last_24h.toLocaleString()}</div>
                        <div className="stat-sub">{summary.detections.unique_plates_24h} unique plates</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Total Detections</div>
                        <div className="stat-value">{summary.detections.total.toLocaleString()}</div>
                        <div className="stat-sub">All-time ANPR index</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">New Alerts</div>
                        <div className={`stat-value ${summary.alerts.new > 0 ? 'red' : 'green'}`}>{summary.alerts.new}</div>
                        <div className="stat-sub">{summary.alerts.total} total alerts</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Watchlist</div>
                        <div className="stat-value yellow">{summary.watchlist.active_entries}</div>
                        <div className="stat-sub">Active entries</div>
                    </div>
                </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                {/* Hourly detections */}
                <div className="card">
                    <div className="card-title">Detections per Hour — Last 24h</div>
                    {hourly.length > 0
                        ? (
                            <ResponsiveContainer width="100%" height={200}>
                                <BarChart data={hourly} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#243050" />
                                    <XAxis dataKey="hour" tick={{ fill: '#64748b', fontSize: 10 }} />
                                    <YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
                                    <Tooltip
                                        contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                                        labelStyle={{ color: 'var(--text-primary)' }}
                                        itemStyle={{ color: 'var(--accent)' }}
                                    />
                                    <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )
                        : (
                            <div className="empty-state" style={{ minHeight: 200, padding: '32px 16px' }}>
                                <div className="empty-state-icon"><BarChart2 size={22} /></div>
                                <div className="empty-state-title">No sightings in the last 24 hours</div>
                                <div className="empty-state-body">
                                    The index holds {summary?.detections.total ?? 0} detections in total.
                                    Run the ANPR worker against a live camera, or replay a clip, to populate this window.
                                </div>
                            </div>
                        )
                    }
                </div>

                {/* Top plates */}
                <div className="card">
                    <div className="card-title">Most Detected Plates</div>
                    {topPlates.length > 0
                        ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 200, overflowY: 'auto' }}>
                                {topPlates.slice(0, 10).map((p, i) => (
                                    <div key={p.plate_text} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                        <span style={{ color: 'var(--text-muted)', fontSize: 11, width: 16, textAlign: 'right' }}>{i + 1}</span>
                                        <span className="plate-chip" style={{ fontSize: 12 }}>{p.plate_text}</span>
                                        <div style={{ flex: 1, background: 'var(--bg-input)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                                            <div style={{ height: '100%', background: 'var(--accent)', borderRadius: 4, width: `${(p.count / topPlates[0].count) * 100}%` }} />
                                        </div>
                                        <span style={{ fontSize: 11, color: 'var(--text-secondary)', width: 28, textAlign: 'right' }}>{p.count}</span>
                                    </div>
                                ))}
                            </div>
                        )
                        : (
                            <div className="empty-state" style={{ minHeight: 200, padding: '32px 16px' }}>
                                <div className="empty-state-icon"><Car size={22} /></div>
                                <div className="empty-state-title">No plates indexed yet</div>
                                <div className="empty-state-body">Recognised plates appear here, most frequent first.</div>
                            </div>
                        )
                    }
                </div>
            </div>

            {/* System status. The stack list that used to sit here belongs in the
                README; an operator console should report on the deployment. */}
            <div className="card" style={{ marginTop: 16 }}>
                <div className="card-title">System Status</div>
                <div className="status-grid">
                    <StatusRow
                        label="Camera registry"
                        value={`${summary?.cameras.total ?? 0} cameras · ${summary?.cameras.live ?? 0} reachable`}
                        tone={(summary?.cameras.offline ?? 0) === 0 ? 'ok' : 'warn'}
                    />
                    <StatusRow
                        label="ANPR index"
                        value={`${(summary?.detections.total ?? 0).toLocaleString()} detections indexed`}
                        tone={(summary?.detections.total ?? 0) > 0 ? 'ok' : 'warn'}
                    />
                    <StatusRow
                        label="Watchlist"
                        value={`${summary?.watchlist.active_entries ?? 0} active · ${summary?.alerts.total ?? 0} alerts raised`}
                        tone={(summary?.alerts.new ?? 0) > 0 ? 'alert' : 'ok'}
                    />
                    <StatusRow
                        label="Audit trail"
                        value="Every search and export recorded with actor and purpose"
                        tone="ok"
                    />
                    <StatusRow
                        label="Access control"
                        value="Role enforced per route · state admin, operator, viewer"
                        tone="ok"
                    />
                    <StatusRow
                        label="Report generation"
                        value="XLSX and PDF available from this page"
                        tone="ok"
                    />
                </div>
            </div>
        </div>
    )
}
