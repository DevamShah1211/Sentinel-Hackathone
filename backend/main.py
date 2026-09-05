"""
Sentinel CCTV Platform — FastAPI Backend
Gujarat CCTV Integration Hackathon 2026 — Model 1 (Registry & GIS) + Model 2 (Unified Viewing + ANPR)
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.database import init_db
from app.middleware import (
    RateLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware,
)
from app.routers import cameras, detections, watchlist, alerts, auth, analytics, ingest
from app.websocket_manager import ws_manager
from app.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Sentinel CCTV Platform…")
    await init_db()
    await auth.seed_demo_users()
    if not settings.auth_enabled:
        logger.warning(
            "AUTH_ENABLED is false — API routes are open. Set AUTH_ENABLED=true "
            "before exposing this instance."
        )
    # Authenticate the stream proxy now so the first video tile does not wait on
    # a login round-trip.
    asyncio.create_task(cameras.warm_hls_session())
    asyncio.create_task(ingest.sync_catalogue_on_startup())
    yield
    logger.info("🛑 Shutting down Sentinel CCTV Platform…")


app = FastAPI(
    title="Sentinel CCTV Platform",
    description=(
        "**Gujarat CCTV Integration Hackathon 2026 — Category 1**\n\n"
        "Model 1 (Camera Registry & GIS Mapping) + Model 2 (Unified Viewing Platform + ANPR).\n\n"
        "Connects to the Sentinel sandbox, reads cameras from `/api/ingest`, "
        "provides live HLS/WebRTC viewing, ANPR detection indexing with fuzzy plate search, "
        "watchlist matching, real-time alerts, and route reconstruction on a GIS map."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ─── Middleware ───────────────────────────────────────────────────────────────
# Order matters: the outermost layer runs first on the way in, so request
# tracing wraps everything, then rate limiting rejects before any work is done.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)

# CORS is restricted to the configured origins. A wildcard origin combined with
# credentials is rejected by browsers anyway, and would be the wrong posture for
# a console that can query citizen movement history.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
    max_age=600,
)

# ─── API Routers ──────────────────────────────────────────────────────────────
app.include_router(auth.router,       prefix="/api/v1/auth",       tags=["Auth"])
app.include_router(cameras.router,    prefix="/api/v1/cameras",    tags=["Cameras (Model 1)"])
app.include_router(detections.router, prefix="/api/v1/detections", tags=["Detections / ANPR (Model 2)"])
app.include_router(watchlist.router,  prefix="/api/v1/watchlist",  tags=["Watchlist (Model 2)"])
app.include_router(alerts.router,     prefix="/api/v1/alerts",     tags=["Alerts (Model 2)"])
app.include_router(analytics.router,  prefix="/api/v1/analytics",  tags=["Analytics & Reports"])
app.include_router(ingest.router,     prefix="/api/v1/ingest",     tags=["Ingest / Catalogue Sync"])

# ─── Evidence crops static files ─────────────────────────────────────────────
os.makedirs(settings.evidence_crop_dir, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=settings.evidence_crop_dir), name="evidence")


# ─── WebSocket — live alerts ──────────────────────────────────────────────────
@app.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep-alive: client can send {"action":"ping"}
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/api/health", tags=["Health"])
async def health():
    """
    Component health.

    Reports what is actually reachable rather than returning a constant 'ok' —
    a health endpoint that cannot fail tells an operator nothing. Degraded means
    the API is serving but something it depends on is not.
    """
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models import Camera, Detection

    components: dict[str, dict] = {}
    healthy = True

    try:
        async with AsyncSessionLocal() as db:
            camera_count = await db.scalar(select(func.count(Camera.id)))
            located = await db.scalar(
                select(func.count(Camera.id)).where(Camera.lat.isnot(None))
            )
            detection_count = await db.scalar(select(func.count(Detection.id)))
            latest = await db.scalar(select(func.max(Detection.detected_at)))
        components["database"] = {"status": "ok", "cameras": camera_count,
                                  "located_cameras": located,
                                  "detections": detection_count}
        components["index"] = {
            "status": "ok",
            "detections": detection_count,
            "latest_detection": latest.isoformat() if latest else None,
        }
    except Exception as exc:
        healthy = False
        components["database"] = {"status": "unavailable", "error": type(exc).__name__}

    components["auth"] = {"status": "ok", "enforced": settings.auth_enabled}
    components["sandbox"] = {"status": "configured" if settings.sentinel_user_email
                             else "no-credentials", "host": settings.sentinel_host}

    return {
        "status": "ok" if healthy else "degraded",
        "service": "sentinel-platform",
        "version": "1.0.0",
        "components": components,
    }
