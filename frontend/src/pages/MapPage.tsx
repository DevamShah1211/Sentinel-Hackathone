import { useEffect, useRef, useState, useCallback } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import { RefreshCw, Layers, CheckCircle2, XCircle } from 'lucide-react'
import { getCamerasGeoJSON, syncCatalogue, getIngestStatus } from '../api/client'
import type { LatLngExpression } from 'leaflet'

interface CameraFeature {
    type: 'Feature'
    geometry: { type: 'Point'; coordinates: [number, number] }
    properties: {
        id: string; native_id: string; name: string; department: string;
        status: string; is_live: boolean; codec: string;
        hls_url: string;
        camera_type: string; address: string;
    }
}

const DEPT_COLOURS: Record<string, string> = {
    'Traffic Police': '#3b82f6',
    'Municipal Corporation': '#22c55e',
    'Transport': '#f59e0b',
    'Police': '#a855f7',
    'Smart City': '#06b6d4',
    'Unknown': '#64748b',
}

function deptColor(dept: string): string {
    return DEPT_COLOURS[dept] || DEPT_COLOURS['Unknown']
}

function MapFlyTo({ lat, lon }: { lat: number; lon: number }) {
    const map = useMap()
    useEffect(() => { map.flyTo([lat, lon], 16, { animate: true }) }, [lat, lon, map])
    return null
}

export default function MapPage() {
    const [cameras, setCameras] = useState<CameraFeature[]>([])
    const [loading, setLoading] = useState(true)
    const [statusFilter, setStatusFilter] = useState<string>('all')
    const [deptFilter, setDeptFilter] = useState<string>('all')
    const [codecFilter, setCodecFilter] = useState<string>('all')
    const [flyTo, setFlyTo] = useState<{ lat: number; lon: number } | null>(null)
    const [status, setStatus] = useState<{ total_cameras: number; live_cameras: number } | null>(null)

    const load = useCallback(async () => {
        setLoading(true)
        try {
            const [geo, st] = await Promise.all([getCamerasGeoJSON(), getIngestStatus()])
            setCameras(geo.features || [])
            setStatus(st)
        } catch (e) { console.error(e) }
        finally { setLoading(false) }
    }, [])

    useEffect(() => { load() }, [load])

    const handleSync = async () => {
        await syncCatalogue()
        setTimeout(load, 2000)
    }

    const filtered = cameras.filter(c => {
        const p = c.properties
        if (statusFilter === 'live' && !p.is_live) return false
        if (statusFilter === 'offline' && p.is_live) return false
        if (deptFilter !== 'all' && p.department !== deptFilter) return false
        if (codecFilter !== 'all' && p.codec !== codecFilter) return false
        return true
    })

    const depts = [...new Set(cameras.map(c => c.properties.department))].sort()
    const codecs = [...new Set(cameras.map(c => c.properties.codec).filter(Boolean))].sort()

    const defaultCenter: LatLngExpression = [23.0225, 72.5714] // Ahmedabad

    return (
        <div className="page-content no-padding" style={{ display: 'flex', flexDirection: 'column' }}>
            {/* Toolbar */}
            <div style={{ padding: '10px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <Layers size={14} style={{ color: 'var(--text-secondary)' }} />
                    <select className="input" style={{ width: 'auto', padding: '4px 8px' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                        <option value="all">All Status</option>
                        <option value="live">Live Only</option>
                        <option value="offline">Offline Only</option>
                    </select>
                    <select className="input" style={{ width: 'auto', padding: '4px 8px' }} value={deptFilter} onChange={e => setDeptFilter(e.target.value)}>
                        <option value="all">All Departments</option>
                        {depts.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                    <select className="input" style={{ width: 'auto', padding: '4px 8px' }} value={codecFilter} onChange={e => setCodecFilter(e.target.value)}>
                        <option value="all">All Codecs</option>
                        {codecs.map(c => <option key={c} value={c}>{c?.toUpperCase()}</option>)}
                    </select>
                </div>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
                    {status && (
                        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            <span style={{ color: 'var(--green)', fontWeight: 600 }}>{status.live_cameras}</span> live /&nbsp;
                            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{status.total_cameras}</span> total
                            &nbsp;·&nbsp;<span style={{ color: 'var(--text-muted)' }}>{filtered.length} shown</span>
                        </span>
                    )}
                    <button className="btn btn-ghost btn-sm" onClick={handleSync}>
                        <RefreshCw size={12} /> Sync Catalogue
                    </button>
                </div>
                {/* Legend */}
                <div style={{ display: 'flex', gap: 10, marginLeft: 12, flexWrap: 'wrap' }}>
                    {Object.entries(DEPT_COLOURS).map(([dept, col]) => (
                        <div key={dept} style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 11, color: 'var(--text-secondary)' }}>
                            <div style={{ width: 10, height: 10, borderRadius: '50%', background: col }} />
                            {dept}
                        </div>
                    ))}
                </div>
            </div>

            {/* Map */}
            <div style={{ flex: 1, position: 'relative' }}>
                {loading && (
                    <div style={{ position: 'absolute', inset: 0, background: 'rgba(11,15,26,0.7)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
                        <div className="spinner" /><span style={{ color: 'var(--text-secondary)' }}>Loading camera grid…</span>
                    </div>
                )}
                <MapContainer
                    center={defaultCenter}
                    zoom={12}
                    style={{ height: '100%', width: '100%' }}
                    zoomControl={true}
                >
                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    {flyTo && <MapFlyTo lat={flyTo.lat} lon={flyTo.lon} />}
                    {filtered.map(cam => {
                        const [lon, lat] = cam.geometry.coordinates
                        const p = cam.properties
                        const col = deptColor(p.department)
                        return (
                            <CircleMarker
                                key={p.id}
                                center={[lat, lon]}
                                radius={p.is_live ? 8 : 5}
                                pathOptions={{
                                    color: p.is_live ? col : '#6b7280',
                                    fillColor: p.is_live ? col : '#374151',
                                    fillOpacity: 0.85,
                                    weight: p.is_live ? 2 : 1,
                                }}
                                eventHandlers={{ click: () => setFlyTo({ lat, lon }) }}
                            >
                                <Popup>
                                    <div>
                                        <div className="popup-title">📷 {p.name}</div>
                                        <div className="popup-row">Dept: <span>{p.department}</span></div>
                                        <div className="popup-row">Status: <span style={{ color: p.is_live ? 'var(--green)' : 'var(--red)' }}>
                                            {p.is_live ? '🟢 Live' : '🔴 Offline'}
                                        </span></div>
                                        <div className="popup-row">Codec: <span>{p.codec?.toUpperCase() || 'Unknown'}</span></div>
                                        <div className="popup-row">Type: <span>{p.camera_type || 'fixed_dome'}</span></div>
                                        {p.address && <div className="popup-row">Address: <span>{p.address}</span></div>}
                                        <div style={{ width: 220, height: 130, marginTop: 8, borderRadius: 6, overflow: 'hidden', background: '#000' }}>
                                            <iframe
                                                src={`http://devam6205%40gmail.com:GAQA-H7HN-P2GE@103.250.160.189:8889/stream/${p.native_id}/?autoplay=true&muted=true`}
                                                title={p.name}
                                                style={{ width: '100%', height: '100%', border: 'none' }}
                                                allow="autoplay; fullscreen"
                                            />
                                        </div>
                                    </div>
                                </Popup>
                            </CircleMarker>
                        )
                    })}
                </MapContainer>
            </div>
        </div>
    )
}
