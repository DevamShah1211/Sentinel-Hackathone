/**
 * One place to see everything the platform knows about a registration.
 *
 * Alerts, the watchlist and plate search all used to show a plate as a bare
 * string with no way to ask "so what is this vehicle, and where has it been?".
 * Each screen answering that separately would mean three partial answers, so
 * they all open this instead: sightings, the vehicle record, the watchlist
 * entry that matched, and the evidence crop, in one panel.
 *
 * Everything shown is fetched live. Where a record is synthetic (the VAHAN
 * mock) the panel says so in place, because a reviewer must never mistake a
 * demonstration record for an authoritative one.
 */
import { useCallback, useEffect, useState } from 'react'
import {
    AlertTriangle, Camera, Car, Clock, FileText, MapPin, Shield, X,
} from 'lucide-react'
import { getPlateRoute, getVehicleDetails, searchDetections } from '../api/client'

export interface Sighting {
    id: string
    plate_text: string
    district?: string
    city?: string
    rto_valid?: boolean
    confidence: number
    detected_at: string
    crop_uri?: string
    camera_name?: string
    camera_department?: string
    camera_address?: string
    partial?: boolean
}

interface VehicleRecord {
    registration_number: string; owner_name: string; vehicle_class: string
    maker_model: string; fuel_type: string; colour: string
    registering_authority: string; registration_date?: string
    insurance_valid_upto?: string; insurance_expired: boolean
    is_blacklisted: boolean; is_authoritative: boolean; disclaimer?: string
}

/** One sighting as the route endpoint returns it: ordered in time, with the
 *  speed implied by the previous sighting and whether that speed is possible. */
interface RouteSighting {
    detection_id: string
    detected_at?: string
    camera_name?: string
    department?: string
    address?: string
    confidence?: number
    crop_uri?: string
    speed_kmh?: number | null
    impossible?: boolean
}

interface RouteData {
    plate: string
    total_sightings?: number
    sightings?: RouteSighting[]
    flagged_transitions?: number
}

const IST = { timeZone: 'Asia/Kolkata' } as const

function fmt(when?: string): string {
    if (!when) return '—'
    return new Date(when).toLocaleString('en-IN', IST) + ' IST'
}

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
    return (
        <div className="pd-field">
            <div className="pd-field-label">{label}</div>
            <div className="pd-field-value" style={mono ? { fontFamily: 'var(--font-mono)' } : undefined}>
                {value || '—'}
            </div>
        </div>
    )
}

