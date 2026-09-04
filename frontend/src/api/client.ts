import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE || '/api/v1'

const api = axios.create({ baseURL: BASE })

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
export const downloadReport = () =>
    api.get('/analytics/report/xlsx', { responseType: 'blob' }).then(r => r.data)

export default api
