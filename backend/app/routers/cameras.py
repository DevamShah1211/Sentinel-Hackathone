"""
Cameras router — Model 1 (Registry & GIS) core.
Provides GeoJSON, paginated list, CRUD, and spatial queries.
"""
import asyncio
import logging
import re
import time
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.live_relay import relay_manager
from app.models import Camera
from app.settings import settings

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
    live_url: Optional[str] = None
    snapshot_url: Optional[str] = None
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
        # Primary viewing path: the local relay, which reads RTSP (reliable) and
        # serves MJPEG. The sandbox's own HLS is kept as a secondary because it
        # is higher quality when its web tier is responsive.
        "live_url": f"/api/v1/cameras/live/{cam.native_id}",
        "snapshot_url": f"/api/v1/cameras/live/{cam.native_id}/snapshot",
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


async def _camera_stream_url(native_id: str, db: AsyncSession) -> tuple[str, str]:
    """Resolve a camera's upstream RTSP URL, or raise 404."""
    cam = (await db.execute(
        select(Camera).where(Camera.native_id == native_id)
    )).scalar_one_or_none()
    if cam is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND,
                            f"Unknown camera '{native_id}'")
    if not cam.rtsp_url:
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            f"Camera '{native_id}' has no RTSP endpoint")
    return cam.rtsp_url, cam.name


@router.get("/live/{native_id}", summary="Live MJPEG stream for a camera")
async def live_stream(
    native_id: str,
    db: AsyncSession = Depends(get_db),
    profile: str = Query("balanced", pattern="^(high|balanced|low)$",
                         description="high = maximised tile, balanced = 2x2, low = 3x3"),
):
    """
    Stream a camera as MJPEG.

    Every browser plays this in a plain `<img src=...>` with no player library.
    One upstream RTSP connection is shared by all viewers of a camera, so a
    nine-tile wall costs the gateway nine connections rather than nine per client.
    """
    url, _name = await _camera_stream_url(native_id, db)
    return StreamingResponse(
        relay_manager.stream(native_id, url, profile),
        media_type="multipart/x-mixed-replace; boundary=sentinelframe",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            # Nothing downstream should buffer a live stream.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/live/{native_id}/snapshot", summary="Single current frame from a camera")
async def live_snapshot(native_id: str, db: AsyncSession = Depends(get_db)):
    """One JPEG — for map popups and previews, where a full stream is wasteful."""
    url, _name = await _camera_stream_url(native_id, db)
    frame = await asyncio.to_thread(relay_manager.snapshot, native_id, url)
    if frame is None:
        raise HTTPException(
            http_status.HTTP_504_GATEWAY_TIMEOUT,
            "No frame available from this camera yet.",
        )
    return Response(content=frame, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


# Declared before /{camera_id}: a literal path must be registered ahead of the
# UUID catch-all or FastAPI matches the catch-all first.
@router.get("/live-status", summary="Relay status per camera")
async def live_status():
    """What the relay is currently doing — useful when a tile will not play."""
    return {"relays": relay_manager.status()}


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

_hls_client: Optional[httpx.AsyncClient] = None

# key -> (fetched_at, body, media_type). Playlists change every few seconds, so a
# short time-to-live is enough to collapse nine tiles' identical requests.
_playlist_cache: dict[str, tuple[float, bytes, str]] = {}
# The sandbox throttles repeated HTTP requests, and nine tiles each re-fetch their
# playlist every few seconds. A 4 s cache keeps the wall inside that budget while
# staying well under the 6 s segment duration, so playback is never starved.
_PLAYLIST_TTL_SECONDS = 4.0


# One shared session, established once. Creating it lazily inside the first
# request made the first tile of the video wall wait ~20 s for a login round-trip,
# which reads as a broken player; `warm_hls_session()` is called at startup.
_hls_lock: asyncio.Lock | None = None


async def _get_hls_client() -> httpx.AsyncClient:
    global _hls_client, _hls_lock
    if _hls_lock is None:
        _hls_lock = asyncio.Lock()

    # Nine tiles start together; without the lock they would each open a client
    # and log in separately.
    async with _hls_lock:
        if _hls_client is None or _hls_client.is_closed:
            _hls_client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=8.0),
                follow_redirects=True,
                # The sandbox presents a certificate that does not validate for
                # this host. Verification is disabled only for this upstream hop,
                # never for anything the platform itself serves.
                verify=False,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
                # The sandbox CDN rejects non-browser user agents with 403, so
                # this must stay a browser string — a plain client name breaks
                # every stream.
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Referer": f"https://{settings.sentinel_cdn_host}/",
                },
            )
            if settings.sentinel_user_email and settings.sentinel_user_password:
                try:
                    await _hls_client.post(
                        f"https://{settings.sentinel_cdn_host}/auth/login",
                        data={"email": settings.sentinel_user_email,
                              "password": settings.sentinel_user_password},
                    )
                    logger.info("HLS proxy session established")
                except httpx.HTTPError as exc:
                    logger.warning("HLS proxy login failed: %s", exc)
    return _hls_client


async def _reset_hls_client() -> None:
    """Drop the current session so the next call authenticates afresh."""
    global _hls_client
    if _hls_client is not None and not _hls_client.is_closed:
        await _hls_client.aclose()
    _hls_client = None


async def warm_hls_session() -> None:
    """Authenticate the stream proxy at startup so the first tile plays promptly."""
    try:
        await _get_hls_client()
    except Exception as exc:
        logger.warning("Could not warm the HLS session: %s", exc)


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

    # Playlists and the shared key are requested repeatedly by every open tile.
    # A short cache collapses nine identical fetches into one without making the
    # stream noticeably staler — segments themselves are never cached, since they
    # are large and each is fetched once.
    cache_key = f"{native_id}/{file_name}"
    cacheable = file_name.endswith((".m3u8", ".key"))
    if cacheable:
        cached = _playlist_cache.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < _PLAYLIST_TTL_SECONDS:
            return Response(content=cached[1], media_type=cached[2],
                            headers={"Cache-Control": "no-store",
                                     "X-Sentinel-Cache": "hit"})

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
        target_url = candidates[0]
        for index, target_url in enumerate(candidates):
            resp = await client.get(target_url)
            if resp.status_code == 200:
                break
            # A 403 is the gateway refusing the session, not a wrong path — trying
            # the remaining paths would only add seconds to a request that is
            # already going to fail, and a slow failure looks worse in a video
            # wall than a fast one.
            if resp.status_code == 403 and index == 0:
                break

        # 401/403 means the session lapsed. Re-authenticate once and retry the
        # path that was being tried; the sandbox also throttles, in which case
        # this retry legitimately fails and the caller is told plainly.
        if resp is not None and resp.status_code in (401, 403):
            logger.info("HLS session rejected (%s) — re-authenticating", resp.status_code)
            await _reset_hls_client()
            client = await _get_hls_client()
            resp = await client.get(target_url)
    except httpx.HTTPError as exc:
        logger.warning("HLS upstream error for %s: %s", cache_key, exc)
        raise HTTPException(
            http_status.HTTP_502_BAD_GATEWAY,
            "Upstream stream gateway is unreachable. Live viewing is temporarily "
            "unavailable; the camera registry and detection index are unaffected.",
        ) from exc

    if resp is None or resp.status_code >= 400:
        code = resp.status_code if resp is not None else "no response"
        logger.warning("HLS upstream refused %s (%s)", cache_key, code)
        raise HTTPException(
            http_status.HTTP_502_BAD_GATEWAY,
            f"Upstream stream gateway returned {code} for this camera.",
        )

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