export default function PlateDetailDrawer({ plate, onClose, context }: {
    plate: string | null
    onClose: () => void
    /** Extra rows supplied by the screen that opened the drawer, e.g. the alert. */
    context?: { label: string; value: string }[]
}) {
    const [sightings, setSightings] = useState<Sighting[]>([])
    const [vehicle, setVehicle] = useState<VehicleRecord | null>(null)
    const [route, setRoute] = useState<RouteData | null>(null)
    const [loading, setLoading] = useState(false)
    const [vehicleError, setVehicleError] = useState(false)

    const load = useCallback(async (p: string) => {
        setLoading(true)
        setVehicleError(false)
        setSightings([]); setVehicle(null); setRoute(null)
        // Each request is independent: a missing vehicle record must not stop the
        // sightings from rendering, which is the part an investigator needs most.
        const [s, v, r] = await Promise.allSettled([
            searchDetections({
                plate: p, fuzzy: true, limit: 100,
                actor: 'operator', purpose: 'investigation',
            }),
            getVehicleDetails(p),
            getPlateRoute(p),
        ])
        if (s.status === 'fulfilled') setSightings(s.value as Sighting[])
        if (v.status === 'fulfilled') setVehicle(v.value as VehicleRecord)
        else setVehicleError(true)
        if (r.status === 'fulfilled') setRoute(r.value as RouteData)
        setLoading(false)
    }, [])

    useEffect(() => { if (plate) load(plate) }, [plate, load])

    // Escape closes, which is what every reviewer will try first.
    useEffect(() => {
        if (!plate) return
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [plate, onClose])

    if (!plate) return null

    // Prefer the route endpoint's ordering: it sorts by time and computes the
    // speed between consecutive sightings. Search results are not guaranteed to
    // be in time order, which is what made "first seen" show the latest sighting.
    const ordered: RouteSighting[] = route?.sightings?.length
        ? route.sightings
        : [...sightings]
            .map(s => ({
                detection_id: s.id, detected_at: s.detected_at, camera_name: s.camera_name,
                department: s.camera_department, address: s.camera_address,
                confidence: s.confidence, crop_uri: s.crop_uri,
            }))
            .sort((a, b) => new Date(a.detected_at ?? 0).getTime() - new Date(b.detected_at ?? 0).getTime())

    const first = ordered[0]
    const last = ordered[ordered.length - 1]
    const cameras = new Set(ordered.map(s => s.camera_name).filter(Boolean))
    const crop = ordered.find(s => s.crop_uri)?.crop_uri ?? sightings.find(s => s.crop_uri)?.crop_uri
    const anyPartial = sightings.some(s => s.partial)
    const partialIds = new Set(sightings.filter(s => s.partial).map(s => s.id))
    const flagged = route?.flagged_transitions ?? 0
    // The RTO district the registration belongs to. The API derives it from the
    // plate, so it is available on any sighting of this vehicle.
    const registration = sightings.find(s => s.district || s.city || s.rto_valid === false)
    const topSpeed = ordered.reduce<number>((m, s) => Math.max(m, s.speed_kmh ?? 0), 0)

    return (
        <>
            <div className="pd-scrim" onClick={onClose} aria-hidden="true" />
            <aside className="pd-drawer" role="dialog" aria-label={`Details for ${plate}`}>
                <header className="pd-head">
                    <div>
                        <div className="pd-plate">{plate}</div>
                        <div className="pd-plate-sub">
                            {loading ? 'Loading…' : `${ordered.length} sighting${ordered.length === 1 ? '' : 's'} · ${cameras.size} camera${cameras.size === 1 ? '' : 's'}`}
                        </div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
                        <X size={14} />
                    </button>
                </header>

                <div className="pd-body">
                    {anyPartial && (
                        <div className="pd-warn">
                            <AlertTriangle size={14} aria-hidden="true" />
                            <span>
                                One or more reads are <strong>partial</strong>: detected consistently
                                but below full plate validation. Verify against the crop before acting.
                            </span>
                        </div>
                    )}

                    {crop && (
                        <section className="pd-section">
                            <div className="pd-section-title"><Camera size={12} /> Evidence crop</div>
                            <img className="pd-crop" src={crop} alt={`Plate crop for ${plate}`} />
                        </section>
                    )}

                    {context && context.length > 0 && (
                        <section className="pd-section">
                            <div className="pd-section-title"><Shield size={12} /> Watchlist match</div>
                            <div className="pd-fields">
                                {context.map(c => <Field key={c.label} label={c.label} value={c.value} />)}
                            </div>
                        </section>
                    )}

                    <section className="pd-section">
                        <div className="pd-section-title"><Clock size={12} /> Movement summary</div>
                        <div className="pd-fields">
                            <Field label="First seen" value={fmt(first?.detected_at)} />
                            <Field label="Last seen" value={fmt(last?.detected_at)} />
                            <Field label="Cameras" value={String(cameras.size)} />
                            <Field
                                label="Registered district"
                                value={registration?.district
                                    // Ahmedabad holds GJ-01 and GJ-27; naming the
                                    // city stops the two reading as unrelated places.
                                    ? registration.city && registration.city !== registration.district
                                        ? `${registration.district} (${registration.city})`
                                        : registration.district
                                    : (registration && registration.rto_valid === false
                                        ? 'Not an issued RTO district' : undefined)}
                            />
                            <Field
                                label="Fastest leg"
                                value={topSpeed > 0 ? `${topSpeed.toFixed(0)} km/h` : '—'}
                            />
                        </div>
                        {flagged > 0 && (
                            <div className="pd-warn" style={{ marginTop: 10 }}>
                                <AlertTriangle size={14} aria-hidden="true" />
                                <span>
                                    {flagged} transition{flagged === 1 ? '' : 's'} flagged as physically
                                    impossible for the time between sightings. The platform shows these
                                    rather than hiding them, so the reading can be challenged.
                                </span>
                            </div>
                        )}
                    </section>

                    <section className="pd-section">
                        <div className="pd-section-title"><Car size={12} /> Vehicle record</div>
                        {vehicleError && (
                            <div className="pd-empty">No vehicle record available for this registration.</div>
                        )}
                        {vehicle && (
                            <>
                                {!vehicle.is_authoritative && (
                                    <div className="pd-warn" style={{ marginBottom: 10 }}>
                                        <AlertTriangle size={14} aria-hidden="true" />
                                        <span>{vehicle.disclaimer ?? 'Synthetic record — not authoritative.'}</span>
                                    </div>
                                )}
                                <div className="pd-fields">
                                    <Field label="Owner" value={vehicle.owner_name} />
                                    <Field label="Make / model" value={vehicle.maker_model} />
                                    <Field label="Class" value={vehicle.vehicle_class} />
                                    <Field label="Colour" value={vehicle.colour} />
                                    <Field label="Fuel" value={vehicle.fuel_type} />
                                    <Field label="Registering authority" value={vehicle.registering_authority} />
                                    <Field label="Registered" value={vehicle.registration_date} />
                                    <Field
                                        label="Insurance valid to"
                                        value={vehicle.insurance_valid_upto
                                            ? `${vehicle.insurance_valid_upto}${vehicle.insurance_expired ? ' (expired)' : ''}`
                                            : undefined}
                                    />
                                </div>
                            </>
                        )}
                    </section>

                    <section className="pd-section">
                        <div className="pd-section-title">
                            <MapPin size={12} /> Sightings, newest first
                        </div>
                        {ordered.length === 0 && !loading && (
                            <div className="pd-empty">No sightings indexed for this plate.</div>
                        )}
                        <ol className="pd-timeline">
                            {[...ordered].reverse().map(s => (
                                <li key={s.detection_id} className="pd-timeline-item">
                                    <div
                                        className={`pd-timeline-dot${s.impossible ? ' is-flagged' : ''}`}
                                        aria-hidden="true"
                                    />
                                    <div style={{ minWidth: 0 }}>
                                        <div className="pd-timeline-cam">
                                            {s.camera_name ?? 'Unknown camera'}
                                            {partialIds.has(s.detection_id) && <span className="pd-partial-tag">PARTIAL</span>}
                                        </div>
                                        <div className="pd-timeline-meta">
                                            {fmt(s.detected_at)}
                                            {s.department ? ` · ${s.department}` : ''}
                                        </div>
                                        {s.address && <div className="pd-timeline-addr">{s.address}</div>}
                                        {s.speed_kmh != null && (
                                            <div className={`pd-timeline-speed${s.impossible ? ' is-flagged' : ''}`}>
                                                {s.impossible && <AlertTriangle size={11} aria-hidden="true" />}
                                                {s.speed_kmh.toFixed(0)} km/h from the previous sighting
                                                {s.impossible && ' — not physically possible'}
                                            </div>
                                        )}
                                    </div>
                                    <div className="pd-timeline-conf">
                                        {s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : ''}
                                    </div>
                                </li>
                            ))}
                        </ol>
                    </section>

                    <section className="pd-section">
                        <div className="pd-section-title"><FileText size={12} /> Accountability</div>
                        <div className="pd-note">
                            Opening this panel performed a plate search, which is written to the audit
                            trail with the signed-in operator and the stated purpose.
                        </div>
                    </section>
                </div>
            </aside>
        </>
    )
}
