import { useState, useCallback } from 'react'
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup } from 'react-leaflet'
import { Search, Map, Download, X } from 'lucide-react'
import { searchDetections, getPlateRoute, downloadReport } from '../api/client'

interface Detection {
    id: string; plate_text: string; confidence: number;
    detected_at: string; crop_uri?: string;
    camera_name: string; camera_department: string;
    camera_lat?: number; camera_lon?: number; camera_address?: string;
}

interface RouteSighting {
    index: number; plate_text: string; confidence: number; detected_at: string;
    camera_name: string; lat?: number; lon?: number; department: string; address?: string;
    speed_kmh?: number; impossible: boolean; crop_uri?: string;
}

interface RouteData {
    plate: string; total_sightings: number; sightings: RouteSighting[];
    route_geojson: { type: string; coordinates: [number, number][] };
}

function ConfBar({ value }: { value: number }) {
    const pct = Math.round(value * 100)
    const color = pct >= 85 ? 'var(--green)' : pct >= 60 ? 'var(--yellow)' : 'var(--red)'
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div className="conf-bar"><div className="conf-bar-fill" style={{ width: `${pct}%`, background: color }} /></div>
            <span style={{ fontSize: 11, color, fontWeight: 600 }}>{pct}%</span>
        </div>
    )
}

