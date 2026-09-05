"""
Cameras router — Model 1 (Registry & GIS) core.
Provides GeoJSON, paginated list, CRUD, and spatial queries.
"""
import asyncio
import csv
import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.database import get_db
from app.live_relay import relay_manager
from app.models import Camera
from app.security import Principal, RequireStateAdmin
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


# The path is constrained to a UUID shape so literal routes declared after this
# one — /health-status, /bulk-import, /live-status — are never swallowed by the
# catch-all. Ordering alone is too easy to break when endpoints are appended.
@router.get("/{camera_id:uuid}", response_model=CameraOut, summary="Get camera by UUID")
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


@router.patch("/{camera_id:uuid}", response_model=CameraOut, summary="Update a camera record")
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


# ─── Model 1: bulk onboarding, health, gap analysis ──────────────────────────

@router.post("/bulk-import", summary="Bulk camera onboarding from CSV")
async def bulk_import_cameras(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(False, description="Validate without writing"),
    principal: Principal = RequireStateAdmin,
):
    """
    Onboard many cameras at once from a CSV.

    The problem statement asks for "bulk import, manual entry, and API-based
    camera onboarding"; this is the first, POST /cameras is the second, and the
    catalogue sync is the third.

    Recognised columns (only native_id and name are required):

        native_id,name,department,lat,lon,address,rtsp_url,codec,resolution,
        camera_type,make,model,connectivity,installation_date,ownership

    Rows are validated individually and a bad row never aborts the import — the
    response reports which rows failed and why, so a department can fix twelve
    lines rather than resubmit a thousand. dry_run=true validates and writes
    nothing, which is how you would check a file before committing it.
    """
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    created = updated = 0
    errors: list[dict] = []
    seen: set[str] = set()

    for line_number, row in enumerate(reader, start=2):   # row 1 is the header
        cleaned = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items() if k}
        native_id = cleaned.get("native_id") or cleaned.get("id")
        name = cleaned.get("name")

        if not native_id:
            errors.append({"line": line_number, "error": "native_id is required"})
            continue
        if not name:
            errors.append({"line": line_number, "error": "name is required"})
            continue
        if native_id in seen:
            errors.append({"line": line_number,
                           "error": f"duplicate native_id {native_id!r} in this file"})
            continue
        seen.add(native_id)

        def number(field_name: str) -> float | None:
            value = cleaned.get(field_name)
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                errors.append({"line": line_number,
                               "error": f"{field_name} {value!r} is not a number"})
                return None

        lat, lon = number("lat"), number("lon")
        if lat is not None and not (-90 <= lat <= 90):
            errors.append({"line": line_number, "error": f"lat {lat} out of range"})
            continue
        if lon is not None and not (-180 <= lon <= 180):
            errors.append({"line": line_number, "error": f"lon {lon} out of range"})
            continue

        installed = None
        if cleaned.get("installation_date"):
            try:
                installed = datetime.fromisoformat(cleaned["installation_date"])
                if installed.tzinfo is None:
                    installed = installed.replace(tzinfo=timezone.utc)
            except ValueError:
                errors.append({"line": line_number,
                               "error": "installation_date must be ISO-8601, "
                                        "e.g. 2021-03-14"})

        fields = {
            "name": name,
            "department": cleaned.get("department") or "Unknown",
            "lat": lat,
            "lon": lon,
            "address": cleaned.get("address") or None,
            "rtsp_url": cleaned.get("rtsp_url") or None,
            "hls_url": cleaned.get("hls_url") or None,
            "codec": cleaned.get("codec") or None,
            "resolution": cleaned.get("resolution") or None,
            "camera_type": cleaned.get("camera_type") or None,
            "make": cleaned.get("make") or None,
            "model": cleaned.get("model") or None,
            "connectivity": cleaned.get("connectivity") or None,
            "ownership": cleaned.get("ownership") or None,
            "installation_date": installed,
        }

        if dry_run:
            created += 1
            continue

        existing = (await db.execute(
            select(Camera).where(Camera.native_id == native_id)
        )).scalar_one_or_none()

        if existing:
            for key, value in fields.items():
                if value is not None:
                    setattr(existing, key, value)
            extra = dict(existing.extra or {})
            extra["onboarded_via"] = "csv-bulk-import"
            existing.extra = extra
            updated += 1
        else:
            db.add(Camera(
                native_id=native_id,
                status="registered",
                is_live=bool(fields["rtsp_url"]),
                extra={"onboarded_via": "csv-bulk-import",
                       "geo_source": "csv" if lat is not None else "unresolved",
                       "geo_confidence": 1.0 if lat is not None else 0.0},
                **fields,
            ))
            created += 1

    if not dry_run:
        await db.commit()
        await audit.record(
            db, actor=principal.email, action="bulk_import_cameras",
            object_type="camera", object_id=f"{created + updated} cameras",
            purpose="registry-onboarding",
            details={"created": created, "updated": updated, "errors": len(errors)},
        )

    return {
        "dry_run": dry_run,
        "created": created,
        "updated": updated,
        "rejected": len(errors),
        "errors": errors[:50],
        "message": (f"Validated {created} rows; {len(errors)} would be rejected"
                    if dry_run else
                    f"Onboarded {created} new and updated {updated} cameras"),
    }


