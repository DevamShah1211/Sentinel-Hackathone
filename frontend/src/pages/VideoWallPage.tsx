import { useEffect, useState } from 'react'
import { Maximize2, Minimize2, LayoutGrid, RotateCw } from 'lucide-react'
import { getCameras } from '../api/client'

interface Camera {
    id: string; native_id: string; name: string; department: string;
    hls_url: string; whep_url: string; is_live: boolean; codec: string;
}

interface Slot {
    camera: Camera | null
    isHero: boolean
}

function StreamPlayer({ cam, keyId }: { cam: Camera; keyId: number }) {
    const streamUrl = `http://devam6205%40gmail.com:GAQA-H7HN-P2GE@103.250.160.189:8889/stream/${cam.native_id}/?autoplay=true&muted=true`
    return (
        <div style={{ position: 'relative', width: '100%', height: '100%', background: '#000' }}>
            <iframe
                key={keyId}
                src={streamUrl}
                title={cam.name}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block', background: '#000' }}
                allow="autoplay; fullscreen"
            />
        </div>
    )
}

function VideoTile({
    slot, index, onMaximise, onCameraChange, cameras, isMaximised,
}: {
    slot: Slot; index: number; onMaximise: (i: number) => void;
    onCameraChange: (i: number, c: Camera | null) => void;
    cameras: Camera[]; isMaximised: boolean;
}) {
    const [showSelect, setShowSelect] = useState(false)
    const [reloadKey, setReloadKey] = useState(0)
    const cam = slot.camera

    if (!cam) return (
        <div className="video-tile tile-empty" onClick={() => setShowSelect(s => !s)}>
            <LayoutGrid size={24} />
            <span>Click to assign camera</span>
            {showSelect && (
                <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 8, zIndex: 10, maxHeight: 200, overflowY: 'auto', width: 220 }}
                    onClick={e => e.stopPropagation()}>
                    {cameras.map(c => (
                        <div key={c.id} style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 12, borderRadius: 4, color: 'var(--text-primary)' }}
                            onMouseOver={e => (e.currentTarget.style.background = 'var(--bg-surface)')}
                            onMouseOut={e => (e.currentTarget.style.background = '')}
                            onClick={() => { onCameraChange(index, c); setShowSelect(false) }}>
                            {c.name} <span style={{ color: 'var(--text-muted)' }}>({c.department})</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )

    return (
        <div className="video-tile" style={{ position: 'relative' }}>
            <StreamPlayer cam={cam} keyId={reloadKey} />
            <div className="tile-overlay">
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div>
                        <div className="tile-cam-name">{cam.name}</div>
                        <div className="tile-cam-dept">{cam.department}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 4 }}>
                        <button style={{ background: 'rgba(0,0,0,0.5)', border: 'none', borderRadius: 4, padding: '3px 6px', cursor: 'pointer', color: '#fff', fontSize: 10 }}
                            title="Reload Stream"
                            onClick={() => setReloadKey(k => k + 1)}>
                            <RotateCw size={12} />
                        </button>
                        <button style={{ background: 'rgba(0,0,0,0.5)', border: 'none', borderRadius: 4, padding: '3px 6px', cursor: 'pointer', color: '#fff', fontSize: 10 }}
                            onClick={() => onMaximise(index)}>
                            {isMaximised ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                        </button>
                        <button style={{ background: 'rgba(0,0,0,0.5)', border: 'none', borderRadius: 4, padding: '3px 6px', cursor: 'pointer', color: '#fff', fontSize: 10 }}
                            onClick={() => onCameraChange(index, null)}>✕</button>
                    </div>
                </div>
            </div>
            {slot.isHero && <div className="tile-hero-badge">HERO · WHEP</div>}
            {cam.is_live && (
                <div style={{ position: 'absolute', top: 6, left: 6, display: 'flex', alignItems: 'center', gap: 4, background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '2px 6px', fontSize: 10, color: 'var(--green)', fontWeight: 700, zIndex: 6 }}>
                    <div className="pulse-dot" />LIVE
                </div>
            )}
        </div>
    )
}

export default function VideoWallPage() {
    const [cameras, setCameras] = useState<Camera[]>([])
    const [slots, setSlots] = useState<Slot[]>(Array.from({ length: 9 }, () => ({ camera: null, isHero: false })))
    const [layout, setLayout] = useState<'3x3' | '2x2' | '1x1'>('3x3')
    const [maximised, setMaximised] = useState<number | null>(null)

    useEffect(() => {
        getCameras({ live_only: true, limit: 100 }).then((data: Camera[]) => {
            setCameras(data)
            // Auto-fill tiles with first 9 live cameras
            setSlots(prev => prev.map((s, i) => i < data.length ? { camera: data[i], isHero: i === 0 } : s))
        })
    }, [])

    const handleMaximise = (idx: number) => setMaximised(m => m === idx ? null : idx)
    const handleCameraChange = (idx: number, cam: Camera | null) =>
        setSlots(prev => prev.map((s, i) => i === idx ? { ...s, camera: cam } : s))

    const gridCount = layout === '3x3' ? 9 : layout === '2x2' ? 4 : 1
    const visibleSlots = slots.slice(0, gridCount)
    const displaySlots = maximised !== null
        ? [{ ...slots[maximised], isHero: false }]
        : visibleSlots

    return (
        <div className="page-content no-padding" style={{ display: 'flex', flexDirection: 'column' }}>
            {/* Toolbar */}
            <div style={{ padding: '8px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600 }}>LAYOUT:</span>
                {(['3x3', '2x2', '1x1'] as const).map(l => (
                    <button key={l} className={`btn btn-sm ${layout === l ? 'btn-primary' : 'btn-ghost'}`}
                        onClick={() => { setLayout(l); setMaximised(null) }}>
                        {l}
                    </button>
                ))}
                {maximised !== null && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setMaximised(null)}>
                        <Minimize2 size={12} /> Exit Fullscreen
                    </button>
                )}
                <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
                    {cameras.filter(c => c.is_live).length} cameras live
                </span>
            </div>

            {/* Wall */}
            <div style={{ flex: 1, padding: 4 }}>
                <div className={`video-wall-grid ${maximised !== null ? 'grid-1x1' : `grid-${layout}`}`}
                    style={{ height: '100%' }}>
                    {displaySlots.map((slot, i) => (
                        <VideoTile
                            key={maximised !== null ? maximised : i}
                            slot={slot}
                            index={maximised !== null ? maximised : i}
                            cameras={cameras}
                            isMaximised={maximised === (maximised !== null ? maximised : i)}
                            onMaximise={handleMaximise}
                            onCameraChange={handleCameraChange}
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}
