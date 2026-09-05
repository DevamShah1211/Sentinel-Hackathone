import { useEffect, useState } from 'react'
import { BarChart2, Download, RefreshCw } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { getAnalyticsSummary, getTopPlates, getDetectionsByHour, downloadReport, saveBlob } from '../api/client'

interface Summary {
    cameras: { total: number; live: number; offline: number }
    detections: { total: number; last_24h: number; unique_plates_24h: number }
    alerts: { total: number; new: number }
    watchlist: { active_entries: number }
    generated_at: string
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <div>
                    <h1 style={{ fontSize: 22, fontWeight: 700 }}>Sentinel Command Centre</h1>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                        Gujarat CCTV Integration Hackathon 2026 · Model 1 + Model 2
                    </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
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
                        : <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>No data yet — start the ANPR worker</div>
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
                        : <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>No detections yet</div>
                    }
                </div>
            </div>

            {/* Platform info card */}
            <div className="card" style={{ marginTop: 16 }}>
                <div className="card-title">Platform Info</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, fontSize: 13 }}>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>BACKEND</div>
                        FastAPI + Python 3.11+<br />
                        <span style={{ color: 'var(--text-muted)' }}>uvicorn · SQLAlchemy async</span>
                    </div>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>DATABASE</div>
                        Supabase PostgreSQL + PostGIS<br />
                        <span style={{ color: 'var(--text-muted)' }}>pg_trgm fuzzy search · GeoJSON</span>
                    </div>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>STREAM</div>
                        HLS via hls.js · WHEP (WebRTC)<br />
                        <span style={{ color: 'var(--text-muted)' }}>Sentinel sandbox · RTSP/TCP</span>
                    </div>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>ANPR</div>
                        fast-alpr (ONNX) · Track-level voting<br />
                        <span style={{ color: 'var(--text-muted)' }}>Indian plate grammar correction</span>
                    </div>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>ALERTS</div>
                        WebSocket /ws/alerts · Real-time<br />
                        <span style={{ color: 'var(--text-muted)' }}>Exact + fuzzy watchlist matching</span>
                    </div>
                    <div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>GIS</div>
                        Leaflet · OpenStreetMap<br />
                        <span style={{ color: 'var(--text-muted)' }}>Route reconstruction · Haversine speed</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
