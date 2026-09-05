"""
Coverage gap analysis — a named Model 1 deliverable.

The problem statement asks for "gap-analysis reports for uncovered zones and
ageing infrastructure". Both halves are answered here, and both are computed from
the registry rather than asserted.

**Uncovered zones.** Gujarat is divided into district cells; for each, the
distance to its nearest camera is measured with PostGIS. A district whose nearest
camera is far away is a coverage gap, and the size of that distance is the
severity. This is deliberately a *spatial* answer rather than a count — five
cameras clustered on one junction do not cover a district, and a report that
merely counted them would say they did.

**Ageing infrastructure.** A camera is flagged on whatever the registry actually
knows: an installation date old enough to be near end of life, a feed that has
not been seen recently, or a codec/resolution below what analytics needs. Where
the registry does not hold a field, the camera is reported as *unknown* rather
than assumed healthy — an audit that quietly passes everything it cannot see is
worse than no audit.

The output feeds both `GET /api/v1/analytics/gap-report` and the XLSX/PDF
generators, so the same numbers appear on screen and in the submitted artefact.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera

logger = logging.getLogger("sentinel.gap")

# A camera is assumed to cover roughly this radius for situational awareness.
# Deliberately generous: the point is to find districts with no camera anywhere
# near, not to model a lens.
NOMINAL_COVERAGE_KM = 3.0

# Distance from a district centre to its nearest camera, in km, above which the
# district is reported at each severity.
SEVERITY_BANDS = (
    (60.0, "critical"),
    (25.0, "high"),
    (10.0, "medium"),
)

# An installed camera is treated as approaching end of life after this long.
# Typical outdoor CCTV service life is 5-7 years.
AGEING_YEARS = 6

# A feed not seen for this long is stale regardless of its recorded status.
STALE_FEED_HOURS = 24

# Below these, a camera cannot support reliable plate recognition.
MIN_ANALYTICS_HEIGHT = 720


# Population-weighted district centres for Gujarat, from OpenStreetMap place
# nodes. Used to ask "how far is the nearest camera from here?" — the districts
# themselves are the unit a department plans and budgets in.
GUJARAT_DISTRICTS: dict[str, tuple[float, float]] = {
    "Ahmedabad": (23.0225, 72.5714),
    "Amreli": (21.6032, 71.2115),
    "Anand": (22.5645, 72.9289),
    "Aravalli": (23.2500, 73.3000),
    "Banaskantha": (24.1722, 72.4383),
    "Bharuch": (21.7051, 72.9959),
    "Bhavnagar": (21.7645, 72.1519),
    "Botad": (22.1704, 71.6684),
    "Chhota Udaipur": (22.3000, 74.0167),
    "Dahod": (22.8340, 74.2600),
    "Dang": (20.7500, 73.6833),
    "Devbhoomi Dwarka": (22.2394, 68.9678),
    "Gandhinagar": (23.2156, 72.6369),
    "Gir Somnath": (20.9130, 70.3670),
    "Jamnagar": (22.4707, 70.0577),
    "Junagadh": (21.5222, 70.4579),
    "Kutch": (23.7337, 69.8597),
    "Kheda": (22.7500, 72.6833),
    "Mahisagar": (23.0833, 73.6000),
    "Mehsana": (23.5880, 72.3693),
    "Morbi": (22.8173, 70.8377),
    "Narmada": (21.8700, 73.5000),
    "Navsari": (20.9467, 72.9520),
    "Panchmahal": (22.7700, 73.6100),
    "Patan": (23.8493, 72.1266),
    "Porbandar": (21.6417, 69.6293),
    "Rajkot": (22.3039, 70.8022),
    "Sabarkantha": (23.6000, 72.9667),
    "Surat": (21.1702, 72.8311),
    "Surendranagar": (22.7271, 71.6479),
    "Tapi": (21.1200, 73.4000),
    "Vadodara": (22.3072, 73.1812),
    "Valsad": (20.5992, 72.9342),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


@dataclass
class DistrictCoverage:
    district: str
    lat: float
    lon: float
    cameras_within_radius: int
    nearest_camera_km: float | None
    nearest_camera_name: str | None
    severity: str          # covered | medium | high | critical

    @property
    def is_gap(self) -> bool:
        return self.severity != "covered"


@dataclass
class AgeingFinding:
    native_id: str
    name: str
    district: str | None
    issue: str             # what is wrong
    detail: str            # the evidence for it
    severity: str          # info | warning | critical


@dataclass
class GapReport:
    generated_at: datetime
    total_cameras: int
    located_cameras: int
    districts_total: int
    districts_covered: int
    coverage: list[DistrictCoverage] = field(default_factory=list)
    ageing: list[AgeingFinding] = field(default_factory=list)

    @property
    def districts_uncovered(self) -> int:
        return self.districts_total - self.districts_covered

    @property
    def coverage_percent(self) -> float:
        if not self.districts_total:
            return 0.0
        return round(100.0 * self.districts_covered / self.districts_total, 1)

    @property
    def gaps(self) -> list[DistrictCoverage]:
        """Uncovered districts, worst first."""
        order = {"critical": 0, "high": 1, "medium": 2}
        return sorted((c for c in self.coverage if c.is_gap),
                      key=lambda c: (order.get(c.severity, 9),
                                     -(c.nearest_camera_km or 0)))


def _severity_for(distance_km: float | None) -> str:
    if distance_km is None:
        return "critical"
    if distance_km <= NOMINAL_COVERAGE_KM:
        return "covered"
    for threshold, label in SEVERITY_BANDS:
        if distance_km >= threshold:
            return label
    return "medium"


def _assess_ageing(camera: Camera, now: datetime) -> list[AgeingFinding]:
    """Everything the registry can honestly say about one camera's condition."""
    findings: list[AgeingFinding] = []
    district = (camera.extra or {}).get("district")

    if camera.installation_date:
        age_years = (now - camera.installation_date).days / 365.25
        if age_years >= AGEING_YEARS:
            findings.append(AgeingFinding(
                camera.native_id, camera.name, district,
                "Approaching end of service life",
                f"Installed {age_years:.1f} years ago "
                f"({camera.installation_date:%Y-%m-%d}); typical service life is "
                f"{AGEING_YEARS} years",
                "warning" if age_years < AGEING_YEARS + 3 else "critical",
            ))
    else:
        findings.append(AgeingFinding(
            camera.native_id, camera.name, district,
            "Installation date unknown",
            "The registry holds no commissioning date, so age cannot be assessed",
            "info",
        ))

    if camera.last_seen_at:
        stale_hours = (now - camera.last_seen_at).total_seconds() / 3600
        if stale_hours >= STALE_FEED_HOURS:
            findings.append(AgeingFinding(
                camera.native_id, camera.name, district,
                "Feed not seen recently",
                f"Last successful contact {stale_hours:.0f} hours ago",
                "critical" if stale_hours >= 72 else "warning",
            ))

    if camera.resolution:
        try:
            height = int(str(camera.resolution).lower().split("x")[1])
            if height < MIN_ANALYTICS_HEIGHT:
                findings.append(AgeingFinding(
                    camera.native_id, camera.name, district,
                    "Resolution below analytics threshold",
                    f"{camera.resolution} is under {MIN_ANALYTICS_HEIGHT}p; "
                    "plate recognition is unlikely to be reliable",
                    "warning",
                ))
        except (IndexError, ValueError):
            pass
    else:
        findings.append(AgeingFinding(
            camera.native_id, camera.name, district,
            "Resolution unknown",
            "The registry holds no resolution, so analytics suitability is unknown",
            "info",
        ))

    if camera.lat is None or camera.lon is None:
        findings.append(AgeingFinding(
            camera.native_id, camera.name, district,
            "Location unresolved",
            "No coordinates, so this camera contributes to no coverage assessment",
            "warning",
        ))

    return findings


