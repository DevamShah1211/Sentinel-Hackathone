"""
Ingest router — onboards cameras from the Sentinel sandbox catalogue.

The catalogue is the contract (playbook, sandbox rule 1): camera ids and the camera
set can change, so nothing here is hardcoded. What the sandbox actually returns is
only `{id, name}` per camera — no coordinates, no department, no codec — so every
location is derived by `app.geocoding`, which records how it was derived and never
invents a position it cannot justify.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.geocoding import (
    GeocodeCache,
    NOMINATIM_UA,
    infer_department,
    resolve_location,
)
from app.models import Camera
from app.sandbox_client import fetch_catalogue
from app.settings import settings

logger = logging.getLogger("sentinel.ingest")
router = APIRouter()


def _stream_urls(native_id: str) -> dict[str, str]:
    """
    Build the three stream URLs for a camera.

    The sandbox is credentialled: RTSP and WHEP carry basic-auth in the URL (the
    email's '@' must be percent-encoded), while HLS is served from the CDN host.
    """
    email = settings.sentinel_user_email
    password = settings.sentinel_user_password
    auth = f"{quote(email, safe='')}:{quote(password, safe='')}@" if email and password else ""

    return {
        "rtsp_url": f"rtsp://{auth}{settings.sentinel_ip}:{settings.sentinel_rtsp_port}/stream/{native_id}",
        "hls_url": f"https://{settings.sentinel_cdn_host}/{native_id}/index.m3u8",
        "whep_url": f"http://{auth}{settings.sentinel_ip}:{settings.sentinel_whep_port}/stream/{native_id}/whep",
    }


def build_camera_row(item: dict, cache: GeocodeCache | None = None,
                     client: httpx.Client | None = None,
                     use_network: bool = True) -> dict | None:
    """Transform one catalogue entry into a `cameras` row."""
    native_id = str(item.get("id") or "").strip()
    if not native_id:
        return None

    name = item.get("name") or f"Camera {native_id}"
    geo = resolve_location(native_id, name, cache=cache, client=client, use_network=use_network)

    # The catalogue may one day carry these directly; prefer them when present.
    lat = item.get("lat") or item.get("latitude") or geo.lat
    lon = item.get("lon") or item.get("longitude") or item.get("lng") or geo.lon

    row = {
        "native_id": native_id,
        "name": name,
        "department": item.get("department") or item.get("dept") or infer_department(name),
        "lat": lat,
        "lon": lon,
        "address": item.get("address") or geo.address,
        "codec": item.get("codec"),
        "resolution": item.get("resolution"),
        "fps": item.get("fps"),
        "bitrate_kbps": item.get("bitrate_kbps") or item.get("bitrate"),
        "status": "operational" if item.get("live", True) else "unknown",
        "is_live": bool(item.get("live", True)),
        "camera_type": item.get("type") or "fixed",
        # Provenance travels with the record so the UI and the HLD can state how
        # each location was arrived at rather than implying survey accuracy.
        "extra": {
            "geo_source": geo.source,
            "geo_confidence": geo.confidence,
            "district": geo.district,
            "department_inferred": not (item.get("department") or item.get("dept")),
            "catalogue_fields": sorted(item.keys()),
        },
    }
    row.update(_stream_urls(native_id))
    return row


async def upsert_cameras(cameras_data: list[dict], db: AsyncSession,
                         use_network: bool = True) -> dict:
    """Insert or update camera records, keyed on native_id."""
    cache = GeocodeCache()
    inserted = updated = skipped = unlocated = 0

    with httpx.Client(timeout=20.0, headers={"User-Agent": NOMINATIM_UA}) as client:
        for item in cameras_data:
            row = build_camera_row(item, cache=cache, client=client, use_network=use_network)
            if row is None:
                skipped += 1
                continue
            if row["lat"] is None or row["lon"] is None:
                unlocated += 1

            existing = (
                await db.execute(select(Camera).where(Camera.native_id == row["native_id"]))
            ).scalar_one_or_none()

            if existing:
                for key, value in row.items():
                    # Never overwrite a known value with a null.
                    if value is not None:
                        setattr(existing, key, value)
                existing.last_seen_at = datetime.now(timezone.utc)
                updated += 1
            else:
                db.add(Camera(**row, last_seen_at=datetime.now(timezone.utc)))
                inserted += 1

    await db.commit()
    result = {"inserted": inserted, "updated": updated,
              "skipped": skipped, "unlocated": unlocated,
              "total": inserted + updated}
    logger.info("Camera sync: %s", result)
    return result


async def sync_catalogue_on_startup() -> None:
    """Populate the camera registry once at application startup."""
    await asyncio.sleep(2)  # let the database initialise
    logger.info("Fetching Sentinel sandbox catalogue…")
    try:
        cameras_data = await fetch_catalogue()
    except Exception as exc:  # never let ingest failure stop the API booting
        logger.warning("Catalogue fetch raised %s: %s", type(exc).__name__, exc)
        return

    if not cameras_data:
        logger.warning("No cameras returned from catalogue; keeping existing registry")
        return

    async with AsyncSessionLocal() as db:
        # Geocoding is rate-limited to 1 req/s; on startup rely on the cache only
        # so boot is not delayed. Use POST /api/v1/ingest/sync to refresh locations.
        await upsert_cameras(cameras_data, db, use_network=False)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/sync", summary="Re-sync the camera registry from the sandbox catalogue")
async def sync_catalogue(background_tasks: BackgroundTasks,
                         geocode: bool = Query(True, description="Resolve missing locations via Nominatim")):
    background_tasks.add_task(_sync_task, geocode)
    return {"message": "Catalogue sync started in the background.",
            "geocoding_enabled": geocode}


async def _sync_task(geocode: bool = True) -> None:
    cameras_data = await fetch_catalogue()
    if not cameras_data:
        logger.warning("Manual sync: catalogue unreachable")
        return
    async with AsyncSessionLocal() as db:
        await upsert_cameras(cameras_data, db, use_network=geocode)


@router.get("/catalogue", summary="Raw catalogue as published by the sandbox")
async def get_raw_catalogue():
    data = await fetch_catalogue()
    return {"count": len(data), "cameras": data}


@router.get("/status", summary="Ingest and registry status")
async def ingest_status(db: AsyncSession = Depends(get_db)):
    cameras = (await db.execute(select(Camera))).scalars().all()
    located = sum(1 for c in cameras if c.lat is not None and c.lon is not None)
    by_source: dict[str, int] = {}
    for cam in cameras:
        source = (cam.extra or {}).get("geo_source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1

    return {
        "total_cameras": len(cameras),
        "live_cameras": sum(1 for c in cameras if c.is_live),
        "located_cameras": located,
        "unlocated_cameras": len(cameras) - located,
        "location_provenance": by_source,
        "sandbox_host": settings.sentinel_host,
    }
