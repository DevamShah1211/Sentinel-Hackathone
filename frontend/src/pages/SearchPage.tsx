import { useState, useCallback } from 'react'
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup } from 'react-leaflet'
import { AlertTriangle, Car, Download, Map, Search, X } from 'lucide-react'
import {
    downloadReport, getPlateRoute, getVehicleDetails, saveBlob, searchDetections,
} from '../api/client'

interface VehicleDetails {
    registration_number: string; owner_name: string; vehicle_class: string
    maker_model: string; fuel_type: string; colour: string
    registering_authority: string; registration_date?: string
    insurance_valid_upto?: string; insurance_expired: boolean
    puc_valid_upto?: string; puc_expired: boolean
    is_blacklisted: boolean; blacklist_reason?: string
    source: string; is_authoritative: boolean; disclaimer?: string
}

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
    flagged_transitions?: number;
    route_geojson: { type: string; coordinates: [number, number][] };
    /** Road-network interpolation from OSRM. Presentation only — the straight
     *  line between sightings is what the data actually supports. */
    road_snapped_geojson?: { type: string; coordinates: [number, number][] } | null;
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

    // The road-snapped path is an interpolation over the street network, drawn
    // beneath the straight line so the two are visually distinguishable.
    const snapped: [number, number][] = (route.road_snapped_geojson?.coordinates ?? [])
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
                        <span className="badge-pill pill-blue">
                            {route.total_sightings} sighting{route.total_sightings === 1 ? '' : 's'}
                        </span>
                        {route.total_sightings === 1 && (
                            <span className="badge-pill" style={{ background: 'var(--bg-input)', color: 'var(--text-secondary)' }}>
                                no route — seen once
                            </span>
                        )}
                        {!!route.flagged_transitions && (
                            <span className="badge-pill" style={{ background: 'var(--red-glow)', color: 'var(--red)' }}>
                                <AlertTriangle size={11} style={{ verticalAlign: -1 }} />{' '}
                                {route.flagged_transitions} implausible
                            </span>
                        )}
                        <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={14} /></button>
                    </div>
                </div>
                <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                    {/* Map */}
                    <div style={{ flex: 1, position: 'relative' }}>
                        <div style={{
                            position: 'absolute', bottom: 10, left: 10, zIndex: 500,
                            background: 'rgba(15,23,33,0.85)', border: '1px solid var(--border)',
                            borderRadius: 6, padding: '6px 10px', fontSize: 11, lineHeight: 1.7,
                            color: 'var(--text-secondary)', pointerEvents: 'none',
                        }}>
                            <div><span style={{ display: 'inline-block', width: 18, borderTop: '2px dashed #3b82f6', verticalAlign: 3 }} /> sighting sequence</div>
                            {snapped.length > 1 && (
                                <div><span style={{ display: 'inline-block', width: 18, borderTop: '4px solid rgba(34,197,94,0.6)', verticalAlign: 3 }} /> road interpolation</div>
                            )}
                            <div><span style={{ color: 'var(--red)' }}>●</span> implausible transition</div>
                        </div>
                        <MapContainer center={center} zoom={12} style={{ height: '100%' }}>
                            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; OpenStreetMap' />
                            {snapped.length > 1 && (
                                <Polyline positions={snapped} pathOptions={{ color: '#22c55e', weight: 5, opacity: 0.45 }} />
                            )}
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
    const [purpose, setPurpose] = useState('investigation')
    const [caseRef, setCaseRef] = useState('')
    const [vehicle, setVehicle] = useState<VehicleDetails | null>(null)
    const [vehicleLoading, setVehicleLoading] = useState(false)

    const handleSearch = useCallback(async () => {
        if (!query.trim()) return
        setLoading(true)
        setSearched(true)
        setVehicle(null)
        try {
            // actor/purpose/case_ref are recorded in the audit trail — access to
            // vehicle movement data is always attributable.
            const data = await searchDetections({
                plate: query.trim(), fuzzy, limit: 100,
                actor: 'operator', purpose: purpose || 'investigation',
                case_ref: caseRef || undefined,
            })
            setResults(data)
        } finally { setLoading(false) }
    }, [query, fuzzy, purpose, caseRef])

    const showRoute = async (plate: string) => {
        const data = await getPlateRoute(plate, {
            actor: 'operator', purpose: purpose || 'investigation',
            case_ref: caseRef || undefined,
        })
        setRoute(data)
    }

    const lookupVehicle = async (plate: string) => {
        setVehicleLoading(true)
        try {
            const data = await getVehicleDetails(plate, {
                actor: 'operator', purpose: purpose || 'investigation',
                case_ref: caseRef || undefined,
            })
            setVehicle(data)
        } catch {
            setVehicle(null)
        } finally { setVehicleLoading(false) }
    }

    const handleDownload = async (format: 'xlsx' | 'pdf') => {
        const blob = await downloadReport(format, {
            plate: query.trim() || undefined,
            actor: 'operator', purpose: 'submission-artefact',
        })
        saveBlob(blob, `sentinel_report_${Date.now()}.${format}`)
    }

    return (
        <div className="page-content">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h1 style={{ fontSize: 20, fontWeight: 700 }}>Plate Search</h1>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload('xlsx')}>
                        <Download size={13} /> XLSX
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload('pdf')}>
                        <Download size={13} /> PDF
                    </button>
                </div>
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

            {/* Purpose binding — recorded in the audit trail with every search. */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
                    Purpose
                </span>
                <select
                    className="input"
                    style={{ maxWidth: 190, fontSize: 12, padding: '5px 8px' }}
                    value={purpose}
                    onChange={e => setPurpose(e.target.value)}
                >
                    <option value="investigation">Investigation</option>
                    <option value="stolen-vehicle">Stolen vehicle</option>
                    <option value="traffic-enforcement">Traffic enforcement</option>
                    <option value="missing-person">Missing person</option>
                    <option value="verification">Verification</option>
                </select>
                <input
                    className="input"
                    style={{ maxWidth: 190, fontSize: 12, padding: '5px 8px' }}
                    placeholder="Case ref (e.g. FIR/2026/001)"
                    value={caseRef}
                    onChange={e => setCaseRef(e.target.value)}
                />
            </div>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
                Supports exact, partial, and fuzzy plate matching (tolerates OCR errors via pg_trgm).
                Every search is recorded in the audit trail with its stated purpose.
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
                        <div style={{ display: 'flex', gap: 8 }}>
                            <button className="btn btn-ghost btn-sm" onClick={() => lookupVehicle(results[0].plate_text)}>
                                {vehicleLoading ? <div className="spinner" /> : <Car size={13} />} Vehicle details
                            </button>
                            <button className="btn btn-ghost btn-sm" onClick={() => showRoute(query)}>
                                <Map size={13} /> Show Route on Map
                            </button>
                        </div>
                    </div>

                    {vehicle && (
                        <div style={{
                            border: '1px solid var(--border)', borderRadius: 10, padding: 14,
                            marginBottom: 12, background: 'var(--bg-card)',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Car size={15} />
                                    <strong style={{ fontFamily: 'var(--font-mono)', letterSpacing: 1.5 }}>
                                        {vehicle.registration_number}
                                    </strong>
                                    {vehicle.is_blacklisted && (
                                        <span className="badge-pill" style={{ background: 'var(--red-glow)', color: 'var(--red)' }}>
                                            BLACKLISTED
                                        </span>
                                    )}
                                </div>
                                <button className="btn btn-ghost btn-sm" onClick={() => setVehicle(null)}><X size={13} /></button>
                            </div>

                            {/* A mock record must never read as authoritative. */}
                            {!vehicle.is_authoritative && (
                                <div style={{
                                    display: 'flex', gap: 6, alignItems: 'flex-start',
                                    background: 'var(--yellow-glow, rgba(234,179,8,0.12))',
                                    border: '1px solid rgba(234,179,8,0.35)', borderRadius: 6,
                                    padding: '7px 10px', marginBottom: 12, fontSize: 11.5,
                                    color: 'var(--yellow, #eab308)',
                                }}>
                                    <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                                    <span>{vehicle.disclaimer ?? 'Synthetic record — not authoritative.'}</span>
                                </div>
                            )}

                            <div style={{
                                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                                gap: '8px 18px', fontSize: 12.5,
                            }}>
                                {([
                                    ['Owner', vehicle.owner_name],
                                    ['Make / model', vehicle.maker_model],
                                    ['Class', vehicle.vehicle_class],
                                    ['Colour', vehicle.colour],
                                    ['Fuel', vehicle.fuel_type],
                                    ['Registering authority', vehicle.registering_authority],
                                ] as const).map(([label, value]) => (
                                    <div key={label}>
                                        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.6 }}>
                                            {label}
                                        </div>
                                        <div>{value}</div>
                                    </div>
                                ))}
                                <div>
                                    <div style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.6 }}>
                                        Insurance
                                    </div>
                                    <div style={{ color: vehicle.insurance_expired ? 'var(--red)' : undefined }}>
                                        {vehicle.insurance_valid_upto ?? '—'}{vehicle.insurance_expired ? ' (expired)' : ''}
                                    </div>
                                </div>
                                <div>
                                    <div style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.6 }}>
                                        PUC
                                    </div>
                                    <div style={{ color: vehicle.puc_expired ? 'var(--red)' : undefined }}>
                                        {vehicle.puc_valid_upto ?? '—'}{vehicle.puc_expired ? ' (expired)' : ''}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
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
