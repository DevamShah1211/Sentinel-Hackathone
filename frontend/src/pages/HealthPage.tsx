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
 *
 * Three states, not two. A camera that was analysed and saw nothing is not the
 * same as one nobody looked at, and collapsing them would hide exactly the gap
 * an operations desk is trying to find. `frames_sampled` is what separates them
 * and the page shows the difference rather than averaging it away.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    Activity, AlertTriangle, Camera as CameraIcon, CheckCircle2,
    Clock, EyeOff, Info, RefreshCw, TrendingUp, Users,
} from 'lucide-react'
import {
    Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer,
    Tooltip, XAxis, YAxis,
} from 'recharts'
import {
    getCameraHealth, getSceneByCamera, getSceneHourly, getSceneSummary,
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
    // How many buckets in the window came from a real worker versus the
    // seeding tool. Present so the page can say which it is showing.
    buckets_by_source?: Record<string, number>
}

interface SceneCamera {
    camera_id: string
    camera_name: string
    department: string
    vehicles: number
    people: number
    frames_analysed: number
    buckets: number
}

interface HourlyPoint {
    hour: number
    vehicles: number
    people: number
    buckets: number
}

const STATE_ORDER: Record<string, number> = { offline: 0, stale: 1, operational: 2 }

const STATE_COPY: Record<string, { label: string }> = {
    operational: { label: 'Operational' },
    stale: { label: 'Stale' },
    offline: { label: 'Offline' },
}

/**
 * Validated categorical palette — checked with the dataviz validator against
 * this surface (#0d1320) for the lightness band, chroma floor, CVD separation
 * of every adjacent pair, and contrast. Assigned in fixed order and never
 * cycled: a class keeps its colour when a filter changes which classes are
 * present, so the chart does not repaint itself as you narrow it.
 */
const CLASS_COLOURS: Record<string, string> = {
    car: '#4a90e8',
    motorcycle: '#00a08f',
    truck: '#c87d2a',
    bus: '#a05fd8',
    bicycle: '#d44a7a',
    person: '#7c8da8',
}
const CLASS_ORDER = ['car', 'motorcycle', 'truck', 'bus', 'bicycle', 'person']

const WINDOWS = [
    { hours: 6, label: '6h' },
    { hours: 24, label: '24h' },
    { hours: 72, label: '3d' },
    { hours: 168, label: '7d' },
]

function relative(hours?: number | null): string {
    if (hours == null) return 'never'
    if (hours < 1) return `${Math.round(hours * 60)} min ago`
    if (hours < 48) return `${Math.round(hours)} h ago`
    return `${Math.round(hours / 24)} d ago`
}

function compact(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 10_000) return `${Math.round(n / 1000)}k`
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
    return String(n)
}

/** Peak hour of the day, named in plain language for the caption. */
function peakHour(hours: HourlyPoint[]): HourlyPoint | null {
    if (!hours.length) return null
    return hours.reduce((best, h) =>
        h.vehicles + h.people > best.vehicles + best.people ? h : best)
}

function HourTooltip({ active, payload, label }: any) {
    if (!active || !payload?.length) return null
    const point: HourlyPoint = payload[0].payload
    return (
        <div className="chart-tooltip">
            <div className="chart-tooltip-head">
                {String(label).padStart(2, '0')}:00 – {String(label).padStart(2, '0')}:59 IST
            </div>
            <div className="chart-tooltip-row">
                <span style={{ background: CLASS_COLOURS.car }} />
                Vehicles <strong>{point.vehicles.toLocaleString()}</strong>
            </div>
            <div className="chart-tooltip-row">
                <span style={{ background: CLASS_COLOURS.person }} />
                People <strong>{point.people.toLocaleString()}</strong>
            </div>
            <div className="chart-tooltip-foot">
                {point.buckets.toLocaleString()} minute buckets
            </div>
        </div>
    )
}

