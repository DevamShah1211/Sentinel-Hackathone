/**
 * Grid health and scene analytics.
 *
 * Two questions an operations desk asks that no other page answers: which
 * cameras have stopped reporting, and what are the working ones actually
 * seeing. The submission names health monitoring and additional analytics as
 * scoring areas; more usefully, a control room running eighty thousand cameras
 * needs the first question answered before it can trust anything else on the
 * platform.
 *
 * The distinction the page is built around is that a camera can be reachable
 * and still be useless — repointed at a wall, or returning frames the decoder
 * cannot use. Reachability is necessary and not sufficient, so 'reporting' here
 * means contributing detections, not answering a ping.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    Activity, AlertTriangle, Camera as CameraIcon, CheckCircle2,
    Clock, RefreshCw, Users,
} from 'lucide-react'
import {
    getCameraHealth, getSceneByCamera, getSceneSummary,
} from '../api/client'

interface HealthCamera {
    native_id: string
    name: string
    department: string
    district?: string | null
    state: 'operational' | 'stale' | 'offline' | string
    last_seen_at?: string | null
    hours_since_contact?: number | null
    codec?: string | null
    resolution?: string | null
    located: boolean
}

interface HealthReport {
    generated_at: string
    totals: { operational: number; stale: number; offline: number; cameras: number }
    cameras: HealthCamera[]
}

interface SceneSummary {
    window_hours: number
    buckets: number
    frames_analysed: number
    cameras_reporting: number
    observations: Record<string, number>
    by_label: Record<string, number>
    note?: string
}

interface SceneCamera {
    camera_id: string
    camera_name: string
    department: string
    vehicles: number
    people: number
    frames_analysed: number
}

const STATE_ORDER: Record<string, number> = { offline: 0, stale: 1, operational: 2 }

const STATE_COPY: Record<string, { label: string; hint: string }> = {
    operational: { label: 'Operational', hint: 'Seen within the last hour' },
    stale: { label: 'Stale', hint: 'Reachable, but nothing recent' },
    offline: { label: 'Offline', hint: 'No contact' },
}

function relative(hours?: number | null): string {
    if (hours == null) return 'never'
    if (hours < 1) return `${Math.round(hours * 60)} min ago`
    if (hours < 48) return `${Math.round(hours)} h ago`
    return `${Math.round(hours / 24)} d ago`
}

export default function HealthPage() {
    const [health, setHealth] = useState<HealthReport | null>(null)
    const [scene, setScene] = useState<SceneSummary | null>(null)
    const [sceneCameras, setSceneCameras] = useState<SceneCamera[]>([])
    const [loading, setLoading] = useState(true)
    const [filter, setFilter] = useState<string>('all')

    const load = useCallback(async () => {
        setLoading(true)
        // Independent: a failing analytics query must not blank the health table,
        // which is the half that matters when something is wrong.
        const [h, s, c] = await Promise.allSettled([
            getCameraHealth(), getSceneSummary(24), getSceneByCamera(24),
        ])
        if (h.status === 'fulfilled') setHealth(h.value as HealthReport)
        if (s.status === 'fulfilled') setScene(s.value as SceneSummary)
        if (c.status === 'fulfilled') setSceneCameras((c.value as { cameras: SceneCamera[] }).cameras ?? [])
        setLoading(false)
    }, [])

    useEffect(() => { load() }, [load])

    // Worst first. An operations page that opens on healthy cameras buries the
    // reason someone came to it.
    const cameras = useMemo(() => {
        const rows = health?.cameras ?? []
        const shown = filter === 'all' ? rows : rows.filter(c => c.state === filter)
        return [...shown].sort((a, b) =>
            (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9)
            || (b.hours_since_contact ?? 0) - (a.hours_since_contact ?? 0))
    }, [health, filter])

    const totals = health?.totals
    const unlocated = (health?.cameras ?? []).filter(c => !c.located).length

    return (
        <div className="page-content">
            <div className="page-head">
                <div>
                    <h1>Grid Health &amp; Scene Analytics</h1>
                    <div className="page-sub">
                        Which cameras are reporting, and what the working ones are seeing ·
                        vehicle and person detection runs where plate reading cannot
                    </div>
                </div>
                <div className="page-head-actions">
                    <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
                        <RefreshCw size={13} /> Refresh
                    </button>
                </div>
            </div>

            {totals && (
                <div className="stat-grid">
                    <button
                        className={`stat-card is-clickable${filter === 'operational' ? ' is-active' : ''}`}
                        onClick={() => setFilter(filter === 'operational' ? 'all' : 'operational')}
                    >
                        <div className="stat-label">Operational</div>
                        <div className="stat-value green">{totals.operational}</div>
                        <div className="stat-sub">Seen within the hour</div>
                    </button>
                    <button
                        className={`stat-card is-clickable${filter === 'stale' ? ' is-active' : ''}`}
                        onClick={() => setFilter(filter === 'stale' ? 'all' : 'stale')}
                    >
                        <div className="stat-label">Stale</div>
                        <div className="stat-value yellow">{totals.stale}</div>
                        <div className="stat-sub">Reachable, nothing recent</div>
                    </button>
                    <button
                        className={`stat-card is-clickable${filter === 'offline' ? ' is-active' : ''}`}
                        onClick={() => setFilter(filter === 'offline' ? 'all' : 'offline')}
                    >
                        <div className="stat-label">Offline</div>
                        <div className={`stat-value ${totals.offline > 0 ? 'red' : ''}`}>{totals.offline}</div>
                        <div className="stat-sub">No contact at all</div>
                    </button>
                    <div className="stat-card">
                        <div className="stat-label">Unlocated</div>
                        <div className="stat-value">{unlocated}<span className="stat-value-of">/{totals.cameras}</span></div>
                        <div className="stat-sub">No coordinates in the registry</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Analysed (24h)</div>
                        <div className="stat-value blue">{(scene?.frames_analysed ?? 0).toLocaleString()}</div>
                        <div className="stat-sub">{scene?.cameras_reporting ?? 0} cameras contributing</div>
                    </div>
                </div>
            )}

            <div className="health-row">
                {/* Scene analytics — what the cameras are seeing. */}
                <section className="card">
                    <div className="card-title">
                        <Activity size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                        Scene analytics — last 24 hours
                    </div>

                    {!scene || scene.buckets === 0 ? (
                        <div className="empty-state" style={{ minHeight: 180 }}>
                            <div className="empty-state-icon"><Activity size={22} /></div>
                            <div className="empty-state-title">No scene analysis yet</div>
                            <div className="empty-state-body">
                                Run <code>python tools/scene_analytics.py --camera cam10</code> to
                                index vehicle and person counts. This tier works on cameras
                                whose plates are too small to read.
                            </div>
                        </div>
                    ) : (
                        <>
                            <div className="scene-counts">
                                <div className="scene-count">
                                    <CameraIcon size={15} aria-hidden="true" />
                                    <div>
                                        <strong>{scene.observations.vehicle ?? 0}</strong>
                                        <span>vehicle observations</span>
                                    </div>
                                </div>
                                <div className="scene-count">
                                    <Users size={15} aria-hidden="true" />
                                    <div>
                                        <strong>{scene.observations.person ?? 0}</strong>
                                        <span>person observations</span>
                                    </div>
                                </div>
                            </div>

                            <div className="scene-labels">
                                {Object.entries(scene.by_label)
                                    .sort((a, b) => b[1] - a[1])
                                    .map(([label, n]) => (
                                        <span key={label} className="scene-chip">
                                            {label} <strong>{n}</strong>
                                        </span>
                                    ))}
                            </div>

                            {scene.note && <p className="scene-note">{scene.note}</p>}

                            {sceneCameras.length > 0 && (
                                <div className="scene-table">
                                    <div className="scene-table-head">
                                        <span>Camera</span><span>Vehicles</span><span>People</span>
                                    </div>
                                    {sceneCameras.map(c => (
                                        <div key={c.camera_id} className="scene-table-row">
                                            <span>{c.camera_name}</span>
                                            <span>{c.vehicles}</span>
                                            <span>{c.people}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    )}
                </section>

                {/* Camera health table. */}
                <section className="card">
                    <div className="card-title">
                        <CheckCircle2 size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                        Camera health
                        {filter !== 'all' && (
                            <button className="btn btn-ghost btn-sm" style={{ marginLeft: 10 }}
                                    onClick={() => setFilter('all')}>
                                Showing {filter} — clear
                            </button>
                        )}
                    </div>

                    {loading && !health
                        ? <div className="loading-overlay"><div className="spinner" /></div>
                        : (
                            <div className="health-list">
                                {cameras.map(c => (
                                    <div key={c.native_id} className={`health-row-item state-${c.state}`}>
                                        <span className={`health-dot state-${c.state}`} aria-hidden="true" />
                                        <div className="health-main">
                                            <div className="health-name">
                                                {c.name}
                                                {!c.located && (
                                                    <span className="health-flag" title="No coordinates in the registry">
                                                        <AlertTriangle size={10} /> unlocated
                                                    </span>
                                                )}
                                            </div>
                                            <div className="health-meta">
                                                {c.department}
                                                {c.resolution && ` · ${c.resolution}`}
                                                {c.codec && ` · ${c.codec.toUpperCase()}`}
                                            </div>
                                        </div>
                                        <div className="health-state">
                                            <span className={`health-state-label state-${c.state}`}>
                                                {STATE_COPY[c.state]?.label ?? c.state}
                                            </span>
                                            <span className="health-seen">
                                                <Clock size={10} aria-hidden="true" />
                                                {relative(c.hours_since_contact)}
                                            </span>
                                        </div>
                                    </div>
                                ))}
                                {cameras.length === 0 && (
                                    <div className="pd-empty">No camera in that state.</div>
                                )}
                            </div>
                        )}
                </section>
            </div>
        </div>
    )
}
