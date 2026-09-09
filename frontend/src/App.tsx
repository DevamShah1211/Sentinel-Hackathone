import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Activity, BarChart2, Bell, LogOut, Map, Monitor, Search, Shield } from 'lucide-react'
import LoginPage from './pages/LoginPage'

// Routes are split so the first paint does not wait on every page's
// dependencies. Leaflet and Recharts are the expensive ones — the map's tile
// engine and the charting library together dominated the bundle, and an
// operator opening the alerts page was downloading both before anything
// rendered. Each page now arrives when it is first visited.
//
// LoginPage is deliberately NOT lazy: it is the first thing an unauthenticated
// user sees, so splitting it would add a network round trip to the one screen
// that must appear instantly.
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const MapPage = lazy(() => import('./pages/MapPage'))
const VideoWallPage = lazy(() => import('./pages/VideoWallPage'))
const SearchPage = lazy(() => import('./pages/SearchPage'))
const AlertsPage = lazy(() => import('./pages/AlertsPage'))
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'))
const HealthPage = lazy(() => import('./pages/HealthPage'))

// Prefetch the rest once the first page is interactive. The operator pays no
// wait when they navigate, but the initial render was never blocked on it.
function prefetchRoutes() {
    void import('./pages/MapPage')
    void import('./pages/VideoWallPage')
    void import('./pages/SearchPage')
    void import('./pages/AlertsPage')
    void import('./pages/WatchlistPage')
    void import('./pages/HealthPage')
}
import { useAlertWebSocket, type WsStatus } from './hooks/useAlertWebSocket'
import Toast from './components/Toast'
import { clearSession, getStoredUser, type AuthUser } from './api/client'

const NAV = [
    { to: '/', label: 'Dashboard', Icon: BarChart2 },
    { to: '/map', label: 'Camera Map', Icon: Map },
    { to: '/wall', label: 'Video Wall', Icon: Monitor },
    { to: '/search', label: 'Plate Search', Icon: Search },
    { to: '/alerts', label: 'Alerts', Icon: Bell },
    { to: '/watchlist', label: 'Watchlist', Icon: Shield },
    { to: '/health', label: 'Grid Health', Icon: Activity },
] as const

const PAGE_TITLES: Record<string, string> = {
    '/': 'Dashboard',
    '/map': 'Camera Map & GIS Registry',
    '/wall': 'Live Video Wall',
    '/search': 'Plate Search & Route Reconstruction',
    '/alerts': 'Live Alerts',
    '/watchlist': 'Watchlist Management',
    '/health': 'Grid Health & Scene Analytics',
}

function Sidebar({ newAlertCount }: { newAlertCount: number }) {
    return (
        <nav className="sidebar" aria-label="Main navigation">
            <div className="sidebar-logo">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
                SENTINEL
            </div>
            <div className="sidebar-nav">
                {NAV.map(({ to, label, Icon }) => {
                    const badge = to === '/alerts' ? newAlertCount : 0
                    return (
                        <NavLink
                            key={to}
                            to={to}
                            end={to === '/'}
                            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
                        >
                            <Icon size={16} aria-hidden="true" />
                            {label}
                            {badge > 0 && (
                                <span className="badge" aria-label={`${badge} new alerts`}>
                                    {badge > 99 ? '99+' : badge}
                                </span>
                            )}
                        </NavLink>
                    )
                })}
            </div>
            <div className="sidebar-footer">
                Gujarat CCTV Hackathon 2026<br />
                Model 1 + Model 2
            </div>
        </nav>
    )
}

