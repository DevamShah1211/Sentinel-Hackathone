# Sentinel — Statewide CCTV Integration Platform

**Gujarat CCTV Integration Hackathon 2026 · Category 1**
Model 1 (Central CCTV Registry & GIS Mapping) + Model 2 (Unified Viewing Platform with ANPR & Watchlist Alerting)

A working platform running against the live Sentinel sandbox grid: 30 cameras
onboarded and mapped, continuous number-plate indexing from live RTSP feeds,
automatic watchlist matching with real-time alerts, vehicle route reconstruction
across cameras, and an audited output report.

---

## Submission links

| Artefact | Link |
|---|---|
| Own-feed demo video (2–3 min) | _add before submitting_ |
| Government-feed demo video | _add before submitting_ |
| Output report (XLSX + PDF) | _add before submitting_ |
| Solution presentation (PDF) | `DOCS/PRESENTATION.md` → export |
| Technical proposal / HLD (PDF) | `DOCS/HLD.md` → export |
| Hosted instance | _add before submitting_ |
| Repository | https://github.com/DevamShah1211/Sentinel-Hackathone |

---

## What it does

| | |
|---|---|
| **Onboards** | Reads the sandbox catalogue, resolves each camera's location, records how that location was derived |
| **Maps** | Leaflet GIS map with department, status and location-confidence layers; PostGIS geography points, GeoJSON export |
| **Watches** | Unified video wall — 3×3 / 2×2 / 1×1, native HLS playback through an authenticated proxy |
| **Reads** | Continuous ANPR on live feeds with tiled inference, track-level voting and Indian plate-grammar correction |
| **Searches** | Detection index by exact, partial and trigram-fuzzy plate |
| **Correlates** | Watchlist matching — exact then fuzzy — on every detection, with bulk CSV import |
| **Alerts** | Real-time WebSocket alerts carrying reason and severity, with acknowledge/resolve workflow |
| **Reconstructs** | Timestamped route across cameras, with speed and physically-impossible-transition flagging |
| **Reports** | Output report as XLSX and PDF, generated from the index |
| **Accounts** | Every search, route reconstruction and export audited with a stated purpose and case reference |

---

## Quick start

**Prerequisites:** Python 3.11+ (3.14 works), Node 18+, and PostgreSQL 16+ with
PostGIS. No GPU is required — all inference runs on CPU.

```bash
# 1 · Database
docker run -d --name sentinel-db -p 5432:5432 \
  -e POSTGRES_PASSWORD=sentinel postgis/postgis:16-3.4
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 2 · Backend
cd backend
pip install -r requirements.txt
cp .env.example .env        # set DATABASE_URL and your sandbox credentials
python run_server.py        # API on :8000 · OpenAPI docs at /api/docs

# 3 · Frontend
cd frontend
npm install
npm run dev                 # UI on :5173

# 4 · ANPR indexer — start it early and leave it running
cd backend
python anpr_worker.py --max-streams 6
```

The camera registry populates itself from the sandbox catalogue on first start.

### Configuration

`backend/.env` — see `.env.example` for the full list:

```ini
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/sentinel
SENTINEL_USER_EMAIL=your-registered-email
SENTINEL_USER_PASSWORD=your-sandbox-password
SECRET_KEY=change-me
```

Sandbox credentials are read from the environment, used only server-side, and
masked in logs. They are never sent to the browser.

---

## Why the indexer should run continuously

The grid replays roughly twelve hours of footage per camera on a loop. An indexer
started early has already seen every plate at every camera by the time it is
needed, so a route renders instantly from the index instead of being processed
live. It is also what the brief asks for — a solution that *continuously processes
the CCTV feeds*.

```bash
# Detached, survives terminal closure (Windows)
powershell -File backend/tools/run_indexer.ps1 -MaxStreams 8
powershell -File backend/tools/run_indexer.ps1 -Stop
```

---

## Verify the claims

Everything below is reproducible on the project hardware.

```bash
cd backend

# Measured ANPR throughput, tiled and full-frame
python anpr_worker.py --benchmark --duration 90
python anpr_worker.py --benchmark --duration 90 --no-tiling

# End-to-end pipeline accuracy against known ground truth
python tools/make_sample_feed.py --validate     # → 6/6 plates, 0 false positives

# Unit tests — plate grammar, vision, VAHAN adapter
python -m pytest tests/ -q                      # → 57 passed
```

Measured on a 20-core CPU with no GPU:

| | Full frame | Tiled 2×3 @2× |
|---|---|---|
| Mean inference | 12.3 ms/frame | 185.9 ms/frame |
| Est. concurrent streams per machine | ≈251 | ≈26 |
| Plate reads in a 90 s window on cam05 | **0** | **8** |

Full detail, including why tiling is necessary on this grid, is in
[`DOCS/MEASUREMENTS.md`](DOCS/MEASUREMENTS.md).

