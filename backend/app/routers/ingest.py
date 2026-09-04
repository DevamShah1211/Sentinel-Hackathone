"""
Ingest router — syncs camera catalogue from the Sentinel sandbox.
GET /api/ingest  →  camera list injested into the cameras table.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import get_db, AsyncSessionLocal
from app.models import Camera
from app.settings import settings

from urllib.parse import quote

logger = logging.getLogger("sentinel.ingest")
router = APIRouter()


def _build_camera_from_catalogue(item: dict) -> dict:
    """Transform a single catalogue entry into our camera model dict."""
    native_id = str(item.get("id", ""))
    
    # Auth credentials formatting per Playbook: email @ must be %40
    email = settings.sentinel_user_email
    password = settings.sentinel_user_password
    if email and password:
        encoded_email = quote(email, safe='').replace('@', '%40')
        auth_prefix = f"{encoded_email}:{password}@"
    else:
        auth_prefix = ""

    ip_host = settings.sentinel_ip
    cdn_host = settings.sentinel_cdn_host

    default_rtsp = f"rtsp://{auth_prefix}{ip_host}:{settings.sentinel_rtsp_port}/stream/{native_id}"
    default_hls  = f"https://{cdn_host}/{native_id}/index.m3u8"
    default_whep = f"http://{auth_prefix}{ip_host}:{settings.sentinel_whep_port}/stream/{native_id}/whep"

    return {
        "native_id":  native_id,
        "name":       item.get("name") or item.get("location") or f"Camera {native_id}",
        "department": item.get("department") or item.get("dept") or "Unknown",
        "lat":        item.get("lat") or item.get("latitude"),
        "lon":        item.get("lon") or item.get("longitude") or item.get("lng"),
        "address":    item.get("location") or item.get("address"),
        "rtsp_url":   item.get("rtsp_url") or default_rtsp,
        "hls_url":    item.get("hls_url") or default_hls,
        "whep_url":   item.get("whep_url") or default_whep,
        "codec":      item.get("codec") or "h264",
        "resolution": item.get("resolution"),
        "fps":        item.get("fps"),
        "bitrate_kbps": item.get("bitrate_kbps") or item.get("bitrate"),
        "status":     "operational" if item.get("live", True) else "unknown",
        "is_live":    bool(item.get("live", True)),
        "camera_type": item.get("type") or "fixed_dome",
        "extra":      {k: v for k, v in item.items()
                       if k not in ("id", "name", "location", "department", "lat", "lon",
                                   "rtsp_url", "hls_url", "whep_url", "codec", "resolution",
                                   "fps", "bitrate_kbps", "live", "type")},
    }


# Known location coordinate & department mappings for Sentinel cameras in Gujarat
LOCATION_PRESETS = {
    "cam01": {"lat": 23.0784, "lon": 72.5976, "department": "Traffic Police", "address": "Chimanbhai Patel Bridge, Subhash Bridge, Ahmedabad"},
    "cam02": {"lat": 23.0298, "lon": 72.5648, "department": "City Surveillance", "address": "Janpath, Ashram Road, Ahmedabad"},
    "cam03": {"lat": 23.0975, "lon": 72.5902, "department": "Smart City Mission", "address": "ONGC Office Junction, Chandkheda, Ahmedabad"},
    "cam04": {"lat": 23.0125, "lon": 72.5641, "department": "Traffic Police", "address": "Paldi Cross Road, Paldi, Ahmedabad"},
    "cam05": {"lat": 23.1065, "lon": 72.5947, "department": "National Highway Authority", "address": "Visat Three Roads, Sabarmati, Ahmedabad"},
    "cam06": {"lat": 21.5222, "lon": 70.4579, "department": "District Police", "address": "Timbavadi Gate, Junagadh"},
    "cam07": {"lat": 22.3072, "lon": 73.1812, "department": "City Surveillance", "address": "Hero Showroom Junction, Vadodara"},
    "cam08": {"lat": 21.1702, "lon": 72.8311, "department": "Traffic Police", "address": "Ring Road Junction, Surat"},
    "cam09": {"lat": 22.4707, "lon": 70.0577, "department": "Port & Highway Security", "address": "Bedi Gateway, Jamnagar"},
    "cam10": {"lat": 21.7645, "lon": 72.1519, "department": "Coastal Police", "address": "Bhavnagar Circle, Bhavnagar"},
}


def _build_camera_from_catalogue(item: dict) -> dict:
    """Transform a single catalogue entry into our camera model dict."""
    native_id = str(item.get("id", ""))
    
    # Auth credentials formatting per Playbook: email @ must be %40
    email = settings.sentinel_user_email
    password = settings.sentinel_user_password
    if email and password:
        encoded_email = quote(email, safe='').replace('@', '%40')
        auth_prefix = f"{encoded_email}:{password}@"
    else:
        auth_prefix = ""

    ip_host = settings.sentinel_ip
    cdn_host = settings.sentinel_cdn_host

    default_rtsp = f"rtsp://{auth_prefix}{ip_host}:{settings.sentinel_rtsp_port}/stream/{native_id}"
    default_hls  = f"https://{cdn_host}/{native_id}/index.m3u8"
    default_whep = f"http://{auth_prefix}{ip_host}:{settings.sentinel_whep_port}/stream/{native_id}/whep"

    # Presets for coordinates if missing in catalogue response
    preset = LOCATION_PRESETS.get(native_id, {})
    
    # Fallback coordinate calculation if not in preset
    cam_num = int(native_id.replace("cam", "")) if native_id.startswith("cam") and native_id[3:].isdigit() else 1
    fallback_lat = preset.get("lat") or item.get("lat") or item.get("latitude") or (23.0225 + (cam_num * 0.008))
    fallback_lon = preset.get("lon") or item.get("lon") or item.get("longitude") or item.get("lng") or (72.5714 + ((cam_num % 5) * 0.012))

    return {
        "native_id":  native_id,
        "name":       item.get("name") or item.get("location") or f"Camera {native_id}",
        "department": item.get("department") or item.get("dept") or preset.get("department") or "Traffic Police",
        "lat":        fallback_lat,
        "lon":        fallback_lon,
        "address":    item.get("location") or item.get("address") or preset.get("address") or f"Junction {native_id}, Gujarat",
        "rtsp_url":   item.get("rtsp_url") or default_rtsp,
        "hls_url":    item.get("hls_url") or default_hls,
        "whep_url":   item.get("whep_url") or default_whep,
        "codec":      item.get("codec") or "h264",
        "resolution": item.get("resolution") or "1920x1080",
        "fps":        item.get("fps") or 25.0,
        "bitrate_kbps": item.get("bitrate_kbps") or item.get("bitrate") or 2048,
        "status":     "operational" if item.get("live", True) else "unknown",
        "is_live":    bool(item.get("live", True)),
        "camera_type": item.get("type") or "fixed_dome",
        "extra":      {k: v for k, v in item.items()
                       if k not in ("id", "name", "location", "department", "lat", "lon",
                                   "rtsp_url", "hls_url", "whep_url", "codec", "resolution",
                                   "fps", "bitrate_kbps", "live", "type")},
    }


async def fetch_catalogue() -> list[dict]:
    """Pull the camera catalogue from the Sentinel sandbox API after authenticating."""
    email = settings.sentinel_user_email
    password = settings.sentinel_user_password

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=False) as client:
        # Step 1: Login if credentials are set
        if email and password:
            try:
                login_url = f"https://{settings.sentinel_cdn_host}/auth/login"
                logger.info(f"Logging into Sentinel portal: {login_url}")
                await client.post(login_url, data={"email": email, "password": password})
            except Exception as exc:
                logger.warning(f"Sentinel portal login attempt failed: {exc}")

        # Step 2: Request cameras.json and API ingest endpoints
        urls = [
            f"https://{settings.sentinel_cdn_host}/cameras.json",
            f"http://{settings.sentinel_host}/api/ingest",
            f"https://{settings.sentinel_cdn_host}/api/ingest",
        ]
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    logger.info(f"Successfully fetched {len(data)} cameras from {url}")
                    return data
                cam_list = data.get("cameras") or data.get("data") or []
                if cam_list:
                    logger.info(f"Successfully fetched {len(cam_list)} cameras from {url}")
                    return cam_list
            except Exception as exc:
                logger.debug(f"Catalogue fetch attempt failed for ({url}): {exc}")

    logger.warning("Could not reach sandbox catalogue endpoints.")
    return []


async def upsert_cameras(cameras_data: list[dict], db: AsyncSession) -> int:
    """Upsert camera records — insert or update based on native_id."""
    count = 0
    for item in cameras_data:
        row = _build_camera_from_catalogue(item)
        if not row["native_id"]:
            continue
        # Check if exists
        result = await db.execute(select(Camera).where(Camera.native_id == row["native_id"]))
        existing = result.scalar_one_or_none()
        if existing:
            for k, v in row.items():
                if v is not None:
                    setattr(existing, k, v)
            existing.last_seen_at = datetime.now(timezone.utc)
        else:
            cam = Camera(**row, last_seen_at=datetime.now(timezone.utc))
            db.add(cam)
        count += 1
    await db.commit()
    return count


async def sync_catalogue_on_startup():
    """Called once on app startup to populate the cameras table."""
    await asyncio.sleep(2)  # Let DB init settle
    logger.info("Fetching Sentinel sandbox catalogue…")
    cameras_data = await fetch_catalogue()
    if cameras_data:
        async with AsyncSessionLocal() as db:
            count = await upsert_cameras(cameras_data, db)
        logger.info(f"Synced {count} cameras from sandbox catalogue.")
    else:
        logger.warning("No cameras returned from catalogue; using existing DB data.")


# ─── Router endpoints ─────────────────────────────────────────────────────────

@router.post("/sync", summary="Manually trigger catalogue sync from Sentinel sandbox")
async def sync_catalogue(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    background_tasks.add_task(_sync_task)
    return {"message": "Catalogue sync started in background."}


async def _sync_task():
    cameras_data = await fetch_catalogue()
    async with AsyncSessionLocal() as db:
        count = await upsert_cameras(cameras_data, db)
    logger.info(f"Manual sync: {count} cameras upserted.")


@router.get("/catalogue", summary="Fetch raw catalogue from Sentinel sandbox")
async def get_raw_catalogue():
    data = await fetch_catalogue()
    return {"count": len(data), "cameras": data}


@router.get("/status", summary="Ingest pipeline status")
async def ingest_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera))
    cams = result.scalars().all()
    live = sum(1 for c in cams if c.is_live)
    return {
        "total_cameras": len(cams),
        "live_cameras": live,
        "offline_cameras": len(cams) - live,
        "sandbox_host": settings.sentinel_host,
    }