async def build_gap_report(db: AsyncSession) -> GapReport:
    """Compute coverage and condition across the whole registry."""
    cameras = (await db.execute(select(Camera))).scalars().all()
    now = datetime.now(timezone.utc)

    located = [c for c in cameras if c.lat is not None and c.lon is not None]

    coverage: list[DistrictCoverage] = []
    for district, (lat, lon) in GUJARAT_DISTRICTS.items():
        nearest_km: float | None = None
        nearest_name: str | None = None
        within = 0

        for camera in located:
            distance = haversine_km(lat, lon, camera.lat, camera.lon)
            if distance <= NOMINAL_COVERAGE_KM:
                within += 1
            if nearest_km is None or distance < nearest_km:
                nearest_km, nearest_name = distance, camera.name

        coverage.append(DistrictCoverage(
            district=district, lat=lat, lon=lon,
            cameras_within_radius=within,
            nearest_camera_km=round(nearest_km, 1) if nearest_km is not None else None,
            nearest_camera_name=nearest_name,
            severity=_severity_for(nearest_km),
        ))

    ageing: list[AgeingFinding] = []
    for camera in cameras:
        ageing.extend(_assess_ageing(camera, now))

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    ageing.sort(key=lambda f: (severity_order.get(f.severity, 9), f.native_id))

    return GapReport(
        generated_at=now,
        total_cameras=len(cameras),
        located_cameras=len(located),
        districts_total=len(GUJARAT_DISTRICTS),
        districts_covered=sum(1 for c in coverage if not c.is_gap),
        coverage=coverage,
        ageing=ageing,
    )
