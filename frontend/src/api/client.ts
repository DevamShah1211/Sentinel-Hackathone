import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const TOKEN_KEY = 'sentinel.token'
const USER_KEY = 'sentinel.user'

const api = axios.create({ baseURL: BASE })

// ─── Session ────────────────────────────────────────────────────

export interface AuthUser {
    id: string; email: string; username: string
    role: string; department?: string | null
}

export const getToken = () => localStorage.getItem(TOKEN_KEY)

export const getStoredUser = (): AuthUser | null => {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    try { return JSON.parse(raw) as AuthUser } catch { return null }
}

export const setSession = (token: string, user: AuthUser) => {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export const clearSession = () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
}

api.interceptors.request.use(config => {
    const token = getToken()
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
})

// A 401 means the token is gone or expired: drop the session so the app returns
// to the login screen rather than looping on failed requests.
api.interceptors.response.use(
    response => response,
    error => {
        if (error?.response?.status === 401 && getToken()) {
            clearSession()
            window.dispatchEvent(new CustomEvent('sentinel:signed-out'))
        }
        return Promise.reject(error)
    },
)

export const login = (email: string, password: string) =>
    api.post('/auth/login', { email, password }).then(r => r.data)

export const getRoleModel = () => api.get('/auth/roles').then(r => r.data)

// ─── Cameras ────────────────────────────────────────────────────
export const getCamerasGeoJSON = () => api.get('/cameras/geojson').then(r => r.data)
export const getCameras = (params?: Record<string, unknown>) => api.get('/cameras', { params }).then(r => r.data)
export const getCameraStats = () => api.get('/cameras/stats').then(r => r.data)
export const syncCatalogue = () => api.post('/ingest/sync').then(r => r.data)
export const getIngestStatus = () => api.get('/ingest/status').then(r => r.data)

// ─── Detections ─────────────────────────────────────────────────
export const searchDetections = (params: Record<string, unknown>) =>
    api.get('/detections', { params }).then(r => r.data)
export const getRecentDetections = () => api.get('/detections/recent').then(r => r.data)
export const getPlateRoute = (plate: string, params?: Record<string, unknown>) =>
    api.get(`/detections/route/${encodeURIComponent(plate)}`, { params }).then(r => r.data)

// ─── Alerts ─────────────────────────────────────────────────────
export const getAlerts = (params?: Record<string, unknown>) => api.get('/alerts', { params }).then(r => r.data)
export const acknowledgeAlert = (id: string, operator: string, notes?: string) =>
    api.patch(`/alerts/${id}/acknowledge`, null, { params: { operator, notes } }).then(r => r.data)
export const resolveAlert = (id: string) => api.patch(`/alerts/${id}/resolve`).then(r => r.data)
export const getAlertStats = () => api.get('/alerts/stats').then(r => r.data)

// ─── Watchlist ──────────────────────────────────────────────────
export const getWatchlist = () => api.get('/watchlist').then(r => r.data)
export const addToWatchlist = (payload: Record<string, unknown>) =>
    api.post('/watchlist', payload).then(r => r.data)
export const removeFromWatchlist = (id: string) => api.delete(`/watchlist/${id}`).then(r => r.data)
export const bulkImportWatchlist = (file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return api.post('/watchlist/bulk-import', fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
}

// ─── Analytics ──────────────────────────────────────────────────
export const getAnalyticsSummary = () => api.get('/analytics/summary').then(r => r.data)
export const getTopPlates = () => api.get('/analytics/top-plates').then(r => r.data)
export const getDetectionsByHour = () => api.get('/analytics/detections-by-hour').then(r => r.data)
export const downloadReport = (format: 'xlsx' | 'pdf' = 'xlsx', params?: Record<string, unknown>) =>
    api.get(`/analytics/report/${format}`, { responseType: 'blob', params }).then(r => r.data)

/** Vehicle particulars for a plate. Mock-backed until VAHAN credentials exist —
 *  the response says so via `source` and `is_authoritative`. */
export const getVehicleDetails = (plate: string, params?: Record<string, unknown>) =>
    api.get(`/analytics/vehicle/${encodeURIComponent(plate)}`, { params }).then(r => r.data)

export const getAuditTrail = (params?: Record<string, unknown>) =>
    api.get('/analytics/audit', { params }).then(r => r.data)

/** Trigger a browser download for a report blob. */
export const saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
}

export default api
