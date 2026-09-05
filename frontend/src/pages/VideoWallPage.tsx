import { useCallback, useEffect, useState } from 'react'
import { LayoutGrid, Maximize2, Minimize2, RotateCw } from 'lucide-react'
import { getCameras } from '../api/client'
import LiveTile, { type StreamProfile, type TileState } from '../components/LiveTile'

interface Camera {
    id: string; native_id: string; name: string; department: string
    live_url?: string; hls_url?: string; is_live: boolean; codec: string
}

interface Slot {
    camera: Camera | null
    isHero: boolean
}

function CameraPicker({ cameras, onPick }: { cameras: Camera[]; onPick: (c: Camera) => void }) {
    const [query, setQuery] = useState('')
    const filtered = cameras.filter(c =>
        `${c.name} ${c.department} ${c.native_id}`.toLowerCase().includes(query.toLowerCase()))

    return (
        <div
            style={{
                position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
                background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8,
                padding: 8, zIndex: 10, width: 250, maxHeight: 260, display: 'flex', flexDirection: 'column',
            }}
            onClick={e => e.stopPropagation()}
        >
            <input
                autoFocus
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Filter cameras…"
                style={{
                    width: '100%', padding: '6px 8px', marginBottom: 6, fontSize: 12,
                    background: 'var(--bg-surface)', border: '1px solid var(--border)',
                    borderRadius: 4, color: 'var(--text-primary)',
                }}
            />
            <div style={{ overflowY: 'auto' }}>
                {filtered.length === 0 && (
                    <div style={{ padding: 8, fontSize: 12, color: 'var(--text-muted)' }}>No cameras match.</div>
                )}
                {filtered.map(c => (
                    <div
                        key={c.id}
                        style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 12, borderRadius: 4, color: 'var(--text-primary)' }}
                        onMouseOver={e => (e.currentTarget.style.background = 'var(--bg-surface)')}
                        onMouseOut={e => (e.currentTarget.style.background = '')}
                        onClick={() => onPick(c)}
                    >
                        {c.name}{' '}
                        <span style={{ color: 'var(--text-muted)' }}>({c.department})</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function VideoTile({ slot, index, onMaximise, onCameraChange, cameras, isMaximised, profile }: {
    slot: Slot; index: number; onMaximise: (i: number) => void
    onCameraChange: (i: number, c: Camera | null) => void
    cameras: Camera[]; isMaximised: boolean; profile: StreamProfile
}) {
    const [showPicker, setShowPicker] = useState(false)
    const [reloadKey, setReloadKey] = useState(0)
    const [state, setState] = useState<TileState>('connecting')
    const cam = slot.camera

    const handleState = useCallback((s: TileState) => setState(s), [])

    if (!cam) {
        return (
            <div className="video-tile tile-empty" onClick={() => setShowPicker(s => !s)}>
                <LayoutGrid size={24} />
                <span>Click to assign camera</span>
                {showPicker && (
                    <CameraPicker
                        cameras={cameras}
                        onPick={c => { onCameraChange(index, c); setShowPicker(false) }}
                    />
                )}
            </div>
        )
    }

    return (
        <div className="video-tile" style={{ position: 'relative' }}>
            <LiveTile
                key={reloadKey}
                cameraId={cam.native_id}
                alt={`Live view from ${cam.name}`}
                onStateChange={handleState}
                profile={profile}
            />

            <div className="tile-overlay">
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div>
                        <div className="tile-cam-name">{cam.name}</div>
                        <div className="tile-cam-dept">{cam.department}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 4 }}>
                        <button
                            style={{ background: 'rgba(0,0,0,0.5)', border: 'none', borderRadius: 4, padding: '3px 6px', cursor: 'pointer', color: '#fff' }}
                            title="Reload stream"
                            onClick={() => setReloadKey(k => k + 1)}
                        >
                            <RotateCw size={12} />
                        </button>
                        <button
                            style={{ background: 'rgba(0,0,0,0.5)', border: 'none', borderRadius: 4, padding: '3px 6px', cursor: 'pointer', color: '#fff' }}
                            title={isMaximised ? 'Restore' : 'Maximise'}
                            onClick={() => onMaximise(index)}
                        >
                            {isMaximised ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                        </button>
                        <button
                            style={{ background: 'rgba(0,0,0,0.5)', border: 'none', borderRadius: 4, padding: '3px 6px', cursor: 'pointer', color: '#fff', fontSize: 10 }}
                            title="Clear tile"
                            onClick={() => onCameraChange(index, null)}
                        >
                            ✕
                        </button>
                    </div>
                </div>
            </div>

            {slot.isHero && <div className="tile-hero-badge">HERO</div>}
            {state === 'playing' && (
                <div style={{
                    position: 'absolute', top: 6, left: 6, display: 'flex', alignItems: 'center', gap: 4,
                    background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '2px 6px',
                    fontSize: 10, color: 'var(--green)', fontWeight: 700, zIndex: 6,
                }}>
                    <div className="pulse-dot" />LIVE
                </div>
            )}
        </div>
    )
}

export default function VideoWallPage() {
    const [cameras, setCameras] = useState<Camera[]>([])
    const [slots, setSlots] = useState<Slot[]>(Array.from({ length: 9 }, () => ({ camera: null, isHero: false })))
    const [layout, setLayout] = useState<'3x3' | '2x2' | '1x1'>('2x2')
    const [maximised, setMaximised] = useState<number | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        getCameras({ live_only: true, limit: 100 })
            .then((data: Camera[]) => {
                setCameras(data)
                setSlots(prev => prev.map((s, i) =>
                    i < data.length ? { camera: data[i], isHero: i === 0 } : s))
            })
            .catch(() => setError('Could not load cameras. Is the backend running?'))
            .finally(() => setLoading(false))
    }, [])

    // Pause every tile while the tab is hidden. Without this the wall keeps
    // decoding nine streams in the background for the whole session.
    useEffect(() => {
        const onVisibility = () => {
            document.querySelectorAll('video').forEach(v => {
                if (document.hidden) v.pause()
                else v.play().catch(() => { /* autoplay policy */ })
            })
        }
        document.addEventListener('visibilitychange', onVisibility)
        return () => document.removeEventListener('visibilitychange', onVisibility)
    }, [])

    const handleMaximise = (idx: number) => setMaximised(m => (m === idx ? null : idx))
    const handleCameraChange = (idx: number, cam: Camera | null) =>
        setSlots(prev => prev.map((s, i) => (i === idx ? { ...s, camera: cam } : s)))

    const gridCount = layout === '3x3' ? 9 : layout === '2x2' ? 4 : 1
    // Fewer tiles on screen means each can afford more resolution and frames.
    const profile: StreamProfile =
        maximised !== null || layout === '1x1' ? 'high'
        : layout === '2x2' ? 'balanced'
        : 'low'
    const displaySlots = maximised !== null
        ? [{ ...slots[maximised], isHero: false }]
        : slots.slice(0, gridCount)

    return (
        <div className="page-content no-padding" style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '8px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600 }}>LAYOUT:</span>
                {(['3x3', '2x2', '1x1'] as const).map(l => (
                    <button
                        key={l}
                        className={`btn btn-sm ${layout === l ? 'btn-primary' : 'btn-ghost'}`}
                        onClick={() => { setLayout(l); setMaximised(null) }}
                    >
                        {l}
                    </button>
                ))}
                {maximised !== null && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setMaximised(null)}>
                        <Minimize2 size={12} /> Exit fullscreen
                    </button>
                )}
                <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
                    {loading ? 'Loading cameras…' : `${cameras.filter(c => c.is_live).length} cameras live`}
                </span>
            </div>

            {error && (
                <div style={{ padding: '10px 16px', color: 'var(--red)', fontSize: 13 }}>{error}</div>
            )}

            <div style={{ flex: 1, padding: 4 }}>
                <div
                    className={`video-wall-grid ${maximised !== null ? 'grid-1x1' : `grid-${layout}`}`}
                    style={{ height: '100%' }}
                >
                    {displaySlots.map((slot, i) => {
                        const realIndex = maximised !== null ? maximised : i
                        return (
                            <VideoTile
                                key={slot.camera ? `${realIndex}-${slot.camera.native_id}` : `empty-${realIndex}`}
                                slot={slot}
                                index={realIndex}
                                cameras={cameras}
                                isMaximised={maximised === realIndex}
                                profile={profile}
                                onMaximise={handleMaximise}
                                onCameraChange={handleCameraChange}
                            />
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
