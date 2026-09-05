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

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {
        "status": "ok",
        "service": "sentinel-platform",
        "version": "1.0.0",
        "sandbox_host": settings.sentinel_host,
    }
