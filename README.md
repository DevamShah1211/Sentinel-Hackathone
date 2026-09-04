# 🛡️ Sentinel CCTV Platform

**Gujarat CCTV Integration Hackathon 2026 — Category 1**  
**Model 1** (Camera Registry & GIS Mapping) + **Model 2** (Unified Viewing Platform + ANPR)

---

## Architecture

```
┌─────────────────────────┐    ┌──────────────────────────────────┐
│   React + Vite Frontend │◄──►│   FastAPI Backend (Python 3.12)  │
│  Leaflet · hls.js       │    │   SQLAlchemy async · WebSocket    │
└─────────────────────────┘    └──────────────┬───────────────────┘
                                              │
                        ┌─────────────────────┼──────────────────────┐
                        │                     │                      │
              ┌─────────▼──────┐  ┌──────────▼──────┐  ┌───────────▼──────┐
              │ Supabase       │  │ Sentinel Sandbox │  │ ANPR Worker      │
              │ PostgreSQL +   │  │ /api/ingest      │  │ OpenCV + RTSP    │
              │ PostGIS +      │  │ HLS / WebRTC     │  │ fast-alpr        │
              │ pg_trgm        │  │ RTSP/TCP streams │  │ Track voting     │
              └────────────────┘  └─────────────────┘  └──────────────────┘
```

## Features

| Feature | Status |
|---|---|
| 📷 Camera registry from Sentinel catalogue | ✅ |
| 🗺️ GIS map — dept/status/codec layers | ✅ |
| 📺 Live HLS video wall (3×3 grid) | ✅ |
| 🎯 ANPR with Indian plate grammar correction | ✅ |
| 🗳️ Track-level confidence-weighted voting | ✅ |
| 🔍 Plate search — exact / partial / fuzzy (pg_trgm) | ✅ |
| 🚨 Watchlist matching + real-time WebSocket alerts | ✅ |
| 🗺️ Route reconstruction with speed & impossibility flags | ✅ |
| 📊 XLSX output report (required artefact) | ✅ |
| 🔒 Audit log + role model | ✅ |
| 📡 Reconnect with exponential backoff (2s→30s) | ✅ |
| ⏱️ PTS-based timing (never wall-clock) | ✅ |

---

## Quick Start

### 1. Supabase Setup
1. Create a project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → paste and run `supabase_setup.sql`
3. Get your connection string from **Settings → Database**

### 2. Backend

```bash
cd backend
cp .env.example .env
# Fill in DATABASE_URL, SUPABASE_URL, SUPABASE_KEY, SENTINEL_HOST

pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs at: http://localhost:8000/api/docs

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at: http://localhost:5173

### 4. ANPR Worker

```bash
cd backend
# Make sure backend is running first!
python anpr_worker.py --max-streams 10

# Or a single camera:
python anpr_worker.py --camera-id <UUID> --rtsp-url rtsp://<host>:8554/stream/1
```

---

## Stream Connection (Playbook §A rules)

| Rule | Implementation |
|---|---|
| TCP transport | `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp` |
| PTS timing | `cap.get(cv2.CAP_PROP_POS_MSEC)` — never `time.time()` |
| Exponential backoff | 2s → 4s → 8s → ... → 30s |
| Decoder warnings not fatal | `try/except` around ANPR, log only |
| No fixed frame rate | PTS delta used for all timing |
| Scene discontinuity | Tracker state flushed on reconnect |

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/v1/cameras/geojson` | GeoJSON for map |
| `GET /api/v1/cameras/stats` | Department-wise stats |
| `POST /api/v1/ingest/sync` | Sync from Sentinel catalogue |
| `GET /api/v1/detections?plate=GJ01AB...&fuzzy=true` | Plate search |
| `GET /api/v1/detections/route/{plate}` | Route reconstruction |
| `GET /api/v1/watchlist` | List watchlist |
| `POST /api/v1/watchlist` | Add entry |
| `POST /api/v1/watchlist/bulk-import` | CSV bulk import |
| `GET /api/v1/alerts` | Alert list |
| `PATCH /api/v1/alerts/{id}/acknowledge` | Acknowledge alert |
| `GET /api/v1/analytics/summary` | Dashboard stats |
| `GET /api/v1/analytics/report/xlsx` | Download output report |
| `WS /ws/alerts` | Real-time alert stream |

---

## Submission Checklist (from Playbook §6)

- [ ] Solution Presentation (PPT/PDF)
- [ ] HLD document
- [ ] Own-feed demo video (2–3 min)
- [ ] Government-feed demo video + output report
- [ ] All links verified in incognito window
- [ ] Platform deployed and accessible
- [ ] Repository README explains how to run it

---

## Tech Stack

- **Backend**: Python 3.12 · FastAPI · SQLAlchemy 2 · GeoAlchemy2
- **Database**: Supabase Postgres 16 + PostGIS 3 + pg_trgm
- **Frontend**: React 18 · TypeScript · Vite · Leaflet · hls.js
- **ANPR**: fast-alpr (ONNX) + OpenCV · Track-level voting · Indian plate grammar
- **Streams**: RTSP/TCP → HLS (hls.js) + WebRTC/WHEP

---

*Prepared: September 2026 · Gujarat CCTV Integration Hackathon · Category 1*
