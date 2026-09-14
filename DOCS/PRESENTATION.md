# SENTINEL
### Statewide CCTV Integration Platform & ANPR Surveillance Engine

**Gujarat CCTV Integration Hackathon 2026** | **Category 1 (Academic / Research / Startup)**  
**Team Name**: KodeMatrix | **Track**: Model 1 (Central CCTV Registry & GIS Mapping) + Model 2 (Unified Viewing Platform & ANPR Alerting)

> A production-grade platform running against the live Sentinel sandbox grid: 30 cameras onboarded and mapped, a continuous ANPR pipeline validated at 100% on legible footage, real-time watchlist alerting, and timestamped route reconstruction across cameras.

---

## Slide 2: The Problem and What Wins It

**The Operational Gap in Statewide Surveillance**

- Cameras are owned by multiple departments in diverse formats with no central registry.
- Investigators asking "where has this vehicle been?" have no unified system to query across jurisdictions.
- Watchlist matching, where present, relies on manual human monitoring across isolated displays.

**What Sentinel Delivers**

| Core Capability | Operational Functionality |
|---|---|
| Central Onboarding | Ingests any camera published in the catalogue with location provenance recorded |
| Unified Viewing | Live multi-camera viewing wall without per-department client software |
| Continuous ANPR | Automatic plate indexing: every plate, every camera, every timestamp |
| Watchlist Matching | Instant exact-then-fuzzy trigram matching on every detection |
| Real-Time Alerts | Low-latency WebSocket alert dispatch with watchlist severity levels |
| Route Reconstruction | Interactive map timeline of vehicle sightings with speed estimation |
| Complete Auditability | Purpose-bound audit logging for every citizen search and evidence export |

---

## Slide 3: System Architecture

```
SANDBOX GRID  30 cameras | RTSP/TCP | HLS/WHEP
      │                              │
      │ inference path               │ viewing path
      ▼                              ▼
ANPR WORKER                    REACT + LEAFLET UI
 · TCP transport                · GIS map
 · PTS timing                   · video wall (hls.js)
 · quality gate                 · plate search
 · tiled inference              · live alert panel
 · track voting                 · watchlist
 · plate grammar                       │
      │  detections                    │ REST + WebSocket
      └──────────▶ FASTAPI ◀───────────┘
                     │
                     ▼
        POSTGRESQL 17 + PostGIS + pg_trgm
        cameras · detections · watchlist
        alerts · audit_log · users
```

**Technology Stack:** Python 3.12+ / FastAPI | PostgreSQL 17 + PostGIS + pg_trgm | React + Vite + TypeScript | Leaflet | hls.js | ONNX Runtime (CPU)

**Architectural Discipline:** Kafka, Elasticsearch, and Kubernetes were deliberately omitted at this scale because PostgreSQL handles all indexing cleanly. The scale-out path for 80,000 cameras is fully designed and documented in Section 9 of the HLD.

---

## Slide 4: Model 1 - Registry & GIS Mapping

**Handling Real-World Data Gaps with Integrity**

The sandbox catalogue publishes **only `id` and `name`**: no coordinates, no department, and no codec hints.

**Our Solution**

- Resolved all 30 camera locations from real site names published in the catalogue.
- Implemented strict location provenance precedence: hand-verified → Nominatim geocoding (rate-limited, cached, bounded to Gujarat) → district centroid → **null**.
- Stored `geo_source` and `geo_confidence` on every camera record so provenance travels into reports and UI displays.

**What We Refused To Do**

We did not invent arbitrary coordinates. An initial arithmetic grid approach placed Junagadh cameras in Surat; that was removed. Unlocatable cameras are reported transparently as unlocated.

**GIS Capabilities:** PostGIS geography points, GeoJSON export, department / status / confidence map layers, clustered markers, and click-through to live video tiles.

---

## Slide 5: Model 2 - ANPR & Accuracy Engine

**Local CPU Inference | Zero Third-Party API Dependence**

Pretrained open-source models (YOLOv9-t detector, cct-s-v2 OCR) executing on **local CPU**. No video frame ever leaves the deployment; no external service sits in the alerting path.

**Accuracy Achieved Through Domain-Specific Engineering**

**1. Track-Level Voting**: Vehicles remain visible across 20-60 frames. Every read votes per character weighted by OCR confidence, right-aligned on the 4-digit serial. Tracks reach 20-35 reads and accumulate 1.000 confidence.

**2. Indian Plate Grammar**: `[2 letters][1-2 digits][1-3 letters][4 digits]`. Position rules make O↔0, I↔1, S↔5, B↔8, Z↔2, G↔6 deterministically correctable, with state codes validated against RTO lists.

