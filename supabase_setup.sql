-- ═══════════════════════════════════════════════════════════════════════
-- Sentinel CCTV Platform — Supabase SQL Setup
-- Run this ONCE in Supabase SQL Editor: Dashboard → SQL Editor → + New Query
-- ═══════════════════════════════════════════════════════════════════════

-- 1. Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy plate search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. cameras table (Model 1 — Registry + Model 2 — Viewing)
CREATE TABLE IF NOT EXISTS cameras (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    native_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    department      TEXT NOT NULL DEFAULT 'Unknown',
    location        geography(POINT, 4326),
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    address         TEXT,
    rtsp_url        TEXT,
    hls_url         TEXT,
    whep_url        TEXT,
    codec           TEXT,
    resolution      TEXT,
    fps             DOUBLE PRECISION,
    bitrate_kbps    INTEGER,
    status          TEXT NOT NULL DEFAULT 'unknown',
    is_live         BOOLEAN DEFAULT TRUE,
    last_seen_at    TIMESTAMPTZ,
    camera_type     TEXT,
    make            TEXT,
    model           TEXT,
    installation_date TIMESTAMPTZ,
    connectivity    TEXT,
    ownership       TEXT,
    extra           JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cameras_native_id  ON cameras(native_id);
CREATE INDEX IF NOT EXISTS idx_cameras_department ON cameras(department);
CREATE INDEX IF NOT EXISTS idx_cameras_is_live    ON cameras(is_live);
CREATE INDEX IF NOT EXISTS idx_cameras_location   ON cameras USING GIST(location);

-- 3. detections table (ANPR output index)
CREATE TABLE IF NOT EXISTS detections (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id    UUID NOT NULL REFERENCES cameras(id),
    plate_text   TEXT NOT NULL,
    confidence   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pts_ms       BIGINT,
    detected_at  TIMESTAMPTZ DEFAULT NOW(),
    track_id     TEXT,
    crop_uri     TEXT,
    vehicle_type TEXT,
    raw_reads    JSONB DEFAULT '[]',
    bbox         JSONB
);

CREATE INDEX IF NOT EXISTS idx_detections_camera_id   ON detections(camera_id);
CREATE INDEX IF NOT EXISTS idx_detections_plate_text  ON detections(plate_text);
CREATE INDEX IF NOT EXISTS idx_detections_detected_at ON detections(detected_at DESC);
-- pg_trgm index for fuzzy plate search
CREATE INDEX IF NOT EXISTS idx_detections_plate_trgm  ON detections USING GIN(plate_text gin_trgm_ops);

-- 4. watchlist table
CREATE TABLE IF NOT EXISTS watchlist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL DEFAULT 'vehicle',
    plate_text  TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT 'wanted',
    severity    TEXT NOT NULL DEFAULT 'high',
    case_ref    TEXT,
    description TEXT,
    added_by    TEXT,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_plate_text ON watchlist(plate_text);
CREATE INDEX IF NOT EXISTS idx_watchlist_active     ON watchlist(active);
CREATE INDEX IF NOT EXISTS idx_watchlist_plate_trgm ON watchlist USING GIN(plate_text gin_trgm_ops);

-- 5. alerts table
CREATE TABLE IF NOT EXISTS alerts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    watchlist_id     UUID NOT NULL REFERENCES watchlist(id),
    detection_id     UUID NOT NULL REFERENCES detections(id),
    matched_at       TIMESTAMPTZ DEFAULT NOW(),
    match_type       TEXT NOT NULL DEFAULT 'exact',
    score            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    status           TEXT NOT NULL DEFAULT 'new',
    acknowledged_by  TEXT,
    acknowledged_at  TIMESTAMPTZ,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_matched_at  ON alerts(matched_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status      ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_watchlist_id ON alerts(watchlist_id);

-- 6. audit_log table
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    object_type TEXT,
    object_id   TEXT,
    purpose     TEXT,
    case_ref    TEXT,
    details     JSONB DEFAULT '{}',
    at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_at ON audit_log(at DESC);

-- 7. users table
CREATE TABLE IF NOT EXISTS users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email            TEXT UNIQUE NOT NULL,
    username         TEXT UNIQUE NOT NULL,
    hashed_password  TEXT NOT NULL,
    role             TEXT NOT NULL DEFAULT 'viewer',
    department       TEXT,
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ── Seed data (optional) ────────────────────────────────────────────────────
-- Insert a default admin user (password: sentinel123 — change immediately!)
-- bcrypt hash of "sentinel123":
INSERT INTO users (email, username, hashed_password, role)
VALUES (
  'admin@sentinel.gov.in',
  'admin',
  '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
  'state_admin'
) ON CONFLICT (email) DO NOTHING;

-- ── Helpful views ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW camera_summary AS
SELECT
    department,
    COUNT(*) AS total,
    SUM(CASE WHEN is_live THEN 1 ELSE 0 END) AS live,
    SUM(CASE WHEN NOT is_live THEN 1 ELSE 0 END) AS offline
FROM cameras
GROUP BY department
ORDER BY total DESC;

CREATE OR REPLACE VIEW recent_alerts AS
SELECT
    a.id, a.matched_at, a.match_type, a.score, a.status,
    w.plate_text, w.reason, w.severity, w.case_ref,
    d.detected_at, d.crop_uri,
    c.name AS camera_name, c.department, c.lat, c.lon
FROM alerts a
JOIN watchlist w ON a.watchlist_id = w.id
JOIN detections d ON a.detection_id = d.id
JOIN cameras c ON d.camera_id = c.id
ORDER BY a.matched_at DESC;

-- Done! ✅
-- Next step: update .env with your Supabase DATABASE_URL and run:
--   uvicorn main:app --reload
