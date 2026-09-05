import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCw, VideoOff } from 'lucide-react'

export type TileState = 'connecting' | 'playing' | 'error'

/**
 * A live camera view.
 *
 * Uses the platform's MJPEG relay rather than the sandbox's HLS. The sandbox's
 * HTTP tier is frequently too slow to start a player — measured at 9-30 s for a
 * playlist, often timing out — while its RTSP holds up, and the relay bridges
 * the two. An MJPEG stream is just an `<img>`, so there is no player library, no
 * manifest and no segment fetching to stall on.
 *
 * The connection is torn down on unmount and when the tab is hidden: an `<img>`
 * pointed at a multipart stream keeps downloading forever otherwise, and nine of
 * them would hold nine connections open behind a hidden tab.
 */
export default function LiveTile({
    cameraId, alt, className, style, onStateChange, showRetry = true,
}: {
    cameraId: string
    alt: string
    className?: string
    style?: React.CSSProperties
    onStateChange?: (s: TileState) => void
    showRetry?: boolean
}) {
    const imgRef = useRef<HTMLImageElement | null>(null)
    const [state, setState] = useState<TileState>('connecting')
    const [attempt, setAttempt] = useState(0)

    const update = useCallback((s: TileState) => {
        setState(s)
        onStateChange?.(s)
    }, [onStateChange])

    useEffect(() => {
        const img = imgRef.current
        if (!img) return

        update('connecting')
        // The cache-buster forces a new request on retry; browsers will otherwise
        // reuse the dead connection.
        const src = `/api/v1/cameras/live/${encodeURIComponent(cameraId)}?t=${Date.now()}`

        const onLoad = () => update('playing')
        const onError = () => update('error')
        img.addEventListener('load', onLoad)
        img.addEventListener('error', onError)
        img.src = src

        const onVisibility = () => {
            if (document.hidden) {
                img.removeAttribute('src')
            } else {
                img.src = `/api/v1/cameras/live/${encodeURIComponent(cameraId)}?t=${Date.now()}`
            }
        }
        document.addEventListener('visibilitychange', onVisibility)

        return () => {
            document.removeEventListener('visibilitychange', onVisibility)
            img.removeEventListener('load', onLoad)
            img.removeEventListener('error', onError)
            // Dropping the src is what actually closes the HTTP connection.
            img.removeAttribute('src')
        }
    }, [cameraId, attempt, update])

    return (
        <>
            <img
                ref={imgRef}
                alt={alt}
                className={className}
                style={{
                    width: '100%', height: '100%', objectFit: 'cover',
                    background: '#000', display: 'block', ...style,
                }}
            />
            {state !== 'playing' && (
                <div style={{
                    position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center', gap: 7,
                    background: 'rgba(0,0,0,0.6)', color: 'var(--text-secondary)',
                    fontSize: 12, textAlign: 'center', padding: 12,
                }}>
                    {state === 'error' ? (
                        <>
                            <VideoOff size={20} aria-hidden="true" />
                            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                                Stream unavailable
                            </span>
                            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', maxWidth: 210 }}>
                                The camera gateway is not responding. The registry and
                                detection index are unaffected.
                            </span>
                            {showRetry && (
                                <button
                                    className="btn btn-ghost btn-sm"
                                    style={{ marginTop: 2 }}
                                    onClick={() => setAttempt(a => a + 1)}
                                >
                                    <RotateCw size={11} aria-hidden="true" /> Retry
                                </button>
                            )}
                        </>
                    ) : (
                        <>
                            <div className="spinner" aria-hidden="true" />
                            <span>Connecting…</span>
                            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', maxWidth: 220 }}>
                                The gateway accepts one connection at a time, so
                                tiles come up in sequence.
                            </span>
                        </>
                    )}
                </div>
            )}
        </>
    )
}
