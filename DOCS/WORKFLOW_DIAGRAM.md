# SENTINEL
## Technical Workflow & Integration Diagram Specification

**Gujarat CCTV Integration Hackathon 2026** | **Category 1 (Academic / Research / Startup)**  
**Document**: Workflow & Integration Diagram Specification  
**Project**: Sentinel: Statewide CCTV Integration & ANPR Surveillance Engine  
**Repository**: [DevamShah1211/Sentinel-Hackathone](https://github.com/DevamShah1211/Sentinel-Hackathone)

---

## 1. Executive Summary

Sentinel is designed as a modular, edge-first statewide CCTV integration platform that ingests camera streams from heterogeneous departmental network feeds, performs continuous local license plate recognition (ANPR), correlates detections against real-time enforcement watchlists, dispatches low-latency WebSocket notifications, and reconstructs vehicle travel corridors on GIS maps with comprehensive audit logging.

This document details the operational workflow, end-to-end data pipelines, microservice integration points, database schemas, and edge-to-cloud scalability topology.

---

## 2. End-to-End Operational Workflow Diagram

The sequence below illustrates how a live RTSP feed is ingested, processed, matched against enforcement watchlists, and surfaced to operators:

```
[ CAMERA ESTATE ]
 30 Sandbox RTSP Feeds (H.264/H.265)
        │
        ▼ (RTSP over TCP)
[ 1. CAPTURE & QUALITY GATE ]
 ├── OpenCV FFmpeg StreamCapture
 ├── Presentation Timestamp (PTS) Sync
 ├── Settling Window Gating (IDR Frames)
 └── Corrupt / Low-Luminance Frame Rejection
        │
        ▼ (Raw Video Frame 1920x1080)
[ 2. TILED INFERENCE & ANPR PIPELINE ]
 ├── Tiled Upscaling (2×3 Overlapping Grid @ 2×)
 ├── YOLOv9-t End-to-End Plate Detector
 ├── Bounding Box Remapping to Full Frame
 └── Fast-ALPR CCT-S-v2 Global OCR (10 Character Slots)
        │
        ▼ (Per-Frame Plate Candidates)
[ 3. NOISE REJECTION & TRACK VOTING ]
 ├── Camera Overlay Text Rejection (Timestamps, PTZ Labels, Billboards)
 ├── IoU Spatial-Temporal Track Association (20-60 Frames per Vehicle)
 ├── Character-Level Confidence-Weighted Voting (Right-Aligned Serial)
 └── Indian Plate Grammar Correction (O↔0, I↔1, S↔5, B↔8, Z↔2, G↔6)
        │
        ▼ (Validated Voted Plate Detection)
[ 4. FASTAPI INGEST & DB COMMIT ]
 ├── REST POST /api/v1/detections (Camera ID, Plate Text, Crop URI, PTS)
 ├── PostgreSQL 17 + PostGIS + pg_trgm Transaction Commit
 └── Evidence Crop Saved to Local Storage (`/static/crops/`)
        │
        ▼ (Synchronous Pre-Commit Trigger)
[ 5. WATCHLIST CORRELATION & ALERTING ]
 ├── Exact String Match Check (Score: 1.0)
 ├── Trigram Fuzzy Match Check (`pg_trgm` Similarity > 0.7)
 ├── Alert Row Created (`status = new`, Severity: Critical/High/Med)
 └── WebSocket Manager Fan-out (`ws://.../ws/alerts`)
        │
        ▼ (Live Alert Notification)
[ 6. OPERATOR UI & WORKFLOW ACTION ]
 ├── React + Leaflet Live Map Toast & Audio Alert
 ├── Video Wall Tile Highlight (HLS Grid + Hero WebRTC)
 ├── Operator Acknowledgment (`status = ack`, Stated Purpose)
 └── VAHAN Registry Enrichment (Owner, Make, Model, Fuel Type)
        │
        ▼ (Investigation & Reporting)
[ 7. ROUTE RECONSTRUCTION & AUDIT ]
 ├── Chronological Sighting Query & GIS Point Ordering
 ├── Great-Circle Distance, Time & Implied Speed Calculation
 ├── Speed Violation Flagging (>150 km/h Impossible Transition Flag)
 ├── Purpose-Bound Audit Logging (`audit_log` Table)
 └── Excel (.xlsx) & PDF Output Evidence Report Export
```

---

## 3. Microservice & System Integration Topology

Sentinel separates video ingestion and compute-heavy inference from the API web backend and frontend UI layer:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            HETEROGENEOUS CAMERA ESTATE                      │
│   RTSP/RTSPS Direct   ·   HLS / WebRTC Gateways   ·   ONVIF Profiles S/T    │
└───────────────────────┬─────────────────────────────┬───────────────────────┘
                        │ Ingestion Path              │ Viewing Path
                        ▼                             ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────┐
│       ANPR INFERENCE WORKER          │  │       WEB FRONTEND DASHBOARD      │
│         (`anpr_worker.py`)           │  │      (React 18 + Vite + TS)       │
│                                      │  │                                   │
│  • OpenCV RTSP Stream Processor      │  │  • Leaflet Interactive GIS Map    │
│  • Frame Quality & Luminance Gate    │  │  • Multi-Tile Video Wall (hls.js) │
│  • YOLOv9-t Tiled Object Detector    │  │  • Real-Time Alert Panel (WS)     │
│  • ONNX Runtime CPU OCR Engine       │  │  • Plate Search & Fuzzy Lookup    │
│  • Track Voting & Grammar Validator  │  │  • Route Timeline & Speed Graph   │
└──────────────────┬───────────────────┘  └─────────────────┬─────────────────┘
                   │                                        │
                   │ POST /api/v1/detections                │ REST APIs + WebSockets
                   ▼                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FASTAPI BACKEND ENGINE                           │
│                                (`run_server.py`)                            │
│                                                                             │
│   /cameras      /detections      /watchlist      /alerts      /analytics    │
│   /ingest       /audit           /auth           /vahan       /ws/alerts    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ PostgreSQL / PostGIS Driver
┌─────────────────────────────────────────────────────────────────────────────┐
│                     POSTGRESQL 17 + POSTGIS + PG_TRGM                       │
│                                                                             │
│   • `cameras`: Geographic points (GIST spatial index), metadata, provenance │
│   • `detections`: Voted plate reads, crops, confidence, trigram index (GIN) │
│   • `watchlist`: Hotlist plates, severity, case references, active status   │
│   • `alerts`: Active notifications, match type (exact/fuzzy), state tracking│
│   • `audit_log`: Purpose-bound tracking of all queries, searches & exports  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Watchlist Correlation & Alert Workflow

The diagram below details the exact decision tree executed whenever a number plate is indexed:

```
                  [ Voted Plate Detection ]
                             │
                             ▼
              Exact Match Check on Watchlist?
                             │
                  ┌──────────┴──────────┐
                 YES                    NO
                  │                     │
                  ▼                     ▼
           [ Exact Match ]    `pg_trgm` Trigram Similarity > 0.7?
           • Score = 1.0                │
           • Type = `exact`     ┌───────┴───────┐
                  │            YES              NO
                  │             │               │
                  │             ▼               ▼
                  │       [ Fuzzy Match ]  [ Standard Index ]
                  │       • Score > 0.7    • No Alert
                  │       • Type = `fuzzy` • Saved to `detections`
                  │             │               │
                  └─────────────┬───────────────┘
                                │
                                ▼
                   [ Create Alert Entry ]
                   • Status = `new`
                   • Severity = Watchlist Priority
                   • Case Reference Attached
                                │
                                ▼
                 [ Real-Time WebSocket Push ]
                 • Dispatch JSON Payload to `/ws/alerts`
                 • Trigger UI Audio Alert & Map Flash
                                │
                                ▼
                  [ Operator Acknowledgment ]
                  • Status = `ack` / `resolved`
                  • Logged to Audit Trail with Purpose
```

---

## 5. Statewide Edge-First Deployment Topology (Scale to 80,000 Cameras)

To prevent centralized network backhaul saturation (192 Gbps raw video bottleneck), Sentinel utilizes an **edge-first architecture**:

```
[ DISTRICT EDGE NODE ]  ──(Metadata & Alerts Only)──▶ [ REGIONAL DC ] ──▶ [ STATE CORE ]
 • 50-200 Local Cameras                                • Aggregated Search   • Central Registry
 • Full Video Recording & Storage                     • Regional Storage    • Statewide Analytics
 • Local ANPR Inference & Quality Gate                                      • Master Audit Log
 • Instant Local Alert Generation                     8.7 Mbps WAN Link     • High-Level Map
 (360 Gbps Reduced to 8.7 Mbps)                      (vs 360 Gbps Direct)
```

---

## 6. Integration Contract Interfaces

### 6.1 VAHAN Vehicle Registry Adapter Interface
- **Endpoint**: `GET /api/v1/vahan/vehicle/{plate_number}`
- **Mock / Integration Adapter**: Contract-first architecture returning registration date, owner name, vehicle class, fuel type, engine number, and insurance validity.

### 6.2 Audit Trail Verification Interface
- **Endpoint**: `GET /api/v1/analytics/audit`
- **Enforcement**: Logs user ID, role, client IP, action type (`SEARCH`, `ROUTE_RECONSTRUCT`, `EXPORT`), timestamp, and explicit **stated legal purpose**.

---

*Generated for Gujarat CCTV Integration Hackathon 2026 submission package.*
