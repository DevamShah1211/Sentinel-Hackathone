"""Alerts router — list, acknowledge, resolve."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Alert, Detection, WatchlistEntry, Camera

logger = logging.getLogger("sentinel.alerts")
router = APIRouter()


class AlertOut(BaseModel):
    id: UUID
    watchlist_id: UUID
    detection_id: UUID
    matched_at: datetime
    match_type: str
    score: float
    status: str
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]
    notes: Optional[str]
    # Enriched fields
    plate_text: Optional[str] = None
    reason: Optional[str] = None
    severity: Optional[str] = None
    case_ref: Optional[str] = None
    camera_name: Optional[str] = None
    camera_id: Optional[str] = None
    crop_uri: Optional[str] = None
    detected_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[AlertOut], summary="List alerts, newest first")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="new / ack / resolved"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    q = (
        select(
            Alert,
            WatchlistEntry.plate_text,
            WatchlistEntry.reason,
            WatchlistEntry.severity,
            WatchlistEntry.case_ref,
            Detection.crop_uri,
            Detection.detected_at,
            Detection.camera_id.label("det_camera_id"),
            Camera.name.label("camera_name"),
        )
        .join(WatchlistEntry, Alert.watchlist_id == WatchlistEntry.id)
        .join(Detection, Alert.detection_id == Detection.id)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(desc(Alert.matched_at))
        .limit(limit)
        .offset(offset)
    )
    if status:
        q = q.where(Alert.status == status)
    result = await db.execute(q)
    rows = result.all()
    return [
        AlertOut(
            id=r[0].id,
            watchlist_id=r[0].watchlist_id,
            detection_id=r[0].detection_id,
            matched_at=r[0].matched_at,
            match_type=r[0].match_type,
            score=r[0].score,
            status=r[0].status,
            acknowledged_by=r[0].acknowledged_by,
            acknowledged_at=r[0].acknowledged_at,
            notes=r[0].notes,
            plate_text=r[1],
            reason=r[2],
            severity=r[3],
            case_ref=r[4],
            crop_uri=r[5],
            detected_at=r[6],
            camera_id=str(r[7]),
            camera_name=r[8],
        )
        for r in rows
    ]


@router.patch("/{alert_id}/acknowledge", summary="Acknowledge an alert")
async def acknowledge_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    operator: str = Query("operator"),
    notes: Optional[str] = Query(None),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "ack"
    alert.acknowledged_by = operator
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.notes = notes
    await db.commit()
    return {"message": "Acknowledged"}


@router.patch("/{alert_id}/resolve", summary="Resolve an alert")
async def resolve_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "resolved"
    await db.commit()
    return {"message": "Resolved"}


@router.get("/stats", summary="Alert counts by status and severity")
async def alert_stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    result = await db.execute(
        select(Alert.status, func.count(Alert.id)).group_by(Alert.status)
    )
    rows = result.all()
    return {"by_status": {r[0]: r[1] for r in rows}}
