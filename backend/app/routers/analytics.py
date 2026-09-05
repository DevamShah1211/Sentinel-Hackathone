"""
Analytics router — dashboard summaries + output report generation (XLSX + PDF).
The output report is a required submission artefact per the playbook.
"""
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.database import get_db
from app.security import (
    CurrentPrincipal, Principal, RequireOperator, RequireStateAdmin,
)
from app.models import Alert, AuditLog, Camera, Detection, WatchlistEntry
from app.gap_analysis import build_gap_report
from app.reporting import (
    ReportMeta, ReportRow, build_gap_xlsx, build_pdf, build_xlsx,
)

logger = logging.getLogger("sentinel.analytics")
router = APIRouter()


@router.get("/summary", summary="Platform-wide dashboard summary")
async def summary(db: AsyncSession = Depends(get_db)):
    # Camera stats
    cam_total = await db.scalar(select(func.count(Camera.id)))
    cam_live  = await db.scalar(select(func.count(Camera.id)).where(Camera.is_live == True))

    # Detection stats (last 24h)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    det_24h = await db.scalar(
        select(func.count(Detection.id)).where(Detection.detected_at >= since)
    )
    det_total = await db.scalar(select(func.count(Detection.id)))

    # Alert stats
    alerts_new  = await db.scalar(select(func.count(Alert.id)).where(Alert.status == "new"))
    alerts_total = await db.scalar(select(func.count(Alert.id)))

    # Watchlist
    wl_active = await db.scalar(
        select(func.count(WatchlistEntry.id)).where(WatchlistEntry.active == True)
    )

    # Unique plates detected (last 24h)
    unique_plates = await db.scalar(
        select(func.count(func.distinct(Detection.plate_text)))
        .where(Detection.detected_at >= since)
    )

    return {
        "cameras": {"total": cam_total, "live": cam_live, "offline": cam_total - cam_live},
        "detections": {"total": det_total, "last_24h": det_24h, "unique_plates_24h": unique_plates},
        "alerts": {"total": alerts_total, "new": alerts_new},
        "watchlist": {"active_entries": wl_active},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/top-plates", summary="Most frequently detected plates")
async def top_plates(db: AsyncSession = Depends(get_db), limit: int = 20):
    result = await db.execute(
        select(Detection.plate_text, func.count(Detection.id).label("count"))
        .group_by(Detection.plate_text)
        .order_by(desc(func.count(Detection.id)))
        .limit(limit)
    )
    return [{"plate_text": r[0], "count": r[1]} for r in result.all()]


@router.get("/detections-by-hour", summary="Detections per camera per hour (last 24h)")
async def detections_by_hour(db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(
        select(
            func.date_trunc("hour", Detection.detected_at).label("hour"),
            func.count(Detection.id).label("count"),
        )
        .where(Detection.detected_at >= since)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    return [{"hour": str(r[0]), "count": r[1]} for r in result.all()]


# ─── Output report — required submission artefact ─────────────────────────────

async def _collect_report_rows(
    db: AsyncSession,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
    plate: Optional[str],
    camera_id: Optional[str],
    limit: int,
) -> tuple[list[ReportRow], ReportMeta]:
    """Pull detections with their camera context and summarise them."""
    query = (
        select(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(desc(Detection.detected_at))
        .limit(limit)
    )
    if from_dt:
        query = query.where(Detection.detected_at >= from_dt)
    if to_dt:
        query = query.where(Detection.detected_at <= to_dt)
    if plate:
        query = query.where(Detection.plate_text.ilike(f"%{plate.strip().upper()}%"))
    if camera_id:
        query = query.where(Camera.native_id == camera_id)

    records = (await db.execute(query)).all()

    rows = [
        ReportRow(
            plate_text=detection.plate_text,
            confidence=detection.confidence or 0.0,
            camera_native_id=camera.native_id,
            camera_name=camera.name,
            department=camera.department,
            lat=camera.lat,
            lon=camera.lon,
            address=camera.address,
            detected_at=detection.detected_at,
            pts_ms=detection.pts_ms,
            track_id=detection.track_id,
            crop_uri=detection.crop_uri,
            geo_source=(camera.extra or {}).get("geo_source"),
        )
        for detection, camera in records
    ]

    meta = ReportMeta(
        total_detections=len(rows),
        unique_plates=len({r.plate_text for r in rows}),
        cameras_covered=len({r.camera_native_id for r in rows}),
        watchlist_alerts=await db.scalar(select(func.count(Alert.id))) or 0,
        window_from=from_dt,
        window_to=to_dt,
    )
    return rows, meta


@router.get("/report/xlsx", summary="Output report as XLSX (required submission artefact)")
async def download_xlsx(
    request: Request,
    db: AsyncSession = Depends(get_db),
    from_dt: Optional[datetime] = Query(None),
    to_dt: Optional[datetime] = Query(None),
    plate: Optional[str] = Query(None, description="Restrict to one plate"),
    camera_id: Optional[str] = Query(None, description="Restrict to one camera (native id)"),
    limit: int = Query(10000, le=50000),
    purpose: str = Query("hackathon-demonstration", description="Why — recorded in the audit log"),
    case_ref: Optional[str] = Query(None),
    principal: Principal = RequireOperator,
):
    rows, meta = await _collect_report_rows(db, from_dt, to_dt, plate, camera_id, limit)
    payload = build_xlsx(rows, meta)

    await audit.record(
        db, actor=principal.email, action="export_report", object_type="report",
        object_id="xlsx", purpose=purpose, case_ref=case_ref, request=request,
        details={"rows": len(rows), "plate": plate, "camera_id": camera_id},
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="sentinel_anpr_report_{stamp}.xlsx"'},
    )


@router.get("/report/pdf", summary="Output report as PDF (required submission artefact)")
async def download_pdf(
    request: Request,
    db: AsyncSession = Depends(get_db),
    from_dt: Optional[datetime] = Query(None),
    to_dt: Optional[datetime] = Query(None),
    plate: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    limit: int = Query(10000, le=50000),
    purpose: str = Query("hackathon-demonstration"),
    case_ref: Optional[str] = Query(None),
    principal: Principal = RequireOperator,
):
    rows, meta = await _collect_report_rows(db, from_dt, to_dt, plate, camera_id, limit)
    payload = build_pdf(rows, meta)

    await audit.record(
        db, actor=principal.email, action="export_report", object_type="report",
        object_id="pdf", purpose=purpose, case_ref=case_ref, request=request,
        details={"rows": len(rows), "plate": plate, "camera_id": camera_id},
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="sentinel_anpr_report_{stamp}.pdf"'},
    )


@router.get("/audit", summary="Audit trail — who searched or exported what, and why")
async def audit_trail(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(200, le=1000),
    action: Optional[str] = Query(None),
    _: Principal = RequireStateAdmin,
):
    query = select(AuditLog).order_by(desc(AuditLog.at)).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    entries = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(entry.id),
            "actor": entry.actor,
            "action": entry.action,
            "object_type": entry.object_type,
            "object_id": entry.object_id,
            "purpose": entry.purpose,
            "case_ref": entry.case_ref,
            "details": entry.details,
            "at": entry.at,
        }
        for entry in entries
    ]


# ─── VAHAN enrichment (contract-first, mock-backed) ───────────────────────────

@router.get("/vehicle/{plate_text}",
            summary="Vehicle particulars for a plate (VAHAN adapter)")
async def vehicle_lookup(
    plate_text: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    purpose: str = Query("investigation", description="Why — recorded in the audit log"),
    case_ref: Optional[str] = Query(None),
    principal: Principal = RequireOperator,
):
    """
    Enrich a plate with owner and vehicle details.

    VAHAN is a closed system with no access route for this prototype, so the
    adapter is contract-first and backed by a documented mock. Every response
    states its `source`; a `source` of "mock" is synthetic and must not be treated
    as authoritative. See DOCS/HLD.md §10 for what changes on credential grant.
    """
    from app.adapters.vahan import VahanLookupError, VehicleNotFound, get_vahan_client

    client = get_vahan_client()
    try:
        record = await client.lookup(plate_text)
    except VehicleNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except VahanLookupError as exc:
        raise HTTPException(503, str(exc)) from exc

    # Looking up an owner is access to personal data and is always audited.
    await audit.record(
        db, actor=principal.email, action="vehicle_lookup", object_type="plate",
        object_id=record.registration_number, purpose=purpose, case_ref=case_ref,
        request=request, details={"source": record.source},
    )

    return {
        "registration_number": record.registration_number,
        "owner_name": record.owner_name,
        "vehicle_class": record.vehicle_class,
        "maker_model": record.maker_model,
        "fuel_type": record.fuel_type,
        "colour": record.colour,
        "registration_date": record.registration_date,
        "registering_authority": record.registering_authority,
        "chassis_number_masked": record.chassis_number_masked,
        "engine_number_masked": record.engine_number_masked,
        "insurance_valid_upto": record.insurance_valid_upto,
        "insurance_expired": record.insurance_expired,
        "puc_valid_upto": record.puc_valid_upto,
        "puc_expired": record.puc_expired,
        "fitness_valid_upto": record.fitness_valid_upto,
        "is_blacklisted": record.is_blacklisted,
        "blacklist_reason": record.blacklist_reason,
        "source": record.source,
        "is_authoritative": not record.is_mock,
        "disclaimer": (
            "Synthetic record from the documented VAHAN mock adapter — not "
            "authoritative. See DOCS/HLD.md section 10."
        ) if record.is_mock else None,
        "retrieved_at": record.retrieved_at,
    }


# ─── Gap analysis — Model 1 deliverable ──────────────────────────────────────

@router.get("/gap-report", summary="Coverage gap and ageing-infrastructure analysis")
async def gap_report(db: AsyncSession = Depends(get_db)):
    """
    Where the estate is thin, and which cameras need attention.

    The problem statement asks for "gap-analysis reports for uncovered zones and
    ageing infrastructure"; both halves are computed from the registry. See
    app/gap_analysis.py for how coverage and condition are determined, and what
    is deliberately reported as unknown rather than assumed healthy.
    """
    report = await build_gap_report(db)
    return {
        "generated_at": report.generated_at,
        "summary": {
            "cameras_total": report.total_cameras,
            "cameras_located": report.located_cameras,
            "districts_total": report.districts_total,
            "districts_covered": report.districts_covered,
            "districts_uncovered": report.districts_uncovered,
            "coverage_percent": report.coverage_percent,
            "ageing_findings": len(report.ageing),
        },
        "coverage": [
            {
                "district": c.district,
                "lat": c.lat,
                "lon": c.lon,
                "cameras_within_radius": c.cameras_within_radius,
                "nearest_camera_km": c.nearest_camera_km,
                "nearest_camera": c.nearest_camera_name,
                "severity": c.severity,
            }
            for c in report.coverage
        ],
        "ageing": [
            {
                "native_id": f.native_id,
                "name": f.name,
                "district": f.district,
                "issue": f.issue,
                "detail": f.detail,
                "severity": f.severity,
            }
            for f in report.ageing
        ],
    }


@router.get("/gap-report/xlsx", summary="Gap-analysis report as XLSX (deliverable)")
async def gap_report_xlsx(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = RequireOperator,
):
    report = await build_gap_report(db)
    payload = build_gap_xlsx(report)

    await audit.record(
        db, actor=principal.email, action="export_gap_report",
        object_type="report", object_id="gap-analysis-xlsx",
        purpose="registry-planning", request=request,
        details={"districts_uncovered": report.districts_uncovered,
                 "ageing_findings": len(report.ageing)},
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="sentinel_gap_analysis_{stamp}.xlsx"'},
    )