> **Real Example**: OCR returned `GJO1AB1234`. Position 2 must be a digit, making O unambiguously 0. **7/7** pass rate on correction test suites.

**3. Overlay Rejection**: Detector filters out burnt-in timestamps, PTZ text overlays, and billboard signage before indexing.

**Ground-Truth Benchmark:** **6/6 plates recovered exactly, 0 false positives.**

**Live Sandbox Feed Findings:** 29 of 30 cameras are wide-area PTZ overviews yielding only roadside signage (correctly rejected). **cam12 (Adalaj Toll Naka)** is a toll plaza feed: the pipeline detected a real truck plate **25 times in 100 seconds**, recovering 8 of 10 characters at 5 px/character. Seven preprocessing variants confirmed that upscaling cannot restore detail missing from optics.

> **The constraint is optics, not software** (see Slide 10).

---

## Slide 6: Continuous ANPR Engine & Scalability

**Inference Costs & Siting Realities**

At 1920×1080 resolution, wide-area night feeds render number plates at 5-15 px wide. Full-frame inference at 384 px proposes zero candidates. Tiled inference on overlapping upscaled regions recovers plate regions at 15x CPU cost.

| Benchmark on cam05 (20-core CPU, No GPU) | Full Frame | **Tiled 2x3 @2x** |
|---|---|---|
| Mean Inference Time | 12.3 ms/frame | **185.9 ms/frame** |
| Est. Concurrent Streams per Machine | ≈251 | **≈26** |
| Plate Candidates (90s window) | **0** | **8** |
| Ground-Truth Plates Recovered | 3/6 | **6/6** |

**Analytics Policy Tiers**

ANPR is not a uniform per-camera cost. It is a **policy choice regarding which cameras require analytics**:

| Analytics Tier | Share of Estate | Deployment Workload |
|---|---|---|
| Tier 1: Continuous ANPR | 5-10% | Highways, border posts, ANPR-sited toll plazas |
| Tier 2: Event-Triggered | 20-30% | Urban junctions (motion / signal triggered) |
| Tier 3: Registry & View | 60-75% | Full video coverage without analytics compute cost |

---

## Slide 7: Correlation, Alerting & Route Reconstruction

**Watchlist Matching: Exact + Fuzzy Trigram Search**

Every detection is matched against active watchlists before database transaction commit: exact match first, followed by `pg_trgm` trigram similarity > 0.7. Matches generate instant WebSocket alerts with severity metadata.

```sql
SELECT *, similarity(plate_text, :q) AS score
FROM detections WHERE plate_text % :q
ORDER BY score DESC, detected_at;
```

> **Why Fuzzy Search is Critical**: ANPR OCR will occasionally misread a character. Exact-only matching misses genuine detections. Verified: searching `GJO1AB1234` correctly retrieves records stored as `GJ01AB1234`.

**Route Reconstruction**

Sightings ordered chronologically → great-circle distance & elapsed time calculated → implied speed estimated → **physically impossible transitions (>150 km/h) flagged** and surfaced to operators rather than hidden.

Flagged transitions notify investigators of potential plate misreads or cloned registration plates, providing actionable intelligence.

---

## Slide 8: Security, Privacy & Accountability

| Security Control | Technical Implementation |
|---|---|
| Access Control | JWT authentication with 3 roles **enforced per API endpoint** |
| Audit Trail | Actor identity extracted from **verified token** with recorded purpose and case reference |
| Data Minimisation | Stores plate text, timestamp, camera, and plate crop (no raw video retention) |
| Data Residency | 100% local inference: zero frames or crops leave local infrastructure |
| Credential Safety | Environment-based configuration, masked in logs, **never sent to browser** |
| Web Security | CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff, HSTS |
| Rate Limiting | 10 req/min on authentication, 300 req/min general (video streams exempt) |
| DPDP Act 2023 | Purpose-bound queries, role restrictions, and auditability |

> **Verified Enforcement**: A viewer token receives **403 Forbidden** on audit trail and plate search routes, and **200 OK** on the camera registry.

**Closed Government Systems (VAHAN, SARTHI, eGujCop)**

Sentinel implements a contract-first adapter pattern. We defined request/response models, built mock adapters with realistic records, and documented exact activation steps when production credentials arrive (base URL, authentication, rate limits, audit hooks).

---

## Slide 9: Scaling to 80,000 Cameras

**Empirical Sandbox Ingestion Bottleneck Benchmark**

Opening N concurrent RTSP streams to the sandbox gateway:

| Concurrent Streams | Succeeded | Wall Time | **Our Server CPU** (20 Cores) |
|---|---|---|---|
| 2 | 2 / 2 | 12 s | **4%** |
| 4 | 4 / 4 | 26 s | **4%** |
| 6 | 6 / 6 | 41 s | **5%** |
| 8 | 7 / 8 | 88 s | **4%** |

