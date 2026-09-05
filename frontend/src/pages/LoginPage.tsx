import { useEffect, useState } from 'react'
import { AlertCircle, LogIn, ShieldCheck } from 'lucide-react'
import { getRoleModel, login, setSession, type AuthUser } from '../api/client'

/**
 * Sign-in screen.
 *
 * Demonstration credentials are listed on the page deliberately: this instance is
 * shared with evaluators who need a way in, and the accounts are seeded, clearly
 * labelled, and hold no real data. A production deployment sets AUTH_ENABLED=true
 * with real accounts and removes this panel.
 */
const DEMO_ACCOUNTS = [
    { role: 'State Admin', email: 'admin@sentinel.gujarat.gov.in', password: 'sentinel-demo-2026',
      grants: 'Everything, including the audit trail' },
    { role: 'Dept Operator', email: 'operator@sentinel.gujarat.gov.in', password: 'operator-demo-2026',
      grants: 'Search, watchlist, alerts, reports' },
    { role: 'Viewer', email: 'viewer@sentinel.gujarat.gov.in', password: 'viewer-demo-2026',
      grants: 'Map and live viewing only' },
]

export default function LoginPage({ onSignedIn }: { onSignedIn: (u: AuthUser) => void }) {
    const [email, setEmail] = useState(DEMO_ACCOUNTS[0].email)
    const [password, setPassword] = useState(DEMO_ACCOUNTS[0].password)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [authRequired, setAuthRequired] = useState<boolean | null>(null)

    useEffect(() => {
        getRoleModel()
            .then(r => setAuthRequired(Boolean(r.auth_enabled)))
            .catch(() => setAuthRequired(null))
    }, [])

    const submit = async (e: React.FormEvent) => {
        e.preventDefault()
        setBusy(true)
        setError(null)
        try {
            const data = await login(email.trim(), password)
            setSession(data.access_token, data.user)
            onSignedIn(data.user)
        } catch (err: unknown) {
            const status = (err as { response?: { status?: number } })?.response?.status
            setError(status === 401
                ? 'Incorrect email or password.'
                : 'Could not reach the platform. Is the backend running?')
        } finally {
            setBusy(false)
        }
    }

    const useAccount = (account: typeof DEMO_ACCOUNTS[number]) => {
        setEmail(account.email)
        setPassword(account.password)
        setError(null)
    }

    return (
        <div className="login-shell">
            <div className="login-card">
                <div className="login-brand">
                    <svg width="30" height="30" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    </svg>
                    <div>
                        <div className="login-title">SENTINEL</div>
                        <div className="login-subtitle">Statewide CCTV Integration Platform</div>
                    </div>
                </div>

                <form onSubmit={submit} className="login-form">
                    <label className="field">
                        <span>Email</span>
                        <input
                            className="input"
                            type="email"
                            autoComplete="username"
                            required
                            value={email}
                            onChange={e => setEmail(e.target.value)}
                        />
                    </label>

                    <label className="field">
                        <span>Password</span>
                        <input
                            className="input"
                            type="password"
                            autoComplete="current-password"
                            required
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                        />
                    </label>

                    {error && (
                        <div className="login-error" role="alert">
                            <AlertCircle size={15} aria-hidden="true" />
                            <span>{error}</span>
                        </div>
                    )}

                    <button className="btn btn-primary login-submit" type="submit" disabled={busy}>
                        {busy ? <div className="spinner" aria-hidden="true" /> : <LogIn size={15} aria-hidden="true" />}
                        {busy ? 'Signing in…' : 'Sign in'}
                    </button>
                </form>

                <div className="login-demo">
                    <div className="login-demo-head">
                        <ShieldCheck size={13} aria-hidden="true" />
                        Demonstration accounts
                    </div>
                    {DEMO_ACCOUNTS.map(account => (
                        <button
                            key={account.email}
                            type="button"
                            className="login-demo-row"
                            onClick={() => useAccount(account)}
                        >
                            <span className="login-demo-role">{account.role}</span>
                            <span className="login-demo-grants">{account.grants}</span>
                        </button>
                    ))}
                    {authRequired === false && (
                        <p className="login-note">
                            Role enforcement is currently disabled on this instance
                            (<code>AUTH_ENABLED=false</code>), so the API is open. Signing in
                            still sets your identity for the audit trail.
                        </p>
                    )}
                </div>

                <div className="login-footer">
                    Gujarat CCTV Integration Hackathon 2026 · Model 1 + Model 2
                </div>
            </div>
        </div>
    )
}
