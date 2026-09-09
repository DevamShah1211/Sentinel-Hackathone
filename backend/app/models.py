"""
SQLAlchemy ORM models for Sentinel CCTV Platform.
Schema follows the Tech Doc Appendix A (camera schema) and the playbook tables.
Supabase Postgres already has PostGIS — enable it once via SQL:
  CREATE EXTENSION IF NOT EXISTS postgis;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func, JSON, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True,
                  default=uuid.uuid4, server_default=func.gen_random_uuid())


# ─────────────────────────────────────────────────────────────────────────────
# CAMERAS  (Model 1 — Registry & Model 2 — Viewing)
# ─────────────────────────────────────────────────────────────────────────────
class Camera(Base):
    __tablename__ = "cameras"

    id           = uuid_pk()
    native_id    = Column(String(100), nullable=False, index=True)   # Sandbox camera id
    name         = Column(String(255), nullable=False)
    department   = Column(String(100), nullable=False, default="Unknown")
    location     = Column(Geography("POINT", srid=4326), nullable=True)  # PostGIS point
    lat          = Column(Float, nullable=True)
    lon          = Column(Float, nullable=True)
    address      = Column(Text, nullable=True)

    # Stream URLs
    rtsp_url     = Column(String(500), nullable=True)
    hls_url      = Column(String(500), nullable=True)
    whep_url     = Column(String(500), nullable=True)

    # Technical specs
    codec        = Column(String(20), nullable=True)   # h264 / h265
    resolution   = Column(String(20), nullable=True)
    fps          = Column(Float, nullable=True)
    bitrate_kbps = Column(Integer, nullable=True)

    # Status
    status       = Column(String(30), nullable=False, default="unknown")
    is_live      = Column(Boolean, default=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    # Registry metadata
    camera_type  = Column(String(50), nullable=True)   # fixed_dome / bullet / ptz / anpr
    make         = Column(String(100), nullable=True)
    model        = Column(String(100), nullable=True)
    installation_date = Column(DateTime(timezone=True), nullable=True)
    connectivity = Column(String(50), nullable=True)   # fibre / 4g / wifi / lan
    ownership    = Column(String(100), nullable=True)

    extra        = Column(JSONB, default={})            # catch-all for sandbox extra fields
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(),
                          onupdate=func.now())

    detections   = relationship("Detection", back_populates="camera", lazy="dynamic")


# ─────────────────────────────────────────────────────────────────────────────
# DETECTIONS  (ANPR outputs)
# ─────────────────────────────────────────────────────────────────────────────
class Detection(Base):
    __tablename__ = "detections"

    id           = uuid_pk()
    camera_id    = Column(UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False, index=True)
    plate_text   = Column(String(20), nullable=False, index=True)
    confidence   = Column(Float, nullable=False, default=0.0)
    pts_ms       = Column(BigInteger, nullable=True)         # PTS from stream (ms)
    detected_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    track_id     = Column(String(50), nullable=True)

    # Evidence
    crop_uri     = Column(String(500), nullable=True)        # path to JPEG crop
    vehicle_type = Column(String(50), nullable=True)
    raw_reads    = Column(JSONB, default=[])                 # all per-frame reads on this track
    bbox         = Column(JSONB, nullable=True)              # {"x1","y1","x2","y2"}

    # Operator-applied event tags — Model 2's "event tagging and camera-wise
    # indexing". Free-form so a control room can label what its own operations
    # need (convoy, wrong-way, suspect-vehicle, follow-up) rather than being held
    # to a fixed vocabulary decided here. Indexed for search.
    tags         = Column(JSONB, default=list, nullable=False, server_default="[]")
    notes        = Column(Text, nullable=True)

    camera       = relationship("Camera", back_populates="detections")
    alert        = relationship("Alert", back_populates="detection", uselist=False)


# ─────────────────────────────────────────────────────────────────────────────
# SCENE ANALYTICS  (vehicle / person / object detection)
# ─────────────────────────────────────────────────────────────────────────────

class SceneObservation(Base):
    """
    What a camera saw, as counts per class over a time bucket.

    Separate from `detections` on purpose. A detection is one vehicle, identified,
    and is evidence about that vehicle. A scene observation is a count — seven
    vehicles and five people in this minute at this camera — and is evidence
    about a place. Storing counts as rows in `detections` would mean a
    plate-shaped table full of records with no plate, and every plate query
    would then have to exclude them.

    **Bucketed, not per frame.** At one frame per second across 80,000 cameras,
    per-frame rows would be 6.9 billion a day. A minute bucket is 1.4% of that
    and answers every question an operator actually asks: how busy was this
    junction, when did footfall peak, was anything moving at 3 a.m. The frames
    within a bucket are aggregated by the worker before they ever reach the
    database, so the write rate is bounded by camera count rather than by frame
    rate — which is what makes this tier scale.

    Retention differs from detections for the same reason: counts age into
    statistics, so they compress well and can move to cold storage on a shorter
    schedule than evidentiary plate records.
    """
    __tablename__ = "scene_observations"

    id          = uuid_pk()
    camera_id   = Column(UUID(as_uuid=True), ForeignKey("cameras.id"),
                         nullable=False, index=True)
    # Start of the bucket, truncated to the minute, in UTC.
    bucket_start = Column(DateTime(timezone=True), nullable=False, index=True)
    bucket_seconds = Column(Integer, nullable=False, default=60)

    # Frames actually inferred in this bucket. Without it a count of zero is
    # ambiguous — nothing was there, or nothing was looked at.
    frames_sampled = Column(Integer, nullable=False, default=0)

    # Peak simultaneous count per class within the bucket, and per category.
    # Peak rather than sum: summing across frames counts the same parked car
    # sixty times, which is not a number anyone wants.
    counts_by_label    = Column(JSONB, default=dict, nullable=False, server_default="{}")
    counts_by_category = Column(JSONB, default=dict, nullable=False, server_default="{}")

    # Highest confidence seen in the bucket, for triaging a quiet camera.
    max_confidence = Column(Float, nullable=False, default=0.0)

    camera = relationship("Camera")

    __table_args__ = (
        # The query this table exists to serve is "this camera, this window",
        # and the uniqueness stops a restarted worker double-writing a bucket.
        UniqueConstraint("camera_id", "bucket_start", name="uq_scene_camera_bucket"),
        Index("ix_scene_camera_time", "camera_id", "bucket_start"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# WATCHLIST
# ─────────────────────────────────────────────────────────────────────────────
class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    id           = uuid_pk()
    entity_type  = Column(String(30), nullable=False, default="vehicle")  # vehicle / person
    plate_text   = Column(String(20), nullable=False, index=True)
    reason       = Column(String(50), nullable=False, default="wanted")   # stolen/wanted/missing/blacklisted
    severity     = Column(String(20), nullable=False, default="high")     # low/medium/high/critical
    case_ref     = Column(String(100), nullable=True)
    description  = Column(Text, nullable=True)
    added_by     = Column(String(100), nullable=True)
    active       = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    alerts       = relationship("Alert", back_populates="watchlist_entry")


# ─────────────────────────────────────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id                = uuid_pk()
    watchlist_id      = Column(UUID(as_uuid=True), ForeignKey("watchlist.id"), nullable=False)
    detection_id      = Column(UUID(as_uuid=True), ForeignKey("detections.id"), nullable=False)
    matched_at        = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    match_type        = Column(String(20), nullable=False, default="exact")   # exact / fuzzy
    score             = Column(Float, nullable=False, default=1.0)
    status            = Column(String(20), nullable=False, default="new")     # new/ack/resolved
    acknowledged_by   = Column(String(100), nullable=True)
    acknowledged_at   = Column(DateTime(timezone=True), nullable=True)
    notes             = Column(Text, nullable=True)

    watchlist_entry   = relationship("WatchlistEntry", back_populates="alerts")
    detection         = relationship("Detection", back_populates="alert")


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_log"

    id          = uuid_pk()
    actor       = Column(String(200), nullable=False)
    action      = Column(String(100), nullable=False)
    object_type = Column(String(50), nullable=True)
    object_id   = Column(String(100), nullable=True)
    purpose     = Column(String(200), nullable=True)
    case_ref    = Column(String(100), nullable=True)
    details     = Column(JSONB, default={})
    at          = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ─────────────────────────────────────────────────────────────────────────────
# USERS (simple, can be replaced with Supabase Auth)
# ─────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id           = uuid_pk()
    email        = Column(String(255), unique=True, nullable=False, index=True)
    username     = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role         = Column(String(30), nullable=False, default="viewer")  # state_admin/dept_admin/operator/viewer
    department   = Column(String(100), nullable=True)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
