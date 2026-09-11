/**
 * Live detection feed — plates appearing as the worker reads them.
 *
 * The rest of the platform answers questions about the past: search a plate,
 * reconstruct a route, export a report. This page answers "what is happening
 * right now", which is what an operator watches between incidents and what a
 * reviewer wants to see working rather than described.
 *
 * **Polled, not pushed.** `/ws/alerts` exists but carries watchlist hits only,
 * and adding a per-detection broadcast would mean changing the ingest hot path.
 * A two-second poll is indistinguishable on screen and cannot break ingest, so
 * that is the trade taken here. If this ever needs to be genuinely live, the
 * shape of the page does not change — only where `rows` comes from.
 *
 * The distinction the page is built around is confirmed versus partial. A read
 * below the resolution threshold is a lead, not an identification, and
 * MEASUREMENTS section 2g is the reason: on this grid a well-formed, confident,
 * wrong plate is the normal failure, not an unlikely one. Partial reads are
 * shown — suppressing them would hide real evidence — but they are badged, they
 * carry the worker's own reason, and they never appear as confirmed.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    AlertTriangle, Camera as CameraIcon, CheckCircle2, Pause, Play, Radio,
} from 'lucide-react'
import { pollRecentDetections } from '../api/client'

interface Detection {
    id: string
    plate_text: string
    confidence: number
    detected_at: string
    crop_uri?: string | null
    camera_name: string
    department: string
    partial?: boolean
    partial_reason?: string | null
}

const POLL_MS = 2000

/** Rows arriving within this window are still highlighted as new. */
const FRESH_MS = 6000

function timeOf(iso: string): string {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-IN', { hour12: false })
}

function agoOf(iso: string, now: number): string {
    const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
    if (s < 60) return `${s}s ago`
    if (s < 3600) return `${Math.round(s / 60)}m ago`
    return `${Math.round(s / 3600)}h ago`
}