function RoutePanel({ route, onClose }: { route: RouteData; onClose: () => void }) {
    const coords: [number, number][] = route.route_geojson.coordinates
        .filter(([lon, lat]) => lat && lon)
        .map(([lon, lat]) => [lat, lon])

    const center: [number, number] = coords.length > 0 ? coords[Math.floor(coords.length / 2)] : [23.0225, 72.5714]

    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
            <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 16, width: '90%', maxWidth: 1000, height: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div>
                        <span style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: 1 }}>Route Reconstruction</span>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, letterSpacing: 2 }}>{route.plate}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span className="badge-pill pill-blue">{route.total_sightings} sightings</span>
                        <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={14} /></button>
                    </div>
                </div>
                <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                    {/* Map */}
                    <div style={{ flex: 1 }}>
                        <MapContainer center={center} zoom={12} style={{ height: '100%' }}>
                            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; OpenStreetMap' />
                            {coords.length > 1 && <Polyline positions={coords} pathOptions={{ color: '#3b82f6', weight: 3, dashArray: '8 4' }} />}
                            {route.sightings.filter(s => s.lat && s.lon).map(s => (
                                <CircleMarker key={s.index} center={[s.lat!, s.lon!]} radius={8}
                                    pathOptions={{ color: s.impossible ? '#ef4444' : '#3b82f6', fillColor: s.impossible ? '#ef4444' : '#1d4ed8', fillOpacity: 0.9, weight: 2 }}>
                                    <Popup>
                                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>#{s.index + 1} — {s.camera_name}</div>
                                        <div style={{ fontSize: 12, color: 'gray' }}>{new Date(s.detected_at).toLocaleString()}</div>
                                        {s.speed_kmh && <div style={{ fontSize: 12, color: s.impossible ? 'red' : 'green' }}>~{s.speed_kmh} km/h{s.impossible ? ' ⚠️ impossible' : ''}</div>}
                                    </Popup>
                                </CircleMarker>
                            ))}
                        </MapContainer>
                    </div>
                    {/* Timeline */}
                    <div style={{ width: 280, borderLeft: '1px solid var(--border)', overflowY: 'auto', padding: 12 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10, fontWeight: 600 }}>Movement Timeline</div>
                        {route.sightings.map(s => (
                            <div key={s.index} className="route-stop">
                                <div className={`route-stop-num${s.impossible ? ' impossible' : ''}`}>{s.index + 1}</div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 600 }}>{s.camera_name}</div>
                                    <div style={{ color: 'var(--text-muted)' }}>{new Date(s.detected_at).toLocaleTimeString()}</div>
                                    {s.speed_kmh != null && (
                                        <div style={{ color: s.impossible ? 'var(--red)' : 'var(--green)', fontSize: 11 }}>
                                            {s.speed_kmh} km/h {s.impossible && '⚠️ Impossible'}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

export default function SearchPage() {
    const [query, setQuery] = useState('')
    const [fuzzy, setFuzzy] = useState(true)
    const [results, setResults] = useState<Detection[]>([])
    const [loading, setLoading] = useState(false)
    const [route, setRoute] = useState<RouteData | null>(null)
    const [searched, setSearched] = useState(false)

    const handleSearch = useCallback(async () => {
        if (!query.trim()) return
        setLoading(true)
        setSearched(true)
        try {
            const data = await searchDetections({ plate: query.trim(), fuzzy, limit: 100 })
            setResults(data)
        } finally { setLoading(false) }
    }, [query, fuzzy])

    const showRoute = async (plate: string) => {
        const data = await getPlateRoute(plate)
        setRoute(data)
    }

    const handleDownload = async () => {
        const blob = await downloadReport()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `sentinel_report_${Date.now()}.xlsx`; a.click()
        URL.revokeObjectURL(url)
    }

    return (
        <div className="page-content">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h1 style={{ fontSize: 20, fontWeight: 700 }}>Plate Search</h1>
                <button className="btn btn-ghost btn-sm" onClick={handleDownload}>
                    <Download size={13} /> Export XLSX Report
                </button>
            </div>

            {/* Search bar */}
            <div className="search-bar">
                <input
                    className="input"
                    style={{ fontFamily: 'var(--font-mono)', fontSize: 16, letterSpacing: 2, maxWidth: 320 }}
                    placeholder="GJ01AB1234"
                    value={query}
                    onChange={e => setQuery(e.target.value.toUpperCase())}
                    onKeyDown={e => e.key === 'Enter' && handleSearch()}
                />
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                    <input type="checkbox" checked={fuzzy} onChange={e => setFuzzy(e.target.checked)} />
                    Fuzzy match
                </label>
                <button className="btn btn-primary" onClick={handleSearch} disabled={loading}>
                    {loading ? <div className="spinner" /> : <Search size={14} />}
                    Search
                </button>
            </div>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
                Supports exact, partial, and fuzzy plate matching (tolerates OCR errors via pg_trgm)
            </div>

            {/* Results */}
            {loading && <div className="loading-overlay"><div className="spinner" /><span>Searching…</span></div>}

            {!loading && searched && results.length === 0 && (
                <div className="empty-state">
                    <Search size={40} />
                    <p>No detections found for "<strong>{query}</strong>"</p>
                    <p style={{ fontSize: 12 }}>Try enabling fuzzy match or searching a partial plate</p>
                </div>
            )}

            {!loading && results.length > 0 && (
                <>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                            <strong style={{ color: 'var(--text-primary)' }}>{results.length}</strong> sighting{results.length !== 1 ? 's' : ''} found
                        </span>
                        <button className="btn btn-ghost btn-sm" onClick={() => showRoute(query)}>
                            <Map size={13} /> Show Route on Map
                        </button>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {results.map(det => (
                            <div key={det.id} className="detection-card">
                                {det.crop_uri
                                    ? <img src={det.crop_uri} alt="plate crop" className="detection-crop" />
                                    : <div className="detection-crop-placeholder">No crop</div>
                                }
                                <div className="detection-info">
                                    <div className="detection-plate" style={{ fontFamily: 'var(--font-mono)', fontSize: 20, letterSpacing: 2 }}>
                                        {det.plate_text}
                                    </div>
                                    <ConfBar value={det.confidence} />
                                    <div className="detection-meta">
                                        🕐 {new Date(det.detected_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST
                                    </div>
                                    <div className="detection-camera">
                                        📷 {det.camera_name} — {det.camera_department}
                                        {det.camera_address && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> · {det.camera_address}</span>}
                                    </div>
                                </div>
                                <button className="btn btn-ghost btn-sm" onClick={() => showRoute(det.plate_text)}>
                                    <Map size={12} /> Route
                                </button>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {route && <RoutePanel route={route} onClose={() => setRoute(null)} />}
        </div>
    )
}
