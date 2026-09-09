import { useEffect, useState } from 'react'
import { AlertCircle, Camera, LogIn, MapPin, ScanLine, ShieldCheck } from 'lucide-react'
import { getRoleModel, login, setSession, type AuthUser } from '../api/client'

/**
 * Sign-in screen.
 *
 * Demonstration *emails* are listed so an evaluator can see the role model and
 * fill the form in one click. Their passwords are deliberately NOT here.
 *
 * They used to be. Three credentials were embedded in this file, which meant
 * they were also in the compiled bundle served to every visitor — so enabling
 * authentication, the step meant to secure the platform, would have shipped
 * three working accounts to anyone who opened the page, one of them state
 * admin. Passwords are generated at seeding time and printed once to the server
 * log; whoever runs the instance passes them to whoever needs them.
 */
const DEMO_ROLES = [
    {
        role: 'State Admin',
        email: 'admin@sentinel.gujarat.gov.in',
        grants: 'Full access, including the audit trail and camera registry',
    },
    {
        role: 'Dept Operator',
        email: 'operator@sentinel.gujarat.gov.in',
        grants: 'Plate search, watchlist, alerts and report export',
    },
    {
        role: 'Viewer',
        email: 'viewer@sentinel.gujarat.gov.in',
        grants: 'Map and live camera viewing only',
    },
]

/** What the platform does, shown beside the form so the panel is not dead space. */
const CAPABILITIES = [
    { icon: MapPin, title: 'Central registry & GIS', body: 'Every camera onboarded, located and searchable on one map.' },
    { icon: Camera, title: 'Unified viewing', body: 'Thirty feeds from one operator console, whatever the vendor.' },
    { icon: ScanLine, title: 'ANPR & watchlist', body: 'Continuous plate reading, matched against wanted vehicles.' },
]

export default function LoginPage({ onSignedIn }: { onSignedIn: (u: AuthUser) => void }) {
    const [email, setEmail] = useState(DEMO_ROLES[0].email)
    const [password, setPassword] = useState('')
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
            setError(
                status === 401 ? 'Incorrect email or password.'
                : status === 429 ? 'Too many attempts. Wait a minute and try again.'
                : 'Could not reach the platform. Is the backend running?')
        } finally {
            setBusy(false)
        }
    }

    return (
        <div className="login-shell">
            {/* Left: what this is. Fills what was empty space, and tells an
                evaluator what they are looking at before they are inside. */}
            <aside className="login-aside">
                <div className="login-brand">
                    <svg width="34" height="34" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    </svg>
                    <div>
                        <div className="login-title">SENTINEL</div>
                        <div className="login-subtitle">Statewide CCTV Integration Platform</div>
                    </div>
                </div>

                <p className="login-lede">
                    One registry, one viewer and one plate index across every
                    department&rsquo;s cameras — without replacing the systems they
                    already run.
                </p>

                <ul className="login-capabilities">
                    {CAPABILITIES.map(({ icon: Icon, title, body }) => (
                        <li key={title}>
                            <Icon size={17} aria-hidden="true" />
                            <div>
                                <strong>{title}</strong>
                                <span>{body}</span>
                            </div>
                        </li>
                    ))}
                </ul>

                <div className="login-aside-foot">
                    Gujarat CCTV Integration Hackathon 2026 · Category 1 · Model 1 + Model 2
                </div>
            </aside>

            {/* Right: the form itself. */}
            <main className="login-main">
                <div className="login-card">
                    <h1 className="login-heading">Sign in</h1>
                    <p className="login-sub">Use the account issued for this instance.</p>

                    <form onSubmit={submit} className="login-form">
                        <label className="field">
                            <span>Email</span>
                            <input
                                className="input"
                                type="email"
                                autoComplete="username"
                                required
                                autoFocus
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
                                placeholder="Issued at deployment"
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
                            Role model — select to fill the email
                        </div>
                        {DEMO_ROLES.map(account => (
                            <button
                                key={account.email}
                                type="button"
                                className={`login-demo-row${email === account.email ? ' is-active' : ''}`}
                                onClick={() => { setEmail(account.email); setError(null) }}
                                aria-pressed={email === account.email}
                            >
                                <span className="login-demo-role">{account.role}</span>
                                <span className="login-demo-grants">{account.grants}</span>
                            </button>
                        ))}

                        {authRequired === false && (
                            <p className="login-note">
                                Role enforcement is disabled on this instance
                                (<code>AUTH_ENABLED=false</code>), so the API is open.
                                Signing in still sets your identity for the audit trail.
                            </p>
                        )}
                    </div>
                </div>
            </main>
        </div>
    )
}