export default function LiveDetectionPage() {
    const [rows, setRows] = useState<Detection[]>([])
    const [paused, setPaused] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [now, setNow] = useState(() => Date.now())
    const [startedAt] = useState(() => Date.now())

    // Ids seen in a previous poll. Anything absent from this is new, which is
    // what drives the arrival highlight — comparing timestamps instead would
    // re-flash every row whenever the clock ticked.
    const seen = useRef<Set<string>>(new Set())
    const [fresh, setFresh] = useState<Record<string, number>>({})

    const poll = useCallback(async () => {
        try {
            const data = (await pollRecentDetections()) as Detection[]
            setError(null)
            const arrived: Record<string, number> = {}
            const stamp = Date.now()
            for (const d of data) {
                if (!seen.current.has(d.id)) {
                    seen.current.add(d.id)
                    // Everything is unseen on the first poll; highlighting all
                    // fifty would be noise rather than signal.
                    if (seen.current.size > data.length) arrived[d.id] = stamp
                }
            }
            if (Object.keys(arrived).length) {
                setFresh(f => ({ ...f, ...arrived }))
            }
            setRows(data)
        } catch {
            setError('Cannot reach the detection index. Is the backend running?')
        }
    }, [])

    useEffect(() => { void poll() }, [poll])

    useEffect(() => {
        if (paused) return
        const id = setInterval(() => { void poll() }, POLL_MS)
        return () => clearInterval(id)
    }, [paused, poll])

    // A separate, slower tick for the relative times, so "12s ago" stays true
    // without re-fetching.
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(id)
    }, [])

    const stats = useMemo(() => {
        const confirmed = rows.filter(r => !r.partial).length
        const partial = rows.length - confirmed
        const plates = new Set(rows.map(r => r.plate_text)).size
        const cameras = new Set(rows.map(r => r.camera_name)).size
        const sinceStart = rows.filter(
            r => new Date(r.detected_at).getTime() >= startedAt).length
        return { confirmed, partial, plates, cameras, sinceStart }
    }, [rows, startedAt])

    return (
        <div className="page-content">
            <div className="page-head">
                <div>
                    <h1>Live Detection Feed</h1>
                    <div className="page-sub">
                        Plates as the indexer reads them · confirmed reads and
                        low-resolution partials, distinguished rather than merged
                    </div>
                </div>
                <div className="page-head-actions">
                    <span className={`live-pill${paused ? ' is-paused' : ''}`}>
                        <Radio size={12} aria-hidden="true" />
                        {paused ? 'Paused' : `Polling every ${POLL_MS / 1000}s`}
                    </span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setPaused(p => !p)}>
                        {paused ? <><Play size={13} /> Resume</> : <><Pause size={13} /> Pause</>}
                    </button>
                </div>
            </div>

            {error && <div className="live-error">{error}</div>}

            <div className="stat-grid">
                <div className="stat-card">
                    <div className="stat-label">Confirmed</div>
                    <div className="stat-value green">{stats.confirmed}</div>
                    <div className="stat-sub">Above the resolution threshold</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Partial</div>
                    <div className="stat-value yellow">{stats.partial}</div>
                    <div className="stat-sub">Searchable, never alertable</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Distinct plates</div>
                    <div className="stat-value">{stats.plates}</div>
                    <div className="stat-sub">In the last 50 reads</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Cameras</div>
                    <div className="stat-value">{stats.cameras}</div>
                    <div className="stat-sub">Contributing reads</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Since you opened</div>
                    <div className="stat-value blue">{stats.sinceStart}</div>
                    <div className="stat-sub">New reads this session</div>
                </div>
            </div>

            <section className="card">
                <div className="card-title">
                    <CameraIcon size={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                    Most recent 50 reads
                    <span className="card-title-note">newest first</span>
                </div>

                {rows.length === 0 ? (
                    <div className="empty-state" style={{ minHeight: 220 }}>
                        <div className="empty-state-icon"><Radio size={22} /></div>
                        <div className="empty-state-title">No detections yet</div>
                        <div className="empty-state-body">
                            Start a worker and reads will appear here within two seconds:
                            <br />
                            <code>python anpr_worker.py --camera cam12</code>
                            <br />
                            or, against your own footage:
                            <br />
                            <code>python tools/live_demo.py --source clip.mp4</code>
                        </div>
                    </div>
                ) : (
                    <div className="live-feed">
                        {rows.map(r => {
                            const isFresh = fresh[r.id] && now - fresh[r.id] < FRESH_MS
                            return (
                                <div
                                    key={r.id}
                                    className={`live-row${r.partial ? ' is-partial' : ''}`
                                        + (isFresh ? ' is-new' : '')}
                                >
                                    {r.crop_uri
                                        ? <img className="live-crop" src={r.crop_uri}
                                               alt={`Evidence crop for ${r.plate_text}`} />
                                        : <div className="live-crop live-crop-missing" aria-hidden="true" />}

                                    <div className="live-main">
                                        <div className="live-plate-row">
                                            <span className="live-plate">{r.plate_text}</span>
                                            {r.partial ? (
                                                <span className="live-badge is-partial"
                                                      title={r.partial_reason ?? undefined}>
                                                    <AlertTriangle size={10} /> PARTIAL
                                                </span>
                                            ) : (
                                                <span className="live-badge is-confirmed">
                                                    <CheckCircle2 size={10} /> CONFIRMED
                                                </span>
                                            )}
                                            {isFresh && <span className="live-badge is-new">NEW</span>}
                                        </div>
                                        <div className="live-meta">
                                            {r.camera_name} · {r.department}
                                        </div>
                                        {r.partial && r.partial_reason && (
                                            <div className="live-reason">{r.partial_reason}</div>
                                        )}
                                    </div>

                                    <div className="live-right">
                                        <span className="live-conf">
                                            {Math.round((r.confidence ?? 0) * 100)}%
                                        </span>
                                        <span className="live-time">{timeOf(r.detected_at)}</span>
                                        <span className="live-ago">{agoOf(r.detected_at, now)}</span>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}

                <p className="chart-caption">
                    A partial read is indexed and searchable but can never raise an
                    alert. On this grid the plates are 4–14 pixels per character
                    against the 20–30 a recogniser needs, so a confident, well-formed,
                    wrong plate is the normal failure rather than an unlikely one —
                    see MEASUREMENTS §2g.
                </p>
            </section>
        </div>
    )
}