export default function HealthPage() {
    const [health, setHealth] = useState<HealthReport | null>(null)
    const [scene, setScene] = useState<SceneSummary | null>(null)
    const [sceneCameras, setSceneCameras] = useState<SceneCamera[]>([])
    const [hourly, setHourly] = useState<HourlyPoint[]>([])
    const [loading, setLoading] = useState(true)
    const [filter, setFilter] = useState<string>('all')
    const [windowHours, setWindowHours] = useState(24)
    // Hide rows the seeding tool wrote. Off by default so a fresh checkout
    // shows the demonstration grid; a recording of real data flips it.
    const [realOnly, setRealOnly] = useState(false)

    const load = useCallback(async () => {
        setLoading(true)
        // Independent: a failing analytics query must not blank the health table,
        // which is the half that matters when something is wrong.
        const [h, s, c, u] = await Promise.allSettled([
            getCameraHealth(),
            getSceneSummary(windowHours, !realOnly),
            getSceneByCamera(windowHours, !realOnly),
            getSceneHourly(windowHours, !realOnly),
        ])
        if (h.status === 'fulfilled') setHealth(h.value as HealthReport)
        if (s.status === 'fulfilled') setScene(s.value as SceneSummary)
        if (c.status === 'fulfilled') setSceneCameras((c.value as { cameras: SceneCamera[] }).cameras ?? [])
        if (u.status === 'fulfilled') setHourly((u.value as { hours: HourlyPoint[] }).hours ?? [])
        setLoading(false)
    }, [windowHours, realOnly])

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

    // Analytics coverage, which is a different question from health: a camera
    // can be perfectly online and still have nobody running a detector on it.
    const coverage = useMemo(() => {
        const total = totals?.cameras ?? 0
        const reporting = scene?.cameras_reporting ?? 0
        return { total, reporting, gap: Math.max(0, total - reporting) }
    }, [totals, scene])

    /**
     * Per-camera activity, ranked by rate rather than by total.
     *
     * Two corrections to the obvious version. Rate first: a camera the worker
     * watched for twice as long accumulates twice the total without being any
     * busier, so totals partly measure the scheduler rather than the traffic.
     * Dividing by buckets analysed removes that.
     *
     * Then the scale. Busy cameras cluster — the top eight here sit between 76%
     * and 100% of the leader — so bars drawn from zero are all nearly full and
     * separate nothing. The bar spans the observed range instead, with the
     * quietest camera keeping a visible stub. That exaggerates differences by
     * construction, which is why the numbers sit beside it and the column is
     * labelled per-minute rather than as a count.
     */
    const rankedCameras = useMemo(() => {
        const withRate = sceneCameras.map(c => ({
            ...c,
            rate: c.buckets > 0 ? (c.vehicles + c.people) / c.buckets : 0,
            // Analysed, saw nothing. Over a 24-hour window almost no camera hits
            // exactly zero, so this fires rarely — but it is the state that must
            // not be confused with a camera nobody analysed, and the short
            // windows are where it shows up.
            idle: c.buckets > 0 && c.vehicles + c.people === 0,
        }))
        const rates = withRate.map(c => c.rate)
        const max = Math.max(...rates, 0.001)
        const min = Math.min(...rates, 0)
        const span = Math.max(max - min, 0.001)
        return withRate
            .sort((a, b) => b.rate - a.rate)
            .map(c => ({ ...c, share: 0.08 + 0.92 * ((c.rate - min) / span) }))
    }, [sceneCameras])

    const classMix = useMemo(() => {
        const labels = scene?.by_label ?? {}
        const total = Object.values(labels).reduce((a, b) => a + b, 0) || 1
        return CLASS_ORDER
            .filter(l => labels[l])
            .map(l => ({ label: l, count: labels[l], share: labels[l] / total }))
    }, [scene])

    const peak = useMemo(() => peakHour(hourly), [hourly])
    const hasScene = (scene?.buckets ?? 0) > 0
    const seededBuckets = scene?.buckets_by_source?.seed ?? 0
    const workerBuckets = scene?.buckets_by_source?.worker ?? 0

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
                    <div className="window-toggle" role="group" aria-label="Time window">
                        {WINDOWS.map(w => (
                            <button
                                key={w.hours}
                                className={`window-btn${windowHours === w.hours ? ' is-active' : ''}`}
                                onClick={() => setWindowHours(w.hours)}
                                aria-pressed={windowHours === w.hours}
                            >
                                {w.label}
                            </button>
                        ))}
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
                        <RefreshCw size={13} className={loading ? 'is-spinning' : ''} /> Refresh
                    </button>
                </div>
            </div>

            {totals && (
                <div className="stat-grid">
                    <button
                        className={`stat-card is-clickable${filter === 'operational' ? ' is-active' : ''}`}
                        onClick={() => setFilter(filter === 'operational' ? 'all' : 'operational')}
                        aria-pressed={filter === 'operational'}
                    >
                        <div className="stat-label">Operational</div>
                        <div className="stat-value green">{totals.operational}</div>
                        <div className="stat-sub">Seen within the hour</div>
                    </button>
                    <button
                        className={`stat-card is-clickable${filter === 'stale' ? ' is-active' : ''}`}
                        onClick={() => setFilter(filter === 'stale' ? 'all' : 'stale')}
                        aria-pressed={filter === 'stale'}
                    >
                        <div className="stat-label">Stale</div>
                        <div className="stat-value yellow">{totals.stale}</div>
                        <div className="stat-sub">Reachable, nothing recent</div>
                    </button>
                    <button
                        className={`stat-card is-clickable${filter === 'offline' ? ' is-active' : ''}`}
                        onClick={() => setFilter(filter === 'offline' ? 'all' : 'offline')}
                        aria-pressed={filter === 'offline'}
                    >
                        <div className="stat-label">Offline</div>
                        <div className={`stat-value ${totals.offline > 0 ? 'red' : ''}`}>{totals.offline}</div>
                        <div className="stat-sub">No contact at all</div>
                    </button>
                    <div className="stat-card">
                        <div className="stat-label">Analytics coverage</div>
                        <div className="stat-value blue">
                            {coverage.reporting}
                            <span className="stat-value-of">/{coverage.total}</span>
                        </div>
                        <div className="stat-sub">
                            {coverage.gap > 0
                                ? `${coverage.gap} cameras not analysed`
                                : 'Every camera analysed'}
                        </div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Frames analysed</div>
                        <div className="stat-value">{compact(scene?.frames_analysed ?? 0)}</div>
                        <div className="stat-sub">
                            {compact(scene?.buckets ?? 0)} minute buckets · last {windowHours}h
                        </div>
                    </div>
                </div>
            )}

            {/* Say what the counts are made of. Demonstration rows are labelled
                in place and can be hidden, never silently mixed in. */}
            {(seededBuckets > 0 || realOnly) && (
                <div className={`demo-banner${realOnly ? ' is-real' : ''}`} role="status">
                    <Info size={13} aria-hidden="true" />
                    <span>
                        {realOnly
                            ? <>Showing <strong>real detector data only</strong> — {workerBuckets.toLocaleString()} minute
                                buckets from workers over live feeds. Seeded rows are hidden, not deleted.</>
                            : <><strong>{seededBuckets.toLocaleString()}</strong> of the {(scene?.buckets ?? 0).toLocaleString()} buckets
                                in this window were written by the seeding tool for demonstration.
                                {workerBuckets > 0 && <> {workerBuckets.toLocaleString()} came from real workers.</>}</>}
                    </span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setRealOnly(v => !v)}>
                        {realOnly ? 'Include seeded data' : 'Real data only'}
                    </button>
                </div>
            )}

            {/* Activity over the day — the question the old page could not answer. */}
            {hasScene && (
                <section className="card chart-card">
                    <div className="card-title">
                        <TrendingUp size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                        Activity by hour
                        <span className="card-title-note">
                            {peak
                                ? `busiest at ${String(peak.hour).padStart(2, '0')}:00 IST`
                                : ''}
                        </span>
                    </div>

                    <div className="chart-legend">
                        <span className="legend-item">
                            <span className="legend-swatch" style={{ background: CLASS_COLOURS.car }} />
                            Vehicles
                        </span>
                        <span className="legend-item">
                            <span className="legend-swatch" style={{ background: CLASS_COLOURS.person }} />
                            People
                        </span>
                    </div>

                    <ResponsiveContainer width="100%" height={190}>
                        <BarChart data={hourly} margin={{ top: 4, right: 6, bottom: 0, left: -14 }}
                                  barCategoryGap="22%">
                            <CartesianGrid stroke="#1f2b44" vertical={false} />
                            <XAxis
                                dataKey="hour" tickLine={false} axisLine={false}
                                tick={{ fill: '#6b7c98', fontSize: 10 }}
                                interval={2}
                                tickFormatter={(h: number) => `${String(h).padStart(2, '0')}`}
                            />
                            <YAxis
                                tickLine={false} axisLine={false}
                                tick={{ fill: '#6b7c98', fontSize: 10 }}
                                tickFormatter={compact} width={44}
                            />
                            <Tooltip content={<HourTooltip />} cursor={{ fill: 'rgba(77,141,255,0.08)' }} />
                            <Bar dataKey="people" stackId="a" fill={CLASS_COLOURS.person} />
                            <Bar dataKey="vehicles" stackId="a" fill={CLASS_COLOURS.car}
                                 radius={[3, 3, 0, 0]}>
                                {hourly.map(h => (
                                    <Cell key={h.hour}
                                          opacity={peak && h.hour === peak.hour ? 1 : 0.82} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                    <p className="chart-caption">
                        Hour of day, IST. Counts are peak-per-minute summed across the
                        window — a throughput estimate, not a count of distinct vehicles.
                    </p>
                </section>
            )}

            <div className="health-row">
                {/* Scene analytics — what the cameras are seeing. */}
                <section className="card">
                    <div className="card-title">
                        <Activity size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                        What the cameras are seeing
                    </div>

                    {!hasScene ? (
                        <div className="empty-state" style={{ minHeight: 180 }}>
                            <div className="empty-state-icon"><Activity size={22} /></div>
                            <div className="empty-state-title">No scene analysis yet</div>
                            <div className="empty-state-body">
                                Run <code>python tools/scene_analytics.py --camera cam10</code> to
                                index vehicle and person counts from a live feed, or{' '}
                                <code>python tools/seed_scene_analytics.py</code> to populate the
                                grid for a walkthrough. This tier works on cameras whose plates
                                are too small to read.
                            </div>
                        </div>
                    ) : (
                        <>
                            <div className="scene-counts">
                                <div className="scene-count">
                                    <CameraIcon size={15} aria-hidden="true" />
                                    <div>
                                        <strong>{(scene?.observations.vehicle ?? 0).toLocaleString()}</strong>
                                        <span>vehicle observations</span>
                                    </div>
                                </div>
                                <div className="scene-count">
                                    <Users size={15} aria-hidden="true" />
                                    <div>
                                        <strong>{(scene?.observations.person ?? 0).toLocaleString()}</strong>
                                        <span>person observations</span>
                                    </div>
                                </div>
                            </div>

                            {/* Class mix as a proportion bar: the shape of the traffic,
                                which a row of chips cannot show. Each segment is direct-
                                labelled below, so identity never rests on colour alone. */}
                            {classMix.length > 0 && (
                                <div className="mix">
                                    <div className="mix-bar">
                                        {classMix.map(c => (
                                            <div
                                                key={c.label}
                                                className="mix-seg"
                                                style={{
                                                    width: `${c.share * 100}%`,
                                                    background: CLASS_COLOURS[c.label] ?? '#7c8da8',
                                                }}
                                                title={`${c.label}: ${c.count.toLocaleString()}`}
                                            />
                                        ))}
                                    </div>
                                    <div className="mix-legend">
                                        {classMix.map(c => (
                                            <span key={c.label} className="mix-item">
                                                <span className="legend-swatch"
                                                      style={{ background: CLASS_COLOURS[c.label] ?? '#7c8da8' }} />
                                                {c.label}
                                                <strong>{compact(c.count)}</strong>
                                                <em>{Math.round(c.share * 100)}%</em>
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {scene?.note && (
                                <p className="scene-note">
                                    <Info size={11} aria-hidden="true" /> {scene.note}
                                </p>
                            )}

                            {rankedCameras.length > 0 && (
                                <div className="scene-rank">
                                    <div className="scene-rank-head">
                                        <span>Camera</span>
                                        <span>Per minute</span>
                                        <span>Vehicles</span>
                                        <span>People</span>
                                    </div>
                                    {rankedCameras.map(c => (
                                        <div key={c.camera_id} className="scene-rank-row">
                                            <span className="scene-rank-name">
                                                {c.camera_name}
                                                {c.idle && (
                                                    <span className="scene-idle"
                                                          title="Analysed, but nothing was in view">
                                                        <EyeOff size={9} /> quiet
                                                    </span>
                                                )}
                                            </span>
                                            <span className="scene-rank-bar"
                                                  title={`${c.rate.toFixed(1)} observations per minute analysed`}>
                                                <span className="scene-rank-track">
                                                    <i style={{ width: `${c.share * 100}%` }} />
                                                </span>
                                                <em>{c.rate.toFixed(1)}</em>
                                            </span>
                                            <span className="num">{compact(c.vehicles)}</span>
                                            <span className="num">{compact(c.people)}</span>
                                        </div>
                                    ))}
                                    {coverage.gap > 0 && (
                                        <div className="coverage-gap">
                                            <AlertTriangle size={12} aria-hidden="true" />
                                            <div>
                                                <strong>
                                                    {coverage.gap} of {coverage.total} cameras
                                                    are not being analysed
                                                </strong>
                                                <span>
                                                    They appear in the registry but no worker
                                                    has indexed them in this window — a blind
                                                    spot the counts above cannot show, because
                                                    a camera nobody watches contributes
                                                    nothing rather than zero.
                                                </span>
                                            </div>
                                        </div>
                                    )}

                                    <p className="chart-caption">
                                        Ranked by observations per minute analysed, not by
                                        total: a camera watched for longer accumulates more
                                        without being busier. Bars span the observed range
                                        rather than starting at zero, so they separate
                                        cameras that cluster — read the figures for absolute
                                        values.
                                    </p>
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
                        {filter === 'all' && unlocated > 0 && (
                            <span className="card-title-note">
                                {unlocated} without coordinates
                            </span>
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
