"""
Detections router — ANPR detections index.
Supports exact / partial / fuzzy plate search (pg_trgm), time range, camera filter.
Also provides sightings-to-route endpoint.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Camera, Detection

logger = logging.getLogger("sentinel.detections")
router = APIRouter()


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
    camera_id: UUID
    plate_text: str
    confidence: float = 0.0
    pts_ms: Optional[int] = None
    track_id: Optional[str] = None
    crop_uri: Optional[str] = None
    vehicle_type: Optional[str] = None
    raw_reads: list[dict] = []
    bbox: Optional[dict] = None


@router.get("", response_model=list[DetectionOut], summary="Search detections by plate / time / camera")
async def search_detections(
    db: AsyncSession = Depends(get_db),
    plate: Optional[str] = Query(None, description="Plate text — exact, partial, or fuzzy"),
    camera_id: Optional[UUID] = Query(None),
    from_dt: Optional[datetime] = Query(None),
    to_dt:   Optional[datetime] = Query(None),
    fuzzy:   bool = Query(True, description="Use pg_trgm fuzzy match"),
    limit:   int  = Query(100, le=500),
    offset:  int  = Query(0),
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
    return out


@router.get("/route/{plate_text}", summary="Route reconstruction — all sightings of a plate ordered by time")
async def plate_route(
    plate_text: str,
    db: AsyncSession = Depends(get_db),
    from_dt: Optional[datetime] = Query(None),
    to_dt: Optional[datetime] = Query(None),
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

    return {
        "plate": p,
        "total_sightings": len(sightings),
        "sightings": sightings,
        "route_geojson": {
            "type": "LineString",
            "coordinates": [
                [s["lon"], s["lat"]]
                for s in sightings if s["lat"] and s["lon"]
            ],
        },
    }


@router.post("", response_model=dict, summary="Ingest a new detection (called by ANPR worker)")
async def create_detection(body: DetectionCreate, db: AsyncSession = Depends(get_db)):
    from app.routers.watchlist import check_and_alert
    det = Detection(
        camera_id=body.camera_id,
        plate_text=body.plate_text.upper().strip(),
        confidence=body.confidence,
        pts_ms=body.pts_ms,
        track_id=body.track_id,
        crop_uri=body.crop_uri,
        vehicle_type=body.vehicle_type,
        raw_reads=body.raw_reads,
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