Connection accept times for 8 streams: 4s, 8s, 27s, 33s, 56s, 60s, 63s, 73s (gateway queue buildup).

> **Key Insight**: Our processing server remained idle at 4% CPU while the single gateway took 73s to accept 8 connections. Centralized single-ingress ingestion is the primary bottleneck.

**Statewide Edge-First Architecture**

```
camera → DISTRICT EDGE → REGIONAL DC → STATE CORE
         record             aggregate     registry
         transcode          regional      statewide search
         ANPR inference     search        cross-region routes
         alert generation   warm storage  dashboards, audit
               ↓                 ↓              ↓
        only metadata,    metadata      metadata only
        alerts, requested  + clips
        clips go upstream
```

Restricting WAN backhaul to metadata, alerts, and requested video clips reduces wide-area bandwidth demand by **2 to 3 orders of magnitude** (from 192 Gbps down to 8.7 Mbps).

---

## Slide 10: Platform Capabilities & Transparent Evaluation

**Fully Demonstrated Capabilities**

✓ 30 sandbox cameras onboarded with full location provenance  
✓ Interactive GIS map with department, status, and confidence filters  
✓ Unified video wall featuring HLS grid and WebRTC hero tiles  
✓ Continuous ANPR pipeline with tiled inference, track voting, and grammar correction  
✓ Exact, partial, and fuzzy plate search  
✓ Automatic watchlist matching with real-time WebSocket alerts  
✓ Route reconstruction with speed calculation and impossible transition flagging  
✓ Output report generation in XLSX and PDF formats  
✓ Purpose-bound audit trail logging  
✓ 57 automated unit/integration tests with 100% accuracy on legible ground-truth feeds  

**Transparent Limitations**

- **Live Sandbox Feed Yield**: 29 of 30 cameras are wide-area PTZ overviews where plates measure 5-15 px (below optical resolution thresholds). cam12 (toll plaza) yielded 25 detections of a real truck plate at 5 px/character. Recommendation: prioritize toll plazas and checkposts equipped with lane-facing optics.
- **Geocoded Locations**: Camera coordinates are geocoded from site names, accurate to the facility rather than exact pole markers.
- **Single-Node Deployment**: Prototype runs as a unified single-node deployment; scale-out topology is documented in HLD Section 9.

---

## Slide 11: Impact on Policing & Strategic Roadmap

**Operational Transformation**

- **Traditional Workflow**: Investigators manually contact multiple departments, scrub hours of footage, and assemble timelines over several days.
- **Sentinel Workflow**: Enter a vehicle registration once. Every sighting across all connected cameras appears on an interactive map within seconds.

| Platform Capability | Operational Benefit |
|---|---|
| Continuous Indexing | Vehicle timelines exist prior to search queries |
| Automated Watchlist Alerts | Instant notifications when wanted vehicles pass cameras |
| Fuzzy Plate Matching | Misread characters do not prevent vehicle identification |
| Unified Camera Registry | Single access portal across departmental boundaries |
| Audited Access Control | Surveillance capabilities with complete accountability |

**Strategic Roadmap**

1. **Phase 1**: Pilot deployment across 1 district (50-200 cameras) at toll plazas and checkposts.
2. **Phase 2**: Multi-VMS adapter rollout across urban junctions (Model 3 integration).
3. **Phase 3**: Live VAHAN API credential activation and edge node expansion.
4. **Phase 4**: Statewide edge node deployment across 80,000 cameras (Model 4 scale-out).

---

## Slide 12: Verification & Reproducibility

| Claim / Benchmark | Verification Command / URL |
|---|---|
| ANPR Throughput Benchmark | `python anpr_worker.py --benchmark` |
| Ground-Truth 6/6 Accuracy Test | `python tools/make_sample_feed.py --validate` |
| Grammar & System Test Suite | `python -m pytest tests/ -q` (57 tests passing) |
| Ingest & Provenance Endpoint | `GET /api/v1/ingest/status` |
| Audit Trail API | `GET /api/v1/analytics/audit` |
| Interactive OpenAPI Docs | `http://localhost:8000/api/docs` |

**Team**: KodeMatrix  
**Repository**: `https://github.com/DevamShah1211/Sentinel-Hackathone`  
**Video Evidence**: Google Drive Folder & `DOCS/evidence/Sentinel Video/`  
**Hosted Prototype**: `http://localhost:8000` (Backend) | `http://localhost:5173` (Frontend)

Every measurement in this presentation is fully reproducible via scripts in `DOCS/MEASUREMENTS.md`.
