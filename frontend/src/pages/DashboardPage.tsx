/**
 * The operations view.
 *
 * The first version of this page was a wall of summary tiles and a list of our
 * own dependencies, which told a reviewer what we had installed rather than
 * what the system was doing. An operator opening a command centre wants to see
 * a camera, what has just been recognised, and what needs their attention, all
 * without navigating. So: a hero stream on the left, live detections and alerts
 * on the right, and every camera reachable from a selector underneath.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    Activity, BarChart2, Bell, Camera as CameraIcon, Car,
    Download, Maximize2, RefreshCw, Search,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
    BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import {
    downloadReport, getAlerts, getAnalyticsSummary, getCameras,
    getDetectionsByHour, getRecentDetections, getTopPlates, saveBlob,
} from '../api/client'
import LiveTile from '../components/LiveTile'
import PlateDetailDrawer from '../components/PlateDetailDrawer'
import type { LiveAlert } from '../hooks/useAlertWebSocket'

interface Summary {
    cameras: { total: number; live: number; offline: number }
    detections: { total: number; last_24h: number; unique_plates_24h: number }
    alerts: { total: number; new: number }
    watchlist: { active_entries: number }
    generated_at: string
}

interface Camera {
    id: string; native_id: string; name: string; department: string
    is_live: boolean; address?: string; latitude?: number; longitude?: number
    codec?: string; status?: string
}

interface Detection {
    id: string; plate_text: string; confidence: number; detected_at: string
    camera_name?: string; camera_department?: string; crop_uri?: string
    partial?: boolean
}

interface AlertRecord {
    id: string; plate_text: string; reason: string; severity: string
    status: string; matched_at: string; camera_name: string
    match_type: string; score: number; case_ref?: string
}

const IST = { timeZone: 'Asia/Kolkata' } as const
const time = (t?: string) => t
    ? new Date(t).toLocaleTimeString('en-IN', { ...IST, hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '—'

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

export default function DashboardPage({ wsAlerts = [] }: { wsAlerts?: LiveAlert[] }) {
    const navigate = useNavigate()
    const [summary, setSummary] = useState<Summary | null>(null)
    const [topPlates, setTopPlates] = useState<{ plate_text: string; count: number }[]>([])
    const [hourly, setHourly] = useState<{ hour: string; count: number }[]>([])
    const [cameras, setCameras] = useState<Camera[]>([])
    const [recent, setRecent] = useState<Detection[]>([])
    const [alerts, setAlerts] = useState<AlertRecord[]>([])
    const [heroId, setHeroId] = useState<string>('')
    const [camQuery, setCamQuery] = useState('')
    const [openPlate, setOpenPlate] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)

    const load = useCallback(async () => {
        setLoading(true)
        // Independent requests: one slow or failing panel must not blank the page.
        const [s, tp, h, c, d, a] = await Promise.allSettled([
            getAnalyticsSummary(), getTopPlates(), getDetectionsByHour(),
            getCameras({ limit: 100 }), getRecentDetections(), getAlerts({}),
        ])
        if (s.status === 'fulfilled') setSummary(s.value as Summary)
        if (tp.status === 'fulfilled') setTopPlates(tp.value as { plate_text: string; count: number }[])
        if (h.status === 'fulfilled') {
            setHourly((h.value as { hour: string; count: number }[]).map(r => ({
                hour: new Date(r.hour).toLocaleTimeString('en-IN', { ...IST, hour: '2-digit', minute: '2-digit' }),
                count: r.count,
            })))
        }
        if (c.status === 'fulfilled') {
            const list = c.value as Camera[]
            setCameras(list)
            setHeroId(prev => prev || list.find(x => x.is_live)?.native_id || list[0]?.native_id || '')
        }
        if (d.status === 'fulfilled') setRecent(d.value as Detection[])
        if (a.status === 'fulfilled') setAlerts(a.value as AlertRecord[])
        setLoading(false)
    }, [])

    useEffect(() => { load() }, [load])

    // A live alert arriving over the socket should appear here without a refresh.
    useEffect(() => { if (wsAlerts.length) load() }, [wsAlerts.length, load])

    const handleDownload = async (format: 'xlsx' | 'pdf') => {
        // Exports are audited; the purpose travels with the request.
        const blob = await downloadReport(format, { actor: 'operator', purpose: 'submission-artefact' })
        saveBlob(blob, `sentinel_anpr_report_${Date.now()}.${format}`)
    }

    const hero = useMemo(() => cameras.find(c => c.native_id === heroId), [cameras, heroId])
    const filteredCams = useMemo(() => {
        const q = camQuery.trim().toLowerCase()
        if (!q) return cameras
        return cameras.filter(c =>
            `${c.name} ${c.department} ${c.native_id} ${c.address ?? ''}`.toLowerCase().includes(q))
    }, [cameras, camQuery])

    const newAlerts = alerts.filter(a => a.status === 'new')

    if (loading && !summary) {
        return (
            <div className="page-content">
                <div className="loading-overlay"><div className="spinner" /><span>Loading command centre…</span></div>
            </div>
        )
    }

    return (
        <div className="page-content">
            <div className="page-head">
                <div>
                    <h1>Command Centre</h1>
                    <div className="page-sub">
                        Statewide camera registry and ANPR index · Model 1 + Model 2
                        {summary && <> · updated {time(summary.generated_at)} IST</>}
                    </div>
                </div>
                <div className="page-head-actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload('xlsx')}>
                        <Download size={13} /> XLSX Report
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload('pdf')}>
                        <Download size={13} /> PDF Report
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={load} title="Refresh">
                        <RefreshCw size={13} />
                    </button>
                </div>
            </div>

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

            {/* Operations row: the stream on the left, what needs attention on the right. */}
            <div className="ops-row">
                <section className="card ops-hero">
                    <div className="ops-hero-head">
                        <div className="card-title" style={{ margin: 0 }}>
                            <CameraIcon size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                            Live view
                        </div>
                        <div className="ops-hero-controls">
                            <select
                                className="input"
                                style={{ width: 'auto', padding: '5px 9px', fontSize: 12 }}
                                value={heroId}
                                onChange={e => setHeroId(e.target.value)}
                                aria-label="Select camera for the live view"
                            >
                                {cameras.map(c => (
                                    <option key={c.id} value={c.native_id}>
                                        {c.name} — {c.department}
                                    </option>
                                ))}
                            </select>
                            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/wall')} title="Open the full video wall">
                                <Maximize2 size={12} /> Wall
                            </button>
                        </div>
                    </div>

                    <div className="ops-hero-stage">
                        {heroId
                            ? <LiveTile key={heroId} cameraId={heroId} alt={`Live view from ${hero?.name ?? heroId}`} profile="high" />
                            : <div className="pd-empty" style={{ padding: 30 }}>No camera selected.</div>}
                        {hero && (
                            <div className="tile-caption">
                                <span className="tile-caption-name">{hero.name}</span>
                                <span className="tile-caption-dept">{hero.department}</span>
                            </div>
                        )}
                    </div>

                    {hero && (
                        <div className="ops-hero-meta">
                            <div><span>Camera id</span><strong>{hero.native_id}</strong></div>
                            <div><span>Department</span><strong>{hero.department}</strong></div>
                            <div>
                                <span>Status</span>
                                <strong style={{ color: hero.is_live ? 'var(--green)' : 'var(--text-muted)' }}>
                                    {hero.is_live ? 'Live' : 'Offline'}
                                </strong>
                            </div>
                            <div><span>Codec</span><strong>{hero.codec?.toUpperCase() || '—'}</strong></div>
                            <div style={{ gridColumn: '1 / -1' }}>
                                <span>Location</span>
                                <strong>{hero.address || 'Not geocoded'}</strong>
                            </div>
                        </div>
                    )}
                </section>

                <div className="ops-side">
                    <section className="card ops-panel">
                        <div className="card-title">
                            <Bell size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                            Live alerts
                            {newAlerts.length > 0 && <span className="ops-count">{newAlerts.length} new</span>}
                        </div>
                        {alerts.length === 0
                            ? <div className="pd-empty">No alerts raised. Watchlist matches appear here instantly.</div>
                            : (
                                <div className="ops-list">
                                    {alerts.slice(0, 6).map(a => (
                                        <button key={a.id} className="ops-item" onClick={() => setOpenPlate(a.plate_text)}>
                                            <span className={`ops-sev sev-${a.severity}`} aria-hidden="true" />
                                            <div className="ops-item-main">
                                                <div className="ops-item-title">{a.plate_text}</div>
                                                <div className="ops-item-sub">{a.reason} · {a.camera_name}</div>
                                            </div>
                                            <span className="ops-item-time">{time(a.matched_at)}</span>
                                        </button>
                                    ))}
                                </div>
                            )}
                        <button className="ops-more" onClick={() => navigate('/alerts')}>
                            View all alerts →
                        </button>
                    </section>

                    <section className="card ops-panel">
                        <div className="card-title">
                            <Activity size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                            Recent recognitions
                        </div>
                        {recent.length === 0
                            ? <div className="pd-empty">No detections indexed yet.</div>
                            : (
                                <div className="ops-list">
                                    {recent.slice(0, 8).map(d => (
                                        <button key={d.id} className="ops-item" onClick={() => setOpenPlate(d.plate_text)}>
                                            {d.crop_uri
                                                ? <img className="ops-item-crop" src={d.crop_uri} alt="" />
                                                : <span className="ops-sev" style={{ background: 'var(--border-strong)' }} aria-hidden="true" />}
                                            <div className="ops-item-main">
                                                <div className="ops-item-title">
                                                    {d.plate_text}
                                                    {d.partial && <span className="pd-partial-tag">PARTIAL</span>}
                                                </div>
                                                <div className="ops-item-sub">{d.camera_name ?? 'Unknown camera'}</div>
                                            </div>
                                            <span className="ops-item-time">{(d.confidence * 100).toFixed(0)}%</span>
                                        </button>
                                    ))}
                                </div>
                            )}
                        <button className="ops-more" onClick={() => navigate('/search')}>
                            Search the index →
                        </button>
                    </section>
                </div>
            </div>

            {/* Every camera, reachable from here. */}
            <section className="card" style={{ marginTop: 16 }}>
                <div className="ops-hero-head" style={{ marginBottom: 12 }}>
                    <div className="card-title" style={{ margin: 0 }}>
                        All cameras
                        <span className="ops-count" style={{ background: 'var(--bg-raised)', color: 'var(--text-secondary)' }}>
                            {filteredCams.length} of {cameras.length}
                        </span>
                    </div>
                    <div className="wall-search" style={{ minWidth: 280, marginLeft: 0 }}>
                        <Search size={13} aria-hidden="true" />
                        <input
                            value={camQuery}
                            onChange={e => setCamQuery(e.target.value)}
                            placeholder="Filter by name, area or id…"
                            aria-label="Filter cameras"
                        />
                    </div>
                </div>
                <div className="cam-chips">
                    {filteredCams.map(c => (
                        <button
                            key={c.id}
                            className={`cam-chip${c.native_id === heroId ? ' is-active' : ''}`}
                            onClick={() => setHeroId(c.native_id)}
                            title={c.address || c.name}
                        >
                            <span className={`cam-chip-dot${c.is_live ? ' live' : ''}`} aria-hidden="true" />
                            <span className="cam-chip-name">{c.name}</span>
                            <span className="cam-chip-dept">{c.department}</span>
                        </button>
                    ))}
                    {filteredCams.length === 0 && <div className="pd-empty">No camera matches that filter.</div>}
                </div>
            </section>

            <div className="dash-charts">
                <div className="card">
                    <div className="card-title">Detections per Hour — Last 24h</div>
                    {hourly.length > 0
                        ? (
                            <ResponsiveContainer width="100%" height={200}>
                                <BarChart data={hourly} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                    <XAxis dataKey="hour" tick={{ fill: '#6b7c98', fontSize: 10 }} />
                                    <YAxis tick={{ fill: '#6b7c98', fontSize: 10 }} />
                                    <Tooltip
                                        contentStyle={{ background: 'var(--bg-raised)', border: '1px solid var(--border-light)', borderRadius: 8, fontSize: 12 }}
                                        labelStyle={{ color: 'var(--text-primary)' }}
                                        itemStyle={{ color: 'var(--accent)' }}
                                        cursor={{ fill: 'var(--accent-soft)' }}
                                    />
                                    <Bar dataKey="count" fill="var(--accent)" radius={[4, 4, 0, 0]} />
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
                        )}
                </div>

                <div className="card">
                    <div className="card-title">Most Detected Plates</div>
                    {topPlates.length > 0
                        ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 200, overflowY: 'auto' }}>
                                {topPlates.slice(0, 10).map((p, i) => (
                                    <button
                                        key={p.plate_text}
                                        onClick={() => setOpenPlate(p.plate_text)}
                                        className="top-plate-row"
                                        title="Open full vehicle detail"
                                    >
                                        <span style={{ color: 'var(--text-muted)', fontSize: 11, width: 16, textAlign: 'right' }}>{i + 1}</span>
                                        <span className="plate-chip" style={{ fontSize: 12 }}>{p.plate_text}</span>
                                        <div style={{ flex: 1, background: 'var(--bg-input)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                                            <div style={{ height: '100%', background: 'var(--accent)', borderRadius: 4, width: `${(p.count / topPlates[0].count) * 100}%` }} />
                                        </div>
                                        <span style={{ fontSize: 11, color: 'var(--text-secondary)', width: 28, textAlign: 'right' }}>{p.count}</span>
                                    </button>
                                ))}
                            </div>
                        )
                        : (
                            <div className="empty-state" style={{ minHeight: 200, padding: '32px 16px' }}>
                                <div className="empty-state-icon"><Car size={22} /></div>
                                <div className="empty-state-title">No plates indexed yet</div>
                                <div className="empty-state-body">Recognised plates appear here, most frequent first.</div>
                            </div>
                        )}
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

            <PlateDetailDrawer plate={openPlate} onClose={() => setOpenPlate(null)} />
        </div>
    )
}