---

## How the ANPR works

**No model was trained, and no external ANPR API is used.** Pretrained
open-source models run locally: a YOLOv9-t plate detector and the `cct-s-v2`
OCR. No video frame leaves the deployment, and no third-party service sits in the
alerting path — which is the only defensible arrangement for government CCTV.

Accuracy comes from three cheap steps rather than a bigger model:

1. **Tiled inference.** These cameras are wide-area PTZ overviews where a plate is
   10–20 px wide. Full-frame inference at 384 px finds nothing; overlapping
   upscaled tiles find real plates.
2. **Track-level voting.** A vehicle is visible for 20–60 frames. Every read votes
   per character, weighted by the OCR's own per-character confidence, right-aligned
   on the four-digit serial.
3. **Indian plate grammar.** `[2 letters][1–2 digits][1–3 letters][4 digits]`, so
   O↔0, I↔1, S↔5, B↔8, Z↔2 and G↔6 are deterministically correctable and the state
   code is validated against the RTO list.

Camera overlay text (burnt-in timestamps, `CSITMS-31`, `PTZ` labels) is rejected
before it can enter the index.

---

## Project layout

```
backend/
  anpr_worker.py           continuous ANPR indexer (also --benchmark)
  app/
    vision.py              capture, frame gating, tiled inference, tracking
    plate_grammar.py       Indian plate correction and per-character voting
    geocoding.py           camera location resolution with provenance
    sandbox_client.py      authenticated catalogue fetch
    reporting.py           XLSX + PDF output report
    audit.py               audit trail
    adapters/vahan.py      contract-first VAHAN adapter (mock-backed)
    routers/               cameras · detections · watchlist · alerts · analytics · ingest · auth
  tools/
    make_sample_feed.py    ground-truth clip + pipeline validation
    run_indexer.ps1        detached indexer control
  tests/                   57 tests
frontend/src/pages/        Map · VideoWall · Search · Alerts · Watchlist · Dashboard
DOCS/
  HLD.md                   technical proposal / high-level design
  PRESENTATION.md          solution presentation content
  MEASUREMENTS.md          every performance number, with the command that produces it
catalogue.json             camera catalogue as published by the sandbox
```

---

## Key API endpoints

Full interactive documentation at `http://localhost:8000/api/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/cameras` · `/geojson` | Camera registry, with location provenance |
| `GET /api/v1/cameras/proxy-hls/{cam}/{file}` | Authenticated HLS proxy — keeps credentials server-side |
| `GET /api/v1/detections?plate=&fuzzy=true` | Plate search — exact, partial, fuzzy |
| `GET /api/v1/detections/route/{plate}` | Route reconstruction with speed and flagged transitions |
| `POST /api/v1/watchlist` · `/bulk-import` | Watchlist management |
| `GET /api/v1/alerts` | Alerts, with acknowledge and resolve |
| `WS /ws/alerts` | Live alert stream |
| `GET /api/v1/analytics/report/xlsx` · `/pdf` | Output report |
| `GET /api/v1/analytics/vehicle/{plate}` | VAHAN vehicle particulars (mock-backed) |
| `GET /api/v1/analytics/audit` | Audit trail |

---

## Known limitations

Stated deliberately — see [`DOCS/HLD.md`](DOCS/HLD.md) §12 for the full list.

- **ANPR yield on the sandbox grid is low.** These are wide-area night-time PTZ
  overviews where plates are frequently a handful of pixels. This is a property of
  camera siting, not of the pipeline, and would improve markedly on cameras sited
  for ANPR.
- **Camera coordinates are geocoded, not surveyed** — accurate to the named site,
  not to the pole. Every camera records `geo_source` and `geo_confidence`.
- **Department attribution is inferred** from the site type in the camera name and
  is labelled as inferred wherever shown.
- **The route is a sequence of point sightings.** The road-snapped line is an
  interpolation returned separately, never presented as evidence.
- **VAHAN integration is contract-first and mock-backed.** Every response says
  `source: "mock"` and `is_authoritative: false`.
- **Single-node prototype** — no HA or DR. The scale-out path is designed in the
  HLD, not implemented.

---

## Documentation

- [`DOCS/HLD.md`](DOCS/HLD.md) — technical proposal: architecture, integration,
  analytics, scaling arithmetic, security, limitations
- [`DOCS/PRESENTATION.md`](DOCS/PRESENTATION.md) — solution presentation content
- [`DOCS/MEASUREMENTS.md`](DOCS/MEASUREMENTS.md) — every measured number and how to
  reproduce it
- [`DOCS/Sentinel-Sprint-Playbook.md`](DOCS/Sentinel-Sprint-Playbook.md) — the sprint plan
- [`DOCS/statewide-cctv-technical-document.md`](DOCS/statewide-cctv-technical-document.md) — companion Tech Doc
