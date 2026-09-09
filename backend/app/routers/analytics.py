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
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.database import get_db
from app.security import (
    CurrentPrincipal, Principal, RequireOperator, RequireStateAdmin,
    RequireViewer,
)
from app.models import (Alert, AuditLog, Camera, Detection, SceneObservation,
                        WatchlistEntry)
from app.gap_analysis import build_gap_report
from app.reporting import (
    ReportMeta, ReportRow, build_gap_xlsx, build_pdf, build_xlsx,
)

logger = logging.getLogger("sentinel.analytics")
router = APIRouter()


@router.get("/summary", summary="Platform-wide dashboard summary")
async def summary(db: AsyncSession = Depends(get_db),
                  principal: Principal = RequireViewer):
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
async def top_plates(db: AsyncSession = Depends(get_db),
                     limit: int = Query(20, le=200),
                     principal: Principal = RequireOperator):
    result = await db.execute(
        select(Detection.plate_text, func.count(Detection.id).label("count"))
        .group_by(Detection.plate_text)
        .order_by(desc(func.count(Detection.id)))
        .limit(limit)
    )
    return [{"plate_text": r[0], "count": r[1]} for r in result.all()]


@router.get("/detections-by-hour", summary="Detections per camera per hour (last 24h)")
async def detections_by_hour(db: AsyncSession = Depends(get_db),
                             principal: Principal = RequireViewer):
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
async def gap_report(db: AsyncSession = Depends(get_db),
                     principal: Principal = RequireOperator):
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


# ─── Scene analytics: vehicle, person and object counts ──────────────────────

class SceneObservationIn(BaseModel):
    """One aggregated minute from a camera."""
    camera_native_id: str
    bucket_start: datetime
    bucket_seconds: int = 60
    frames_sampled: int = 0
    counts_by_label: dict[str, int] = {}
    counts_by_category: dict[str, int] = {}
    max_confidence: float = 0.0

    model_config = {"extra": "forbid"}


@router.post("/scene", summary="Ingest one minute of scene counts")
async def ingest_scene_observation(
    body: SceneObservationIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = RequireOperator,
):
    """
    Write one aggregated bucket.

    Guarded like detection ingest: this is analytics about a public place and,
    while it identifies nobody, it still describes police camera coverage.

    Idempotent on (camera, bucket_start). A worker that restarts mid-minute
    re-sends the bucket it was building, and re-running an analysis over
    recorded footage should correct the row rather than duplicate it — which is
    also why the table carries a unique constraint rather than relying on this
    check alone.
    """
    camera = (await db.execute(
        select(Camera).where(Camera.native_id == body.camera_native_id)
    )).scalar_one_or_none()
    if camera is None:
        raise HTTPException(404, f"Unknown camera '{body.camera_native_id}'")

    bucket_start = body.bucket_start
    if bucket_start.tzinfo is None:
        bucket_start = bucket_start.replace(tzinfo=timezone.utc)

    existing = (await db.execute(
        select(SceneObservation).where(
            SceneObservation.camera_id == camera.id,
            SceneObservation.bucket_start == bucket_start,
        )
    )).scalar_one_or_none()

    if existing is not None:
        existing.frames_sampled = body.frames_sampled
        existing.counts_by_label = body.counts_by_label
        existing.counts_by_category = body.counts_by_category
        existing.max_confidence = body.max_confidence
        await db.commit()
        return {"status": "updated", "camera": camera.native_id}

    db.add(SceneObservation(
        camera_id=camera.id,
        bucket_start=bucket_start,
        bucket_seconds=body.bucket_seconds,
        frames_sampled=body.frames_sampled,
        counts_by_label=body.counts_by_label,
        counts_by_category=body.counts_by_category,
        max_confidence=body.max_confidence,
    ))
    await db.commit()
    return {"status": "created", "camera": camera.native_id}


@router.get("/scene/summary", summary="Vehicle and person counts across the grid")
async def scene_summary(
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
    principal: Principal = RequireViewer,
):
    """
    What the cameras have been seeing, aggregated over a window.

    This is the analytics tier that works where ANPR does not. The measured
    finding in MEASUREMENTS section 2g is that no camera on this grid produces a
    readable plate, while the same frames contain vehicles and people a detector
    resolves comfortably — so a deployment that reported only plate reads would
    report nothing at all from these cameras.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = (await db.execute(
        select(SceneObservation.counts_by_category,
               SceneObservation.counts_by_label,
               SceneObservation.frames_sampled)
        .where(SceneObservation.bucket_start >= since)
    )).all()

    # Peak within a bucket, summed across buckets, is a throughput estimate
    # rather than a unique-object count — a vehicle standing at a junction for
    # three minutes is counted three times. Named so nobody reads it as a
    # vehicle census.
    observations = {"vehicle": 0, "person": 0}
    by_label: dict[str, int] = {}
    frames = 0
    for by_category, labels, sampled in rows:
        frames += sampled or 0
        for key, n in (by_category or {}).items():
            observations[key] = observations.get(key, 0) + n
        for key, n in (labels or {}).items():
            by_label[key] = by_label.get(key, 0) + n

    cameras_reporting = (await db.execute(
        select(func.count(func.distinct(SceneObservation.camera_id)))
        .where(SceneObservation.bucket_start >= since)
    )).scalar() or 0

    return {
        "window_hours": hours,
        "buckets": len(rows),
        "frames_analysed": frames,
        "cameras_reporting": cameras_reporting,
        "observations": observations,
        "by_label": by_label,
        "note": ("Counts are peak-per-minute summed over the window: a throughput "
                 "estimate, not a count of distinct vehicles."),
    }


@router.get("/scene/by-camera", summary="Per-camera activity, busiest first")
async def scene_by_camera(
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(30, ge=1, le=200),
    principal: Principal = RequireViewer,
):
    """Which cameras are busy, and which are watching an empty street."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = (await db.execute(
        select(SceneObservation.camera_id, Camera.name, Camera.department,
               SceneObservation.counts_by_category, SceneObservation.frames_sampled)
        .join(Camera, Camera.id == SceneObservation.camera_id)
        .where(SceneObservation.bucket_start >= since)
    )).all()

    per_camera: dict[str, dict] = {}
    for camera_id, name, department, by_category, sampled in rows:
        key = str(camera_id)
        entry = per_camera.setdefault(key, {
            "camera_id": key, "camera_name": name, "department": department,
            "vehicles": 0, "people": 0, "frames_analysed": 0, "buckets": 0,
        })
        entry["vehicles"] += (by_category or {}).get("vehicle", 0)
        entry["people"] += (by_category or {}).get("person", 0)
        entry["frames_analysed"] += sampled or 0
        entry["buckets"] += 1

    ranked = sorted(per_camera.values(),
                    key=lambda r: -(r["vehicles"] + r["people"]))
    return {"window_hours": hours, "cameras": ranked[:limit]}
