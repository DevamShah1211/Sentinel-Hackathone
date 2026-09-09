import { useEffect, useState } from 'react'
import { Plus, Shield, Trash2, Upload } from 'lucide-react'
import { getWatchlist, addToWatchlist, removeFromWatchlist, bulkImportWatchlist } from '../api/client'
import PlateDetailDrawer from '../components/PlateDetailDrawer'

interface WatchlistEntry {
    id: string; plate_text: string; entity_type: string; reason: string;
    severity: string; case_ref?: string; description?: string;
    added_by?: string; active: boolean; created_at: string;
}

const REASON_OPTIONS = ['wanted', 'stolen', 'missing', 'blacklisted', 'suspicious']
const SEVERITY_OPTIONS = ['low', 'medium', 'high', 'critical']
const SEV_PILL: Record<string, string> = { low: 'pill-gray', medium: 'pill-blue', high: 'pill-yellow', critical: 'pill-red' }

export default function WatchlistPage() {
    const [entries, setEntries] = useState<WatchlistEntry[]>([])
    const [loading, setLoading] = useState(true)
    const [open, setOpen] = useState<WatchlistEntry | null>(null)
    const [form, setForm] = useState({ plate_text: '', reason: 'wanted', severity: 'high', case_ref: '', description: '' })
    const [adding, setAdding] = useState(false)
    const [showForm, setShowForm] = useState(false)

    const load = async () => {
        setLoading(true)
        try { setEntries(await getWatchlist()) }
        finally { setLoading(false) }
    }

    useEffect(() => { load() }, [])

    const handleAdd = async () => {
        if (!form.plate_text.trim()) return
        setAdding(true)
        try {
            // added_by is set by the API from the authenticated principal;
            // sending it from here would be a claim, not a record.
            await addToWatchlist({
                ...form,
                plate_text: form.plate_text.toUpperCase().trim(),
            })
            setForm({ plate_text: '', reason: 'wanted', severity: 'high', case_ref: '', description: '' })
            setShowForm(false)
            load()
        } finally { setAdding(false) }
    }

    const handleRemove = async (id: string) => {
        if (!confirm('Deactivate this watchlist entry?')) return
        await removeFromWatchlist(id)
        load()
    }

    const handleBulkImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return
        const resp = await bulkImportWatchlist(file)
        alert(`Imported ${resp.created} entries. Errors: ${resp.errors?.length || 0}`)
        load()
        e.target.value = ''
    }

    const activeEntries = entries.filter(e => e.active)
    const critical = activeEntries.filter(e => e.severity === 'critical').length
    const high = activeEntries.filter(e => e.severity === 'high').length

    return (
        <div className="page-content">
            {/* Header */}
            <div className="section-header">
                <div>
                    <h1 style={{ fontSize: 20, fontWeight: 700 }}>Watchlist</h1>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                        {activeEntries.length} active {activeEntries.length === 1 ? 'entry' : 'entries'} · {critical} critical · {high} high
                    </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                    <label className="btn btn-ghost btn-sm" style={{ cursor: 'pointer' }}>
                        <Upload size={13} /> Bulk CSV
                        <input type="file" accept=".csv" style={{ display: 'none' }} onChange={handleBulkImport} />
                    </label>
                    <button className="btn btn-primary btn-sm" onClick={() => setShowForm(s => !s)}>
                        <Plus size={13} /> Add Entry
                    </button>
                </div>
            </div>

            {/* Add form */}
            {showForm && (
                <div className="watchlist-add-form">
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 14, color: 'var(--accent)' }}>
                        New Watchlist Entry
                    </div>
                    <div className="form-grid">
                        <div className="form-field">
                            <label className="form-label">Plate Number *</label>
                            <input className="input" style={{ fontFamily: 'var(--font-mono)', fontSize: 15, letterSpacing: 2 }}
                                placeholder="GJ01AB1234"
                                value={form.plate_text}
                                onChange={e => setForm(f => ({ ...f, plate_text: e.target.value.toUpperCase() }))}
                            />
                        </div>
                        <div className="form-field">
                            <label className="form-label">Case Reference</label>
                            <input className="input" placeholder="FIR/2026/001"
                                value={form.case_ref}
                                onChange={e => setForm(f => ({ ...f, case_ref: e.target.value }))}
                            />
                        </div>
                        <div className="form-field">
                            <label className="form-label">Reason</label>
                            <select className="input" value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}>
                                {REASON_OPTIONS.map(r => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
                            </select>
                        </div>
                        <div className="form-field">
                            <label className="form-label">Severity</label>
                            <select className="input" value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}>
                                {SEVERITY_OPTIONS.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="form-field" style={{ marginTop: 10 }}>
                        <label className="form-label">Description / Notes</label>
                        <textarea className="input" rows={2} placeholder="Reason for adding to watchlist…"
                            value={form.description}
                            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                        />
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                        <button className="btn btn-primary" onClick={handleAdd} disabled={adding || !form.plate_text}>
                            {adding ? <div className="spinner" /> : <Plus size={14} />} Add to Watchlist
                        </button>
                        <button className="btn btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
                    </div>
                    <div style={{ marginTop: 10, padding: '8px 12px', background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)', borderRadius: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
                        💡 Bulk import CSV format: <code>plate,reason,severity,case_ref,description</code>
                    </div>
                </div>
            )}

            {/* Table */}
            {loading
                ? <div className="loading-overlay"><div className="spinner" /></div>
                : entries.length === 0
                    ? (
                        <div className="empty-state">
                            <div className="empty-state-icon"><Shield size={24} /></div>
                            <div className="empty-state-title">No registrations on the watchlist</div>
                            <div className="empty-state-body">
                                Add a plate above, or bulk import a CSV. Any detection matching an
                                active entry raises an alert immediately, and the match is recorded
                                with the operator who armed it.
                            </div>
                        </div>
                    )
                    : (
                        <div className="card" style={{ padding: 0 }}>
                            <div className="table-wrap">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Plate</th>
                                            <th>Reason</th>
                                            <th>Severity</th>
                                            <th>Case Ref</th>
                                            <th>Added By</th>
                                            <th>Added</th>
                                            <th>Status</th>
                                            <th></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {entries.map(e => (
                                            <tr
                                                key={e.id}
                                                className="is-clickable"
                                                title="Open full vehicle detail"
                                                onClick={() => setOpen(e)}
                                            >
                                                <td><span className="plate-chip">{e.plate_text}</span></td>
                                                <td style={{ textTransform: 'capitalize' }}>{e.reason}</td>
                                                <td><span className={`badge-pill ${SEV_PILL[e.severity] || 'pill-gray'}`}>{e.severity}</span></td>
                                                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{e.case_ref || '—'}</td>
                                                <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{e.added_by || '—'}</td>
                                                <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                                                    {new Date(e.created_at).toLocaleDateString('en-IN')}
                                                </td>
                                                <td>
                                                    {e.active
                                                        ? <span className="badge-pill pill-green">Active</span>
                                                        : <span className="badge-pill pill-gray">Inactive</span>
                                                    }
                                                </td>
                                                <td onClick={ev => ev.stopPropagation()}>
                                                    {e.active && (
                                                        <button className="btn btn-ghost btn-sm" style={{ color: 'var(--red)' }} onClick={() => handleRemove(e.id)}>
                                                            <Trash2 size={12} />
                                                        </button>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )
            }
            <PlateDetailDrawer
                plate={open?.plate_text ?? null}
                onClose={() => setOpen(null)}
                context={open ? [
                    { label: 'Reason', value: open.reason },
                    { label: 'Severity', value: open.severity },
                    { label: 'Case reference', value: open.case_ref || '—' },
                    { label: 'Added by', value: open.added_by || '—' },
                    { label: 'Added on', value: new Date(open.created_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST' },
                    { label: 'Entry status', value: open.active ? 'Active — alerts armed' : 'Inactive' },
                    { label: 'Entity type', value: open.entity_type || '—' },
                    { label: 'Description', value: open.description || '—' },
                ] : undefined}
            />
        </div>
    )
}
