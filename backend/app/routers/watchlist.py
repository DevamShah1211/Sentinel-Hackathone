"""
Watchlist router — CRUD + bulk import + matching logic.
Every new detection is checked: exact match first, then pg_trgm fuzzy match.
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from pydantic import BaseModel
from sqlalchemy import func, select, or_, text, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Alert, Detection, WatchlistEntry
from app.websocket_manager import ws_manager

logger = logging.getLogger("sentinel.watchlist")
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class WatchlistOut(BaseModel):
    id: UUID
    entity_type: str
    plate_text: str
    reason: str
    severity: str
    case_ref: Optional[str]
    description: Optional[str]
    added_by: Optional[str]
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WatchlistCreate(BaseModel):
    entity_type: str = "vehicle"
    plate_text: str
    reason: str = "wanted"
    severity: str = "high"
    case_ref: Optional[str] = None
    description: Optional[str] = None
    added_by: Optional[str] = "operator"


# ─── Matching logic (called by detections router) ─────────────────────────────

async def check_and_alert(detection: Detection, db: AsyncSession) -> bool:
    """
    Check a new detection against the watchlist.
    1. Exact match first.
    2. Fuzzy match via pg_trgm (similarity > 0.7).
    Fires a WebSocket alert if matched.
    Returns True if alert was created.
    """
    plate = detection.plate_text.upper().strip()

    # 1. Exact match
    result = await db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.plate_text == plate,
            WatchlistEntry.active == True,
        )
    )
    match = result.scalar_one_or_none()
    match_type = "exact"
    score = 1.0

    # 2. Fuzzy match
    if not match:
        result = await db.execute(
            select(WatchlistEntry, text("similarity(watchlist.plate_text, :p) AS sim").bindparams(p=plate))
            .where(
                WatchlistEntry.active == True,
                text("similarity(watchlist.plate_text, :p2) > 0.7").bindparams(p2=plate),
            )
            .order_by(text("sim DESC"))
            .limit(1)
        )
        row = result.first()
        if row:
            match, score = row[0], row[1]
            match_type = "fuzzy"

    if not match:
        return False

    # Create alert
    alert = Alert(
        watchlist_id=match.id,
        detection_id=detection.id,
        match_type=match_type,
        score=score,
        status="new",
    )
    db.add(alert)
    await db.flush()

    # Broadcast via WebSocket
    alert_payload = {
        "alert_id": str(alert.id),
        "plate_text": detection.plate_text,
        "match_type": match_type,
        "score": round(score, 3),
        "reason": match.reason,
        "severity": match.severity,
        "case_ref": match.case_ref,
        "camera_id": str(detection.camera_id),
        "detected_at": detection.detected_at.isoformat() if detection.detected_at else None,
        "crop_uri": detection.crop_uri,
        "matched_at": datetime.now(timezone.utc).isoformat(),
    }
    await ws_manager.broadcast_alert(alert_payload)
    logger.info(f"ALERT: plate {plate} matched watchlist ({match_type}, score={score:.2f})")
    return True


# ─── Router endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[WatchlistOut], summary="List watchlist entries")
async def list_watchlist(
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(True),
    limit: int = 200,
):
    q = select(WatchlistEntry).order_by(desc(WatchlistEntry.created_at)).limit(limit)
    if active_only:
        q = q.where(WatchlistEntry.active == True)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=WatchlistOut, summary="Add a plate to the watchlist")
async def add_to_watchlist(body: WatchlistCreate, db: AsyncSession = Depends(get_db)):
    entry = WatchlistEntry(**body.model_dump())
    entry.plate_text = entry.plate_text.upper().strip()
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}", summary="Deactivate a watchlist entry")
async def remove_from_watchlist(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WatchlistEntry).where(WatchlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Watchlist entry not found")
    entry.active = False
    await db.commit()
    return {"message": "Deactivated"}


@router.post("/bulk-import", summary="Bulk import plates from CSV (plate,reason,severity,case_ref)")
async def bulk_import(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    added_by: str = "bulk-import",
):
    content = await file.read()
    text_content = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text_content))
    created = 0
    errors = []
    for i, row in enumerate(reader):
        plate = row.get("plate") or row.get("plate_text") or row.get("Plate")
        if not plate:
            errors.append(f"Row {i+2}: missing plate")
            continue
        entry = WatchlistEntry(
            plate_text=plate.strip().upper(),
            reason=row.get("reason", "wanted"),
            severity=row.get("severity", "high"),
            case_ref=row.get("case_ref"),
            description=row.get("description"),
            added_by=added_by,
        )
        db.add(entry)
        created += 1
    await db.commit()
    return {"created": created, "errors": errors}


from fastapi import Query  # noqa: E402 — avoid circular at top
