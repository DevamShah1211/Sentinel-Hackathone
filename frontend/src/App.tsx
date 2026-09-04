import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { Map, Monitor, Search, Bell, Shield, BarChart2, RefreshCw } from 'lucide-react'
import MapPage from './pages/MapPage'
import VideoWallPage from './pages/VideoWallPage'
import SearchPage from './pages/SearchPage'
import AlertsPage from './pages/AlertsPage'
import WatchlistPage from './pages/WatchlistPage'
import DashboardPage from './pages/DashboardPage'
import { useAlertWebSocket } from './hooks/useAlertWebSocket'
import Toast from './components/Toast'

function Sidebar({ newAlertCount }: { newAlertCount: number }) {
    const nav = [
        { to: '/', label: 'Dashboard', Icon: BarChart2 },
        { to: '/map', label: 'Camera Map', Icon: Map },
        { to: '/wall', label: 'Video Wall', Icon: Monitor },
        { to: '/search', label: 'Plate Search', Icon: Search },
        { to: '/alerts', label: 'Alerts', Icon: Bell, badge: newAlertCount },
        { to: '/watchlist', label: 'Watchlist', Icon: Shield },
    ]
    return (
        <nav className="sidebar">
            <div className="sidebar-logo">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
                SENTINEL
            </div>
            <div className="sidebar-nav">
                {nav.map(({ to, label, Icon, badge }) => (
                    <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                        <Icon size={16} />
                        {label}
                        {badge ? <span className="badge">{badge > 99 ? '99+' : badge}</span> : null}
                    </NavLink>
                ))}
            </div>
            <div className="sidebar-footer">
                Gujarat CCTV Hackathon 2026<br />
                Model 1 + Model 2
            </div>
        </nav>
    )
}

function Topbar({ connected }: { connected: boolean }) {
    const loc = useLocation()
    const titles: Record<string, string> = {
        '/': 'Dashboard',
        '/map': 'Camera Map & GIS Registry',
        '/wall': 'Live Video Wall',
        '/search': 'Plate Search & Route Reconstruction',
        '/alerts': 'Live Alerts',
        '/watchlist': 'Watchlist Management',
    }
    return (
        <div className="topbar">
            <span className="topbar-title">{titles[loc.pathname] || 'Sentinel'}</span>
            <div className="topbar-right">
                <div className={`live-indicator${connected ? '' : ' disconnected'}`} style={!connected ? { color: 'var(--red)', background: 'var(--red-glow)', borderColor: 'var(--red)' } : {}}>
                    <div className="pulse-dot" style={!connected ? { background: 'var(--red)' } : {}} />
                    {connected ? 'LIVE' : 'RECONNECTING'}
                </div>
            </div>
        </div>
    )
}

function App() {
    const { alerts, connected, clearAlert } = useAlertWebSocket()
    const newCount = alerts.filter(a => a.match_type).length // all WS alerts are "new"
    // Show toast for last 3 unread alerts
    const toasts = alerts.slice(0, 3)

    return (
        <BrowserRouter>
            <div className="app-layout">
                <Sidebar newAlertCount={newCount} />
                <div className="main-area">
                    <Topbar connected={connected} />
                    <Routes>
                        <Route path="/" element={<DashboardPage />} />
                        <Route path="/map" element={<MapPage />} />
                        <Route path="/wall" element={<VideoWallPage />} />
                        <Route path="/search" element={<SearchPage />} />
                        <Route path="/alerts" element={<AlertsPage wsAlerts={alerts} />} />
                        <Route path="/watchlist" element={<WatchlistPage />} />
                    </Routes>
                </div>
            </div>
            {/* Live alert toasts */}
            <div className="toast-container">
                {toasts.map(a => (
                    <Toast key={a.alert_id} alert={a} onClose={() => clearAlert(a.alert_id)} />
                ))}
            </div>
        </BrowserRouter>
    )
}

export default App