@router.get("/bulk-import/template", summary="CSV template for bulk onboarding")
async def bulk_import_template():
    """A ready-to-fill CSV with the recognised columns and one worked example."""
    header = ("native_id,name,department,lat,lon,address,rtsp_url,codec,"
              "resolution,camera_type,make,model,connectivity,installation_date,"
              "ownership\n")
    example = ("GJ-AHM-0001,Nehru Bridge East,Traffic Police,23.0225,72.5714,"
               "Nehru Bridge Ahmedabad,rtsp://10.0.0.5:554/stream1,h264,"
               "1920x1080,fixed_dome,Hikvision,DS-2CD2143G0,fibre,2021-03-14,"
               "Ahmedabad Municipal Corporation\n")
    return Response(
        content=header + example,
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="sentinel_camera_onboarding_template.csv"'},
    )


@router.get("/health-status", summary="Camera health and maintenance status")
async def camera_health(db: AsyncSession = Depends(get_db)):
    """
    Per-camera health, as the registry can actually determine it.

    A camera is offline if it has never been contacted, stale if it has not been
    seen for a day, and operational otherwise. Anything the registry does not
    know is reported as unknown rather than assumed good.
    """
    cameras = (await db.execute(select(Camera))).scalars().all()
    now = datetime.now(timezone.utc)

    rows = []
    counts = {"operational": 0, "stale": 0, "offline": 0}
    for cam in cameras:
        if cam.last_seen_at is None:
            state, age_hours = "offline", None
        else:
            age_hours = (now - cam.last_seen_at).total_seconds() / 3600
            state = "operational" if age_hours < 24 else "stale"
        counts[state] += 1

        age_years = None
        if cam.installation_date:
            age_years = round((now - cam.installation_date).days / 365.25, 1)

        rows.append({
            "native_id": cam.native_id,
            "name": cam.name,
            "department": cam.department,
            "district": (cam.extra or {}).get("district"),
            "state": state,
            "last_seen_at": cam.last_seen_at,
            "hours_since_contact": round(age_hours, 1) if age_hours is not None else None,
            "codec": cam.codec,
            "resolution": cam.resolution,
            "age_years": age_years,
            "located": cam.lat is not None and cam.lon is not None,
        })

    rows.sort(key=lambda r: ({"offline": 0, "stale": 1, "operational": 2}[r["state"]],
                             r["native_id"]))
    return {
        "generated_at": now,
        "totals": {**counts, "cameras": len(cameras)},
        "cameras": rows,
    }
