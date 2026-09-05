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
        // How this camera's coordinates were arrived at.
        geo_source?: string; geo_confidence?: number; district?: string;
    }
}

/** Plain-language provenance for a camera's coordinates. The catalogue publishes
 *  no locations, so every position is derived and the map says how. */
const GEO_SOURCE_LABEL: Record<string, string> = {
    manual: 'Hand-verified against the site named in the catalogue',
    nominatim: 'Geocoded from the camera name (OpenStreetMap)',
    district_centroid: 'Approximate — district centroid only',
    unresolved: 'Not resolved',
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

/**
 * Preview inside a map popup.
 *
 * A still frame from the relay rather than a live stream: popups open and close
 * constantly while panning, and holding a video connection per click would keep
 * upstream connections open for cameras nobody is looking at any more.
 */
function PopupPreview({ cam }: { cam: CameraFeature['properties'] }) {
    const [failed, setFailed] = useState(false)
    const [loaded, setLoaded] = useState(false)

    if (failed) {
        return (
            <div style={{
                width: '100%', height: '100%', display: 'flex', alignItems: 'center',
                justifyContent: 'center', color: '#8b95a5', fontSize: 11,
            }}>
                Preview unavailable
            </div>
        )
    }

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            <img
                src={`/api/v1/cameras/live/${encodeURIComponent(cam.native_id)}/snapshot`}
                alt={`Snapshot from ${cam.name}`}
                onLoad={() => setLoaded(true)}
                onError={() => setFailed(true)}
                style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
            {!loaded && (
                <div style={{
                    position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
                    justifyContent: 'center', background: '#000', color: '#8b95a5', fontSize: 11,
                }}>
                    Loading…
                </div>
            )}
        </div>
    )
}

function MapFlyTo({ lat, lon }: { lat: number; lon: number }) {
    const map = useMap()
    useEffect(() => { map.flyTo([lat, lon], 16, { animate: true }) }, [lat, lon, map])
    return null
}

/**
 * Fit the view to every camera once they load.
 *
 * Opening on Ahmedabad hid the cameras in Junagadh, Rajkot, Navsari and Kutch,
 * which is precisely the statewide coverage Model 1 is meant to show. Refitting
 * only when the camera *set* changes leaves the operator's own panning alone.
 */
function FitToCameras({ points }: { points: [number, number][] }) {
    const map = useMap()
    const signature = points.length
    useEffect(() => {
        if (points.length === 0) return
        if (points.length === 1) {
            map.setView(points[0], 13)
            return
        }
        map.fitBounds(points, { padding: [48, 48], maxZoom: 12 })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [map, signature])
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

    // Gujarat, used only until the cameras load and the view is fitted to them.
    const defaultCenter: LatLngExpression = [22.6, 71.6]

    const cameraPoints = filtered
        .map(c => c.geometry.coordinates)
        .filter(([lon, lat]) => Number.isFinite(lat) && Number.isFinite(lon))
        .map(([lon, lat]) => [lat, lon] as [number, number])

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
                    zoom={7}
                    preferCanvas
                    style={{ height: '100%', width: '100%' }}
                    zoomControl={true}
                >
                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    <FitToCameras points={cameraPoints} />
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
                                        {p.district && <div className="popup-row">District: <span>{p.district}</span></div>}
                                        {p.address && <div className="popup-row">Address: <span>{p.address}</span></div>}
                                        {p.geo_source && (
                                            <div className="popup-row" style={{ marginTop: 4 }}>
                                                Location:{' '}
                                                <span style={{ color: (p.geo_confidence ?? 0) >= 0.8 ? 'var(--green)' : 'var(--yellow, #eab308)' }}>
                                                    {GEO_SOURCE_LABEL[p.geo_source] ?? p.geo_source}
                                                </span>
                                            </div>
                                        )}
                                        <div style={{ width: 220, height: 130, marginTop: 8, borderRadius: 6, overflow: 'hidden', background: '#000' }}>
                                            {/* Streams play through the platform's authenticated proxy — no
                                                sandbox credential is ever placed in the page. */}
                                            <PopupPreview cam={p} />
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
