import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { BarChart2, Bell, LogOut, Map, Monitor, Search, Shield } from 'lucide-react'
import MapPage from './pages/MapPage'
import VideoWallPage from './pages/VideoWallPage'
import SearchPage from './pages/SearchPage'
import AlertsPage from './pages/AlertsPage'
import WatchlistPage from './pages/WatchlistPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import { useAlertWebSocket } from './hooks/useAlertWebSocket'
import Toast from './components/Toast'
import { clearSession, getStoredUser, type AuthUser } from './api/client'

const NAV = [
    { to: '/', label: 'Dashboard', Icon: BarChart2 },
    { to: '/map', label: 'Camera Map', Icon: Map },
    { to: '/wall', label: 'Video Wall', Icon: Monitor },
    { to: '/search', label: 'Plate Search', Icon: Search },
    { to: '/alerts', label: 'Alerts', Icon: Bell },
    { to: '/watchlist', label: 'Watchlist', Icon: Shield },
] as const

const PAGE_TITLES: Record<string, string> = {
    '/': 'Dashboard',
    '/map': 'Camera Map & GIS Registry',
    '/wall': 'Live Video Wall',
    '/search': 'Plate Search & Route Reconstruction',
    '/alerts': 'Live Alerts',
    '/watchlist': 'Watchlist Management',
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

function Topbar({ connected, user, onSignOut }: {
    connected: boolean; user: AuthUser | null; onSignOut: () => void
}) {
    const { pathname } = useLocation()
    return (
        <header className="topbar">
            <h1 className="topbar-title">{PAGE_TITLES[pathname] ?? 'Sentinel'}</h1>
            <div className="topbar-right">
                <div
                    className={`live-indicator${connected ? '' : ' disconnected'}`}
                    role="status"
                    aria-live="polite"
                >
                    <div className="pulse-dot" aria-hidden="true" />
                    {connected ? 'LIVE' : 'RECONNECTING'}
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

function Shell({ user, onSignOut }: { user: AuthUser | null; onSignOut: () => void }) {
    const { alerts, connected, clearAlert } = useAlertWebSocket()
    const toasts = alerts.slice(0, 3)

    return (
        <div className="app-layout">
            <Sidebar newAlertCount={alerts.length} />
            <div className="main-area">
                <Topbar connected={connected} user={user} onSignOut={onSignOut} />
                <Routes>
                    <Route path="/" element={<DashboardPage />} />
                    <Route path="/map" element={<MapPage />} />
                    <Route path="/wall" element={<VideoWallPage />} />
                    <Route path="/search" element={<SearchPage />} />
                    <Route path="/alerts" element={<AlertsPage wsAlerts={alerts} />} />
                    <Route path="/watchlist" element={<WatchlistPage />} />
                </Routes>
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