function Topbar({ status, user, onSignOut }: {
    status: WsStatus; user: AuthUser | null; onSignOut: () => void
}) {
    const { pathname } = useLocation()
    return (
        <header className="topbar">
            <h1 className="topbar-title">{PAGE_TITLES[pathname] ?? 'Sentinel'}</h1>
            <div className="topbar-right">
                <div
                    className={`live-indicator${status === 'live' ? '' : ' disconnected'}`}
                    role="status"
                    aria-live="polite"
                    title="Live alert feed"
                >
                    <div className="pulse-dot" aria-hidden="true" />
                    {status === 'live' ? 'LIVE' : status === 'connecting' ? 'CONNECTING' : 'RECONNECTING'}
                </div>
                {user && (
                    <div className="topbar-user">
                        <div className="topbar-user-meta">
                            <span className="topbar-user-name">{user.username}</span>
                            <span className="topbar-user-role">{user.role.replace('_', ' ')}</span>
                        </div>
                        <button className="btn btn-ghost btn-sm" onClick={onSignOut} title="Sign out">
                            <LogOut size={13} aria-hidden="true" />
                            <span className="sr-only-sm">Sign out</span>
                        </button>
                    </div>
                )}
            </div>
        </header>
    )
}

/**
 * Shown while a route chunk downloads.
 *
 * Deliberately quiet: a spinner that appears for 80ms reads as a flicker, which
 * looks less responsive than a brief still moment. The skeleton holds the
 * layout so the page does not jump when content arrives.
 */
function RouteFallback() {
    return (
        <div className="page-content" aria-busy="true" aria-live="polite">
            <div className="route-skeleton">
                <div className="skeleton-bar" style={{ width: '30%', height: 26 }} />
                <div className="skeleton-grid">
                    {Array.from({ length: 4 }, (_, i) => (
                        <div key={i} className="skeleton-card" />
                    ))}
                </div>
            </div>
            <span className="sr-only">Loading…</span>
        </div>
    )
}

function Shell({ user, onSignOut }: { user: AuthUser | null; onSignOut: () => void }) {
    const { alerts, status, clearAlert } = useAlertWebSocket()

    // Warm the other routes once this one has settled, so navigation is instant.
    useEffect(() => {
        const idle = (window as unknown as {
            requestIdleCallback?: (cb: () => void) => number
        }).requestIdleCallback
        if (idle) {
            const handle = idle(prefetchRoutes)
            return () => (window as unknown as {
                cancelIdleCallback?: (h: number) => void
            }).cancelIdleCallback?.(handle)
        }
        const timer = setTimeout(prefetchRoutes, 2000)
        return () => clearTimeout(timer)
    }, [])
    const toasts = alerts.slice(0, 3)

    return (
        <div className="app-layout">
            <Sidebar newAlertCount={alerts.length} />
            <div className="main-area">
                <Topbar status={status} user={user} onSignOut={onSignOut} />
                <Suspense fallback={<RouteFallback />}>
                    <Routes>
                        <Route path="/" element={<DashboardPage wsAlerts={alerts} />} />
                        <Route path="/map" element={<MapPage />} />
                        <Route path="/wall" element={<VideoWallPage />} />
                        <Route path="/search" element={<SearchPage />} />
                        <Route path="/alerts" element={<AlertsPage wsAlerts={alerts} />} />
                        <Route path="/watchlist" element={<WatchlistPage />} />
                        <Route path="/health" element={<HealthPage />} />
                    </Routes>
                </Suspense>
            </div>

            <div className="toast-container" aria-live="assertive" aria-relevant="additions">
                {toasts.map(a => (
                    <Toast key={a.alert_id} alert={a} onClose={() => clearAlert(a.alert_id)} />
                ))}
            </div>
        </div>
    )
}

export default function App() {
    const [user, setUser] = useState<AuthUser | null>(() => getStoredUser())

    const signOut = useCallback(() => {
        clearSession()
        setUser(null)
    }, [])

    // The API client raises this when a request comes back 401, so an expired
    // token returns us to the login screen instead of looping on failures.
    useEffect(() => {
        const handler = () => setUser(null)
        window.addEventListener('sentinel:signed-out', handler)
        return () => window.removeEventListener('sentinel:signed-out', handler)
    }, [])

    if (!user) {
        return <LoginPage onSignedIn={setUser} />
    }

    return (
        <BrowserRouter>
            <Shell user={user} onSignOut={signOut} />
        </BrowserRouter>
    )
}
