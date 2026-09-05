"""
Cameras router — Model 1 (Registry & GIS) core.
Provides GeoJSON, paginated list, CRUD, and spatial queries.
"""
import logging
import re
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
    hls_url: Optional[str]
    codec: Optional[str]
    resolution: Optional[str]
    fps: Optional[float]
    status: str
    is_live: bool
    camera_type: Optional[str]
    make: Optional[str]
    model: Optional[str]
    connectivity: Optional[str]
    # Location provenance — how this camera's coordinates were arrived at.
    geo_source: Optional[str] = None
    geo_confidence: Optional[float] = None
    district: Optional[str] = None

    class Config:
        from_attributes = True


def serialise_camera(cam: Camera) -> dict:
    """
    Shape a camera for the API.

    Stream URLs are rewritten to this platform's proxy. The stored RTSP and WHEP
    URLs carry sandbox credentials for the inference worker's use, and those must
    never reach a browser — so they are not serialised at all.
    """
    extra = cam.extra or {}
    return {
        "id": cam.id,
        "native_id": cam.native_id,
        "name": cam.name,
        "department": cam.department,
        "lat": cam.lat,
        "lon": cam.lon,
        "address": cam.address,
        "hls_url": f"/api/v1/cameras/proxy-hls/{cam.native_id}/index.m3u8",
        "codec": cam.codec,
        "resolution": cam.resolution,
        "fps": cam.fps,
        "status": cam.status,
        "is_live": cam.is_live,
        "camera_type": cam.camera_type,
        "make": cam.make,
        "model": cam.model,
        "connectivity": cam.connectivity,
        "geo_source": extra.get("geo_source"),
        "geo_confidence": extra.get("geo_confidence"),
        "district": extra.get("district"),
    }


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
    return [serialise_camera(cam) for cam in result.scalars().all()]


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
    unlocated = 0
    for cam in cameras:
        # A camera whose location could not be resolved is reported as unlocated
        # rather than being given a fabricated position on the map.
        if cam.lat is None or cam.lon is None:
            unlocated += 1
            continue
        properties = serialise_camera(cam)
        properties["id"] = str(properties["id"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [cam.lon, cam.lat]},
            "properties": properties,
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "total": len(features),
        "unlocated": unlocated,
    }


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
    return serialise_camera(cam)


@router.post("", response_model=CameraOut, summary="Create a camera record manually")
async def create_camera(body: CameraCreate, db: AsyncSession = Depends(get_db)):
    cam = Camera(**body.model_dump())
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return serialise_camera(cam)


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
    return serialise_camera(cam)


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
    """
    Serve a sandbox HLS playlist or segment on the platform's own origin.

    The sandbox requires a session cookie, and the browser must never hold one:
    embedding credentials in a stream URL would ship the sandbox password to every
    client that loads the video wall. This endpoint holds the session server-side
    and the browser talks only to us.

    Playlists are rewritten so segment references point back through this proxy;
    otherwise the player would resolve them against the sandbox origin and be
    refused for want of a cookie.
    """
    # The upstream path segment is attacker-controllable in principle, so refuse
    # anything that is not a plain playlist or segment filename.
    if "/" in file_name or "\\" in file_name or ".." in file_name:
        raise HTTPException(400, "Invalid stream file name")

    client = await _get_hls_client()
    # The sandbox publishes playlists at /<camera>/index.m3u8 and the shared
    # AES-128 decryption key at the host root. Older gateway builds used
    # /live/stream/<camera>/, so that path is tried as a fallback.
    candidates = (
        f"https://{settings.sentinel_cdn_host}/{native_id}/{file_name}",
        f"https://{settings.sentinel_cdn_host}/{file_name}",
        f"https://{settings.sentinel_cdn_host}/live/stream/{native_id}/{file_name}",
    )

    try:
        resp = None
        for target_url in candidates:
            resp = await client.get(target_url)
            if resp.status_code == 200:
                break
        if resp is not None and resp.status_code in (401, 403):
            # Session expired — re-authenticate once and retry.
            await client.post(
                f"https://{settings.sentinel_cdn_host}/auth/login",
                data={"email": settings.sentinel_user_email,
                      "password": settings.sentinel_user_password},
            )
            resp = await client.get(target_url)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"HLS proxy error: {exc}") from exc

    if file_name.endswith(".m3u8"):
        base = f"/api/v1/cameras/proxy-hls/{native_id}/"
        lines = []
        for line in resp.text.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append(line)
            elif stripped.startswith("#"):
                # The playlist is AES-128 encrypted and names its key URI. That
                # key also sits behind the sandbox session, so it must come
                # through this proxy too or playback fails at the first segment.
                if "URI=" in stripped:
                    stripped = _rewrite_key_uri(stripped, base)
                lines.append(stripped)
            else:
                # Rewrite segment references to route back through this proxy.
                lines.append(base + stripped.rsplit("/", 1)[-1])
        body = "\n".join(lines).encode()
        return Response(content=body, media_type="application/vnd.apple.mpegurl",
                        status_code=resp.status_code,
                        headers={"Cache-Control": "no-store"})

    media_type = "application/octet-stream" if file_name.endswith(".key") else "video/MP2T"
    return Response(content=resp.content, media_type=media_type,
                    status_code=resp.status_code,
                    headers={"Cache-Control": "no-store"})


def _rewrite_key_uri(tag_line: str, base: str) -> str:
    """Point an EXT-X-KEY URI at this proxy, preserving the rest of the tag."""
    match = re.search(r'URI="([^"]+)"', tag_line)
    if not match:
        return tag_line
    key_name = match.group(1).rsplit("/", 1)[-1]
    return tag_line.replace(match.group(0), f'URI="{base}{key_name}"')



@router.get("/internal/streams", summary="Stream URLs for the ANPR worker (server-side only)")
async def internal_stream_urls(
    db: AsyncSession = Depends(get_db),
    live_only: bool = Query(True),
    limit: int = Query(200, le=1000),
):
    """
    Return the credential-bearing RTSP URLs the inference worker needs.

    This is deliberately separate from `GET /cameras`, which serves browsers and
    must never disclose sandbox credentials. In a real deployment this route sits
    behind service-to-service authentication and is not reachable from the
    operator network; for the prototype it is documented as internal so the
    distinction is explicit rather than accidental.
    """
    q = select(Camera)
    if live_only:
        q = q.where(Camera.is_live == True)
    q = q.limit(limit)
    cameras = (await db.execute(q)).scalars().all()
    return [
        {
            "id": str(cam.id),
            "native_id": cam.native_id,
            "name": cam.name,
            "rtsp_url": cam.rtsp_url,
            "hls_url": cam.hls_url,
            "codec": cam.codec,
        }
        for cam in cameras
    ]
