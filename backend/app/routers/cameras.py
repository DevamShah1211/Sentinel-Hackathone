"""
Cameras router — Model 1 (Registry & GIS) core.
Provides GeoJSON, paginated list, CRUD, and spatial queries.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Camera

logger = logging.getLogger("sentinel.cameras")
router = APIRouter()


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class CameraOut(BaseModel):
    id: UUID
    native_id: str
    name: str
    department: str
    lat: Optional[float]
    lon: Optional[float]
    address: Optional[str]
    rtsp_url: Optional[str]
    hls_url: Optional[str]
    whep_url: Optional[str]
    codec: Optional[str]
    resolution: Optional[str]
    fps: Optional[float]
    status: str
    is_live: bool
    camera_type: Optional[str]
    make: Optional[str]
    model: Optional[str]
    connectivity: Optional[str]

    class Config:
        from_attributes = True


class CameraCreate(BaseModel):
    native_id: str
    name: str
    department: str = "Unknown"
    lat: Optional[float] = None
    lon: Optional[float] = None
    address: Optional[str] = None
    rtsp_url: Optional[str] = None
    hls_url: Optional[str] = None
    whep_url: Optional[str] = None
    codec: Optional[str] = "h264"
    resolution: Optional[str] = None
    camera_type: Optional[str] = "fixed_dome"
    make: Optional[str] = None
    model: Optional[str] = None
    connectivity: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CameraOut], summary="List all cameras (paginated)")
async def list_cameras(
    db: AsyncSession = Depends(get_db),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    codec: Optional[str] = Query(None),
    live_only: bool = Query(False),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
):
    q = select(Camera)
    if department:
        q = q.where(Camera.department.ilike(f"%{department}%"))
    if status:
        q = q.where(Camera.status == status)
    if codec:
        q = q.where(Camera.codec == codec)
    if live_only:
        q = q.where(Camera.is_live == True)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/geojson", summary="All cameras as GeoJSON FeatureCollection (for map)")
async def cameras_geojson(
    db: AsyncSession = Depends(get_db),
    department: Optional[str] = Query(None),
    live_only: bool = Query(False),
):
    """Returns GeoJSON FeatureCollection for Leaflet / MapLibre."""
    q = select(Camera).where(Camera.lat.isnot(None)).where(Camera.lon.isnot(None))
    if department:
        q = q.where(Camera.department.ilike(f"%{department}%"))
    if live_only:
        q = q.where(Camera.is_live == True)
    result = await db.execute(q)
    cameras = result.scalars().all()

    features = []
    for cam in cameras:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [cam.lon, cam.lat]},
            "properties": {
                "id":         str(cam.id),
                "native_id":  cam.native_id,
                "name":       cam.name,
                "department": cam.department,
                "status":     cam.status,
                "is_live":    cam.is_live,
                "codec":      cam.codec,
                "hls_url":    cam.hls_url,
                "whep_url":   cam.whep_url,
                "rtsp_url":   cam.rtsp_url,
                "camera_type": cam.camera_type,
                "address":    cam.address,
            },
        })
    return {"type": "FeatureCollection", "features": features, "total": len(features)}


@router.get("/stats", summary="Department-wise camera statistics")
async def camera_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Camera.department, func.count(Camera.id).label("total"),
               func.sum(func.cast(Camera.is_live, "int")).label("live"))
        .group_by(Camera.department)
        .order_by(func.count(Camera.id).desc())
    )
    rows = result.all()
    return [{"department": r[0], "total": r[1], "live": r[2] or 0} for r in rows]


@router.get("/{camera_id}", response_model=CameraOut, summary="Get camera by UUID")
async def get_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@router.post("", response_model=CameraOut, summary="Create a camera record manually")
async def create_camera(body: CameraCreate, db: AsyncSession = Depends(get_db)):
    cam = Camera(**body.model_dump())
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return cam


@router.patch("/{camera_id}", response_model=CameraOut, summary="Update a camera record")
async def update_camera(camera_id: UUID, body: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    for k, v in body.items():
        if hasattr(cam, k):
            setattr(cam, k, v)
    await db.commit()
    await db.refresh(cam)
    return cam


# ─── Authenticated HLS Stream Proxy ──────────────────────────────────────────
import httpx
from fastapi import Response
from app.settings import settings

_hls_client: Optional[httpx.AsyncClient] = None


async def _get_hls_client() -> httpx.AsyncClient:
    global _hls_client
    if _hls_client is None or _hls_client.is_closed:
        _hls_client = httpx.AsyncClient(
            timeout=10,
            follow_redirects=True,
            verify=False,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        if settings.sentinel_user_email and settings.sentinel_user_password:
            try:
                await _hls_client.post(
                    f"https://{settings.sentinel_cdn_host}/auth/login",
                    data={"email": settings.sentinel_user_email, "password": settings.sentinel_user_password}
                )
            except Exception as e:
                logger.warning(f"HLS proxy login warning: {e}")
    return _hls_client


@router.get("/proxy-hls/{native_id}/{file_name}", summary="Proxy authenticated HLS stream segments")
async def proxy_hls_stream(native_id: str, file_name: str):
    client = await _get_hls_client()
    target_url = f"https://{settings.sentinel_cdn_host}/live/stream/{native_id}/{file_name}"
    try:
        resp = await client.get(target_url)
        if resp.status_code in (401, 403):
            # Session expired — re-login and retry
            await client.post(
                f"https://{settings.sentinel_cdn_host}/auth/login",
                data={"email": settings.sentinel_user_email, "password": settings.sentinel_user_password}
            )
            resp = await client.get(target_url)

        content_type = "application/x-mpegURL" if file_name.endswith(".m3u8") else "video/MP2T"
        return Response(content=resp.content, media_type=content_type, status_code=resp.status_code)
    except Exception as exc:
        raise HTTPException(502, f"HLS Proxy error: {exc}")

