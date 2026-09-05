"""
Detections router — ANPR detections index.
Supports exact / partial / fuzzy plate search (pg_trgm), time range, camera filter.
Also provides sightings-to-route endpoint.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.database import get_db
from app.security import Principal, RequireOperator
from app.models import Camera, Detection

logger = logging.getLogger("sentinel.detections")
router = APIRouter()

# Public OSRM demo server. Used only to make a route follow streets instead of
# cutting across blocks; if it is unreachable the straight-line path still stands,
# so nothing in the platform depends on this call succeeding.
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"


async def snap_to_roads(coordinates: list[list[float]]) -> dict | None:
    """
    Snap a sequence of [lon, lat] sightings to the road network.

    Returns None rather than raising when the service is unavailable or the path
    is too short to route — the caller treats the snapped path as a presentation
    nicety, never as evidence.
    """
    if len(coordinates) < 2:
        return None

    # OSRM's demo server takes a limited number of waypoints per request.
    waypoints = coordinates[:25]
    path = ";".join(f"{lon},{lat}" for lon, lat in waypoints)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{OSRM_URL}{path}",
                params={"overview": "full", "geometries": "geojson"},
            )
        if response.status_code != 200:
            return None
        routes = response.json().get("routes") or []
        if not routes:
            return None
        return routes[0].get("geometry")
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.debug("OSRM snap unavailable: %s", exc)
        return None


class DetectionOut(BaseModel):
    id: UUID
    camera_id: UUID
    plate_text: str
    confidence: float
    pts_ms: Optional[int]
    detected_at: datetime
    track_id: Optional[str]
    crop_uri: Optional[str]
    vehicle_type: Optional[str]
    # Joined camera fields
    camera_name: Optional[str] = None
    camera_department: Optional[str] = None
    camera_lat: Optional[float] = None
    camera_lon: Optional[float] = None
    camera_address: Optional[str] = None

    class Config:
        from_attributes = True


class DetectionCreate(BaseModel):
    """
    Payload written by the ANPR worker.

    `camera_id` may be omitted when `camera_native_id` is supplied, so the worker
    can post using the sandbox's own camera id without first resolving our UUID.
    """
    camera_id: Optional[UUID] = None
    camera_native_id: Optional[str] = None
    plate_text: str
    confidence: float = 0.0
    pts_ms: Optional[int] = None
    track_id: Optional[str] = None
    crop_uri: Optional[str] = None
    vehicle_type: Optional[str] = None
    raw_reads: list[dict] = []
    bbox: Optional[dict] = None
    plate_format: Optional[str] = None
    grammar_corrections: int = 0


@router.get("", response_model=list[DetectionOut], summary="Search detections by plate / time / camera")
async def search_detections(
    request: Request,
    db: AsyncSession = Depends(get_db),
    plate: Optional[str] = Query(None, description="Plate text — exact, partial, or fuzzy"),
    camera_id: Optional[UUID] = Query(None),
    from_dt: Optional[datetime] = Query(None),
    to_dt:   Optional[datetime] = Query(None),
    fuzzy:   bool = Query(True, description="Use pg_trgm fuzzy match"),
    limit:   int  = Query(100, le=500),
    offset:  int  = Query(0),
    purpose: Optional[str] = Query(None, description="Why — recorded in the audit log"),
    case_ref: Optional[str] = Query(None),
    principal: Principal = RequireOperator,
):
    """
    Search detections. With fuzzy=true uses pg_trgm similarity (tolerates one bad character).
    Always joins camera name/location for display.
    """
    q = (
        select(
            Detection,
            Camera.name.label("camera_name"),
            Camera.department.label("camera_department"),
            Camera.lat.label("camera_lat"),
            Camera.lon.label("camera_lon"),
            Camera.address.label("camera_address"),
        )
        .join(Camera, Detection.camera_id == Camera.id)
    )

    if plate:
        p = plate.strip().upper()
        if fuzzy:
            # pg_trgm similarity — tolerates OCR errors
            q = q.where(
                text("similarity(detections.plate_text, :p) > 0.3")
            ).params(p=p).order_by(
                text("similarity(detections.plate_text, :p2) DESC").bindparams(p2=p)
            )
        else:
            q = q.where(Detection.plate_text.ilike(f"%{p}%"))
    if camera_id:
        q = q.where(Detection.camera_id == camera_id)
    if from_dt:
        q = q.where(Detection.detected_at >= from_dt)
    if to_dt:
        q = q.where(Detection.detected_at <= to_dt)

    if not plate:
        q = q.order_by(desc(Detection.detected_at))

    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.all()
    out = []
    for row in rows:
        det = row[0]
        d = DetectionOut(
            id=det.id,
            camera_id=det.camera_id,
            plate_text=det.plate_text,
            confidence=det.confidence,
            pts_ms=det.pts_ms,
            detected_at=det.detected_at,
            track_id=det.track_id,
            crop_uri=det.crop_uri,
            vehicle_type=det.vehicle_type,
            camera_name=row.camera_name,
            camera_department=row.camera_department,
            camera_lat=row.camera_lat,
            camera_lon=row.camera_lon,
            camera_address=row.camera_address,
        )
        out.append(d)

    # Searching the index by plate is a query about a specific vehicle, so it is
    # audited. Unfiltered browsing of recent detections is not.
    if plate:
        await audit.record(
            db, actor=principal.email, action="search_plate", object_type="plate",
            object_id=plate.strip().upper(), purpose=purpose, case_ref=case_ref,
            request=request, details={"fuzzy": fuzzy, "results": len(out)},
        )

    return out


@router.get("/route/{plate_text}", summary="Route reconstruction — all sightings of a plate ordered by time")
async def plate_route(
    plate_text: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    from_dt: Optional[datetime] = Query(None),
    to_dt: Optional[datetime] = Query(None),
    purpose: str = Query("investigation", description="Why — recorded in the audit log"),
    case_ref: Optional[str] = Query(None),
    principal: Principal = RequireOperator,
):
    """
    Returns sorted sightings + computed speed between consecutive cameras.
    Flags physically impossible transitions (>150 km/h).
    """
    from math import radians, cos, sin, asin, sqrt

    def haversine_km(lat1, lon1, lat2, lon2):
        R = 6371.0
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
        return 2 * R * asin(sqrt(a))

    p = plate_text.strip().upper()
    q = (
        select(Detection, Camera.name, Camera.lat, Camera.lon, Camera.department, Camera.address)
        .join(Camera, Detection.camera_id == Camera.id)
        .where(Detection.plate_text.ilike(f"%{p}%"))
    )
    if from_dt:
        q = q.where(Detection.detected_at >= from_dt)
    if to_dt:
        q = q.where(Detection.detected_at <= to_dt)
    q = q.order_by(Detection.detected_at)
    result = await db.execute(q)
    rows = result.all()

    sightings = []
    for i, row in enumerate(rows):
        det: Detection = row[0]
        s = {
            "index": i,
            "detection_id": str(det.id),
            "plate_text": det.plate_text,
            "confidence": det.confidence,
            "detected_at": det.detected_at.isoformat(),
            "pts_ms": det.pts_ms,
            "crop_uri": det.crop_uri,
            "camera_name": row[1],
            "lat": row[2],
            "lon": row[3],
            "department": row[4],
            "address": row[5],
            "speed_kmh": None,
            "impossible": False,
        }
        if i > 0 and sightings[-1]["lat"] and sightings[-1]["lon"] and row[2] and row[3]:
            prev = sightings[-1]
            dist = haversine_km(prev["lat"], prev["lon"], row[2], row[3])
            dt_s = (det.detected_at - datetime.fromisoformat(prev["detected_at"])).total_seconds()
            if dt_s > 0:
                speed = (dist / dt_s) * 3600
                s["speed_kmh"] = round(speed, 1)
                s["impossible"] = speed > 150
        sightings.append(s)

    # Route reconstruction is access to an individual's movement history, so it is
    # audited with the stated purpose like any other sensitive query.
    await audit.record(
        db, actor=principal.email, action="reconstruct_route", object_type="plate",
        object_id=p, purpose=purpose, case_ref=case_ref, request=request,
        details={"sightings": len(sightings),
                 "flagged_transitions": sum(1 for s in sightings if s["impossible"])},
    )

    straight_line = [[s["lon"], s["lat"]] for s in sightings if s["lat"] and s["lon"]]

    return {
        "plate": p,
        "total_sightings": len(sightings),
        "sightings": sightings,
        "flagged_transitions": sum(1 for s in sightings if s["impossible"]),
        # The straight-line path between sightings is what the data actually
        # supports; the snapped path below is a road-network interpolation and is
        # returned separately so the two are never confused.
        "route_geojson": {"type": "LineString", "coordinates": straight_line},
        "road_snapped_geojson": await snap_to_roads(straight_line),
    }


@router.post("", response_model=dict, summary="Ingest a new detection (called by ANPR worker)")
async def create_detection(body: DetectionCreate, db: AsyncSession = Depends(get_db)):
    from app.routers.watchlist import check_and_alert

    camera_id = body.camera_id
    if camera_id is None:
        if not body.camera_native_id:
            raise HTTPException(422, "Either camera_id or camera_native_id is required")
        camera_id = await db.scalar(
            select(Camera.id).where(Camera.native_id == body.camera_native_id)
        )
        if camera_id is None:
            raise HTTPException(404, f"Unknown camera '{body.camera_native_id}'")

    # Grammar metadata rides along in raw_reads so the report can state how many
    # plates needed correcting without widening the table.
    raw_reads = list(body.raw_reads)
    if body.plate_format or body.grammar_corrections:
        raw_reads.append({
            "_meta": True,
            "plate_format": body.plate_format,
            "grammar_corrections": body.grammar_corrections,
        })

    det = Detection(
        camera_id=camera_id,
        plate_text=body.plate_text.upper().strip(),
        confidence=body.confidence,
        pts_ms=body.pts_ms,
        track_id=body.track_id,
        crop_uri=body.crop_uri,
        vehicle_type=body.vehicle_type,
        raw_reads=raw_reads,
        bbox=body.bbox,
    )
    db.add(det)
    await db.flush()
    await db.refresh(det)
    # Check watchlist and fire alert if matched
    alert_created = await check_and_alert(det, db)
    await db.commit()
    return {"id": str(det.id), "alert_created": alert_created}


@router.get("/recent", summary="Most recent 50 detections across all cameras")
async def recent_detections(db: AsyncSession = Depends(get_db)):
    q = (
        select(Detection, Camera.name, Camera.department)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(desc(Detection.detected_at))
        .limit(50)
    )
    result = await db.execute(q)
    rows = result.all()
    return [
        {
            "id": str(r[0].id),
            "plate_text": r[0].plate_text,
            "confidence": r[0].confidence,
            "detected_at": r[0].detected_at,
            "crop_uri": r[0].crop_uri,
            "camera_name": r[1],
            "department": r[2],
        }
        for r in rows
    ]
