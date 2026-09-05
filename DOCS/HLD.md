# Sentinel — High-Level Design

**Statewide CCTV Integration Platform · Model 1 + Model 2**
Gujarat CCTV Integration Hackathon 2026 · Category 1 (Academic / Research / Startup)

| | |
|---|---|
| Document | Technical Proposal / High-Level Design |
| Scope | Model 1 — Central CCTV Registry & GIS Mapping (compulsory)<br>Model 2 — Unified Viewing Platform with ANPR & Watchlist Alerting |
| Prototype status | Running against the live Sentinel sandbox grid (30 cameras) |
| Companion | *Statewide CCTV Integration Programme — Technical Solution Document v1.0* ("the Tech Doc") |
| Measurements | All figures quoted here are reproduced in `DOCS/MEASUREMENTS.md` |

---

## 1. What we built, and what we did not

Sentinel is a working platform, not a mock-up. It onboards cameras from the
sandbox catalogue, plots them on a GIS map, streams them in a unified viewer,
continuously reads number plates from live feeds, matches them against a
watchlist, raises alerts in real time, reconstructs a vehicle's route across
cameras, and exports the output report.

We are equally explicit about what is **described rather than demonstrated**.
Section 9 sets out the scale-out path to 80,000 cameras; that section is a design
argument supported by arithmetic, not a claim about running code. The distinction
matters more than any individual feature, because a submission that blurs it
cannot be trusted on the parts that *are* real.

### 1.1 Demonstrated in the prototype

- Camera registry populated from the live sandbox catalogue, with location
  provenance recorded per camera
- GIS map with department, status and location-confidence layers
- Multi-camera live viewing (HLS grid, WebRTC hero tile)
- Continuous ANPR pipeline on a subset of cameras — tiled inference, track-level
  voting and Indian plate-grammar correction (yield on this grid: see §6.5)
- Detection index searchable by exact, partial and trigram-fuzzy plate
- Watchlist with bulk import; automatic exact-then-fuzzy matching
- Real-time alerts pushed over WebSocket
- Route reconstruction with speed computation and impossible-transition flagging
- Output report in XLSX and PDF
- Audit log on every search, route reconstruction and export
- Role model: state admin / department operator / viewer

### 1.2 Described, not built

Kafka, Elasticsearch, Kubernetes, federation middleware (Model 3), face
recognition, crowd analytics, vehicle re-identification, and live VAHAN / eGujCop
integration. Each is addressed in Section 9 or Section 10 as part of the scale-out
or integration path. At 30–50 cameras PostgreSQL does all of it, and adding those
components would have cost the prototype without improving the demonstration.

---

## 2. Architecture

### 2.1 Prototype topology

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SENTINEL SANDBOX GRID          30 cameras · RTSP/TCP :8554 · HLS/WHEP  │
└───────────────┬─────────────────────────────────────┬───────────────────┘
                │ RTSP over TCP                       │ HLS / WHEP
                │ (inference path)                    │ (viewing path)
                ▼                                     ▼
┌──────────────────────────────┐          ┌──────────────────────────────┐
│  ANPR WORKER  (anpr_worker)  │          │   BROWSER — React + Vite     │
│                              │          │                              │
│  StreamCapture               │          │  • GIS map (Leaflet)         │
│   · TCP transport forced     │          │  • Video wall (hls.js)       │
│   · PTS timing, never clock  │          │  • Plate search              │
│   · IDR settle + quality gate│          │  • Live alert panel          │
│   · backoff 2s → 30s         │          │  • Watchlist management      │
│   · loop-point track reset   │          └──────────────┬───────────────┘
│              │               │                         │ REST + WebSocket
│              ▼               │                         ▼
│  PlateDetector               │          ┌──────────────────────────────┐
│   · YOLOv9-t plate detector  │          │   FASTAPI BACKEND            │
│   · tiled 2×3 @2× upscale    │          │                              │
│   · cct-s-v2 OCR (10 slots)  │          │  /cameras  /detections       │
│   · overlay-text rejection   │          │  /watchlist /alerts          │
│              │               │          │  /analytics /ingest /audit   │
│              ▼               │  POST    │  ws://…/ws/alerts            │
│  TrackManager + vote()       │─────────▶│                              │
│   · IoU→proximity assoc.     │detections│  matching: exact → pg_trgm   │
│   · per-char weighted vote   │          │  alert broadcast             │
│   · Indian plate grammar     │          └──────────────┬───────────────┘
└──────────────────────────────┘                         │
                                                          ▼
                                  ┌──────────────────────────────────────┐
                                  │  POSTGRESQL 17 + PostGIS + pg_trgm   │
                                  │  cameras · detections · watchlist    │
                                  │  alerts · audit_log · users          │
                                  └──────────────────────────────────────┘
```

Every frame is decoded and analysed inside the deployment. No video, and no crop
of a frame, is sent to any external service. The only outbound calls the platform
makes are to OpenStreetMap Nominatim (one-off camera geocoding, cached to disk)
and the OSRM demo server (optional road-snapping of a drawn route) — neither is in
the detection or alerting path, and both degrade gracefully when unavailable.

### 2.2 Component responsibilities

| Component | Responsibility | Key module |
|---|---|---|
| Sandbox client | Authenticated catalogue fetch; commits `catalogue.json` | `app/sandbox_client.py` |
| Ingest | Camera onboarding, location resolution, provenance | `app/routers/ingest.py`, `app/geocoding.py` |
| Capture | RTSP/TCP, PTS timing, reconnect, quality gate, loop detection | `app/vision.py` |
| Detection | Tiled inference, dedup, overlay rejection | `app/vision.py` |
| Aggregation | Track association, per-character weighted voting | `app/vision.py`, `app/plate_grammar.py` |
| Correlation | Exact then fuzzy watchlist matching; alert creation | `app/routers/watchlist.py` |
| Distribution | WebSocket alert broadcast | `app/websocket_manager.py` |
| Analytics | Search, route reconstruction, reports | `app/routers/detections.py`, `app/reporting.py` |
| Accountability | Audit trail with purpose and case reference | `app/audit.py` |

---

## 3. Integrating heterogeneous cameras, NVRs and VMS

The sandbox presents one protocol family, but a statewide platform will not. The
design point is that **nothing above the connector layer knows what a camera is**.

A camera enters the registry as a record with a stream URL and a codec hint. The
capture layer takes a URL and yields frames. Everything downstream — indexing,
matching, mapping, reporting — operates on `Detection` and `Camera` rows and is
therefore already protocol-agnostic.

| Source class | Integration route | Prototype status |
|---|---|---|
| ONVIF Profile S/T cameras | ONVIF device discovery → RTSP URI | Design |
| Direct RTSP / RTSPS | Native; the sandbox path | **Working** |
| HLS / WebRTC (WHEP) gateways | Native; the viewing path | **Working** |
| NVR/DVR with RTSP export | Per-channel RTSP URLs registered as cameras | Design |
| Proprietary VMS (Milestone, Genetec, Hikvision) | Vendor SDK/API adapter behind the same connector interface | Design |
| Legacy analogue via encoder | Encoder presents RTSP; unchanged upstream | Design |

**What we would need from each department** to assess integration feasibility is
precisely the canonical camera schema in Tech Doc Appendix A. In practice the
minimum viable set is: camera identifier, site name, coordinates, owning
department, make/model, codec and resolution, streaming protocol and endpoint,
authentication method, network path and available bandwidth, retention policy and
recording location, and a named technical contact. The registry schema in this
prototype (`cameras` table, Section 5) is a working subset of that list, and the
gaps we hit on the sandbox — no coordinates, no department, no codec — are exactly
the fields we would insist on from a real department.

---

## 4. Stream ingestion from dispersed locations

Four sandbox-specific lessons shaped the capture layer, and each is a general
property of real CCTV estates rather than a quirk of this grid.

**TCP transport is mandatory.** UDP loses fragments across NAT and firewalls, and
partial delivery produces corrupt frames that are indistinguishable from model
failure. The worker sets `rtsp_transport;tcp` before OpenCV loads its FFmpeg
backend.

**Timing comes from the presentation timestamp, never the wall clock.** On connect
the gateway replays its buffered group-of-pictures, so the first second of frames
arrives faster than real time. Arrival-timestamped logic computes impossible
velocities on every reconnect. All timing derives from `CAP_PROP_POS_MSEC`. The
reported frame rate is also ignored: the sandbox declares 30 fps and delivers
14–23 fps, so anything derived from the declared rate would be wrong.

**Frames must be gated before inference.** Frames arriving before the first IDR
decode to flat grey artefacts. Feeding them to the detector wastes CPU and
produces phantom reads, so the capture layer discards a settling window and then
rejects frames whose luminance spread and edge density indicate corruption. Around
30 of 1,308 frames were rejected during benchmarking. Night footage is dim but
structured, and is correctly retained.

**State must survive discontinuity.** The footage loops with a hard scene cut,
detected as a PTS regression, at which point all tracker state is discarded rather
than allowed to associate a vehicle from before the cut with one after it.

Reconnection uses exponential backoff from 2 s to 30 s. Decoder warnings at join
are logged, never fatal.

At statewide scale this same capture logic runs at the **district edge node**, not
centrally — see Section 9.

---

## 5. Data model

```
cameras                          detections                     watchlist
─────────                        ──────────                     ─────────
id            uuid PK            id           uuid PK           id          uuid PK
native_id     text  ◄─────────── camera_id    uuid FK           entity_type text
name          text               plate_text   text  (GIN trgm)  plate_text  text
department    text               confidence   float             reason      text
location      geography(Point)   pts_ms       bigint            severity    text
lat, lon      float              detected_at  timestamptz       case_ref    text
address       text               track_id     text              added_by    text
rtsp/hls/whep text               crop_uri     text              active      bool
codec, resolution                vehicle_type text
status, is_live                  raw_reads    jsonb             alerts
extra         jsonb              bbox         jsonb             ──────
  ├ geo_source                                                  id            uuid PK
  ├ geo_confidence               audit_log                      watchlist_id  uuid FK
  └ district                     ─────────                      detection_id  uuid FK
                                 id          uuid PK            match_type    exact|fuzzy
users                            actor       text               score         float
─────                            action      text               status        new|ack|resolved
id, email, username              object_type text               matched_at    timestamptz
hashed_password                  object_id   text               acknowledged_by
role, department                 purpose     text
                                 case_ref    text
                                 at          timestamptz
```

Two indexes carry the demonstration: a **GIST index on `cameras.location`** for
spatial queries, and a **GIN trigram index on `detections.plate_text`** for fuzzy
search. `raw_reads` retains every per-frame read behind a voted result, so any
detection can be re-derived and audited rather than being taken on trust.

---

## 6. AI analytics approach

### 6.1 Position on training and third-party APIs

**We did not train a model, and we use no external ANPR API.** Both are deliberate.

Training a plate model requires annotated Indian plate data and GPU hours we do
not have, and would be beaten by the two post-processing steps described below,
which cost nothing.

The API question is more important. A paid ANPR service bills per call, adds
cloud round-trip latency to every alert, and — decisively — would mean shipping
frames of government CCTV footage to a third-party, likely foreign, cloud service.
For a Gujarat Police deployment reviewed by NFSU, "our servers, nothing leaves the
deployment" is the only defensible answer. A system whose real-time alerting
depends on an external API is also not deployable statewide.

So: **pretrained open-source detection and recognition running entirely on local
infrastructure, with domain adaptation applied through track-level confidence
aggregation and Indian plate-format validation rather than retraining.**

### 6.2 Pipeline

```
frame ──▶ quality gate ──▶ tile 2×3 @2× ──▶ YOLOv9-t plate detector
                                                      │
                                            ┌─────────┴─────────┐
                                            ▼                   ▼
                                     map box to           cct-s-v2 OCR
                                     full frame           (10 slots)
                                            │                   │
                                            └─────────┬─────────┘
                                                      ▼
                                        dedup ──▶ overlay-text rejection
                                                      │
                                                      ▼
                                        track association (IoU → proximity)
                                                      │
                                     ┌────────────────┴────────────────┐
                                     ▼                                 ▼
                       per-character weighted vote          Indian plate grammar
                       across 20–35 reads                   O/0 I/1 S/5 B/8 Z/2 G/6
                                     └────────────────┬────────────────┘
                                                      ▼
                                        one detection per vehicle pass
```

### 6.3 Where the accuracy actually comes from

Not from the model. From two steps that cost nothing:

**Track-level voting.** A vehicle is visible for 20–60 frames. Rather than
trusting whichever frame happened to be sampled, every read of a track votes
per character, weighted by the OCR's own per-character confidence, with reads
right-aligned on the four-digit serial (the most reliably segmented part of an
Indian plate). Measured on ground truth, tracks accumulate 20–35 reads and reach
confidence 1.000.

**Indian plate grammar.** The format is `[2 letters][1–2 digits][1–3 letters][4
digits]`. Knowing which positions must be alphabetic and which numeric makes
O↔0, I↔1, S↔5, B↔8, Z↔2 and G↔6 deterministically correctable, and lets the state
code be validated against the real RTO prefix list. The pipeline's own OCR
returned `GJO1AB1234` during development; position 2 must be a digit, so the
letter O is unambiguously a zero. 7/7 on the correction test cases.

A third step proved just as important on this grid: **rejecting camera overlay
text**. The detector offers up burnt-in timestamps, `CSITMS-31`, `PTZ` labels and,
in one observed case, an "ADVERTISE HERE" billboard read as `AEER75EEEE`. These
are filtered before they can enter the index.

### 6.4 The tiling decision, and its cost

The sandbox cameras are wide-area PTZ overviews. At 1920×1080 a number plate is
often 10–20 px wide — far below what a 384 px detector resolves from a whole
frame. Measured on `cam05`:

| | Full frame | Tiled 2×3 @2× |
|---|---|---|
| Mean inference | 12.3 ms | 185.9 ms |
| Est. streams per machine (20 cores) | ≈251 | ≈26 |
| Plate candidates in a 90 s window | **0** | **8** |
| Ground-truth plates recovered (§6.5) | 3/6 | **6/6** |

Tiling costs 15× the CPU. On this grid it is the difference between proposing
candidate regions and proposing none; on footage where plates are legible it is
the difference between recovering 3 of 6 plates and recovering all 6. This single
table is the basis of the tiered-analytics argument in Section 9.

### 6.5 Measured accuracy, stated honestly

On a ground-truth clip of six vehicle passes at production settings: **6/6 plates
recovered exactly, zero false positives** (`tools/make_sample_feed.py --validate`,
reproducible). With tiling disabled the same clip yields 3/6.

A per-frame audit showed **every OCR read of a detected plate was
character-perfect**. The binding constraint is plate *detection*, not
*recognition*.

**On the live sandbox feeds the pipeline reads no valid plates, and we say so.**
Measured across six cameras for 75 s each, counted at every stage:

| Stage | Count |
|---|---|
| Frames captured | 1,175 |
| Passed the quality gate | 198 |
| Plate-shaped regions proposed by the detector | 165 |
| OCR strings returned | 87 |
| Passed the plausibility filter | 34 |
| **Valid Indian registration plates** | **0** |

A continuous eight-camera run over ~25 minutes produced the same result.

The stage breakdown is what makes this interpretable. The detector is working —
it proposed 165 plate-shaped regions. The OCR is working — it returned 87
strings. But those strings are roadside text, not vehicles: cam05's repeated
`AEVETEE` is the "ADVERTISE HERE" billboard in frame, cam24's `C8MCY811` is
signage. The Indian-plate grammar validator rejected every one, which is the
system behaving correctly.

The cause is camera siting. These are wide-area PTZ overviews, largely at night;
a vehicle occupies 30–80 px of a 1920×1080 frame, putting its plate at 5–15 px —
below the resolution at which ten characters can be recovered, tiling and
upscaling included. Upscaling cannot restore detail the sensor never captured.

So the honest claim is narrow and defensible: a pipeline validated end to end at
**100% on footage where plates are legible** (§6.5 above), which **correctly
rejects every false candidate** where they are not, and whose limitation here is
the camera estate rather than the software. **ANPR requires cameras sited for
it** — mounted low, angled along the carriageway, framed on the plate region —
and that is a finding worth reporting to the department in its own right.

The rejection behaviour is itself a result. A system that had reported `AEVETEE`
as a vehicle would have produced impressive-looking detections and a worthless
index.

### 6.6 Model selection note

`max_plate_slots` in `fast-plate-ocr` decides whether a 10-character Indian plate
can be represented at all. The 8-slot models return `GJ01AB1234` as `01AB123` — a
truncation that still looks like a valid plate and so corrupts the index without
registering as an error. `cct-s-v2-global-model` (10 slots) is used throughout.

---

## 7. Watchlist correlation and alerting

### 7.1 Matching

Every detection written to the index is checked against the active watchlist
synchronously, before the transaction commits:

1. **Exact match** on the normalised plate string → `match_type = exact`, score 1.0
2. **Fuzzy match** via `pg_trgm` similarity > 0.7 → `match_type = fuzzy`, score = similarity

```sql
SELECT *, similarity(plate_text, :q) AS score
FROM detections
WHERE plate_text % :q
ORDER BY score DESC, detected_at;
```

Fuzzy matching is not a nicety. ANPR will misread a character, and exact-match-only
search fails in front of an evaluator on a plate the system genuinely detected.
Verified: searching `GJO1AB1234` returns the sightings stored as `GJ01AB1234`.

### 7.2 Alert workflow

```
detection ──▶ match? ──no──▶ indexed only
                │
               yes
                ▼
         alert created (status = new)
                │
                ├──▶ WebSocket broadcast ──▶ operator UI toast + alert panel
                │
                ▼
         operator acknowledges (status = ack, acknowledged_by, timestamp)
                │
                ▼
         resolved (status = resolved, notes)
```

Alerts carry the watchlist reason (stolen / wanted / missing / blacklisted) and
severity (low / medium / high / critical), so prioritisation is a property of the
watchlist entry rather than a UI decision. Severity drives ordering and visual
treatment in the operator panel.

At statewide scale this is where a message broker enters the design — see
Section 9.3 — but at this scale a synchronous check plus a WebSocket fan-out is
both simpler and lower-latency.

---

## 8. Route reconstruction

1. Retrieve all sightings of the plate, ordered by `detected_at`
2. For each consecutive pair, compute great-circle distance and elapsed time, and
   from those the implied average speed
3. Flag any transition above ~150 km/h as physically implausible — **and show it**,
   marked low-confidence, rather than silently dropping it
4. Return the straight-line path, plus an optional road-snapped path from the
   public OSRM demo server, kept as a **separate field** so an interpolation is
   never mistaken for evidence

Point 3 is a deliberate design position. A system that hides its own uncertain
results is harder to trust than one that surfaces them: a flagged transition tells
an investigator either that a plate was misread or that two vehicles share a
similar registration, and both are operationally useful.

---

## 9. Scaling to ~80,000 cameras

This section is a design argument. It is not implemented, and we do not claim it is.

### 9.1 Why flat central ingestion fails

From Tech Doc §4.9.1, at an assumed H.265 camera mix:

| Quantity | Value |
|---|---|
| Aggregate ingest bandwidth | **≈192 Gbps** |
| Central write rate | ≈24 GB/s |
| Raw volume, 30 days | **≈62 PB** |

Direct camera-to-core ingestion at this scale requires ~192 Gbps of sustained
backhaul into one facility. That is not a procurement problem; it is an
architectural dead end.

### 9.2 Edge-first topology

```
   camera  ──▶  DISTRICT EDGE NODE  ──▶  REGIONAL DC  ──▶  STATE CORE
                · recording                · aggregation      · registry
                · transcoding               · regional search  · statewide search
                · ANPR inference            · warm storage     · cross-region routes
                · alert generation                             · dashboards, audit
                ▼                           ▼                  ▼
           only metadata,              metadata + clips    metadata only
           alerts and requested
           clips travel upstream
```

Edge nodes record and analyse locally; only metadata, alerts and specifically
requested clips traverse the backbone. This reduces the wide-area requirement by
**two to three orders of magnitude**, because a plate read is a few hundred bytes
where the video that produced it is megabytes per second.

### 9.3 What changes, and at what threshold

| Concern | Prototype (≤50 cameras) | Statewide (80,000) |
|---|---|---|
| Ingest | Direct RTSP from the worker | District edge nodes; core never touches raw video |
| Detection index | One PostgreSQL table | Partitioned by time and region; regional shards |
| Search | `pg_trgm` GIN index | Same, per shard, with a scatter-gather federation layer |
| Alert distribution | In-process WebSocket fan-out | Message broker (Kafka/NATS) between edge and core |
| Camera map | Client-side clustering | Server-side clustering — mandatory above ~10,000 points |
| Analytics scheduling | All selected cameras, always | Tiered policy — see §9.4 |
| Storage | Local disk for crops | Hot NVMe → warm object → cold archive tiering |

We would introduce a broker at the point where alert fan-out crosses a data-centre
boundary, not before. Adding it at 30 cameras would be complexity without benefit.

### 9.4 Analytics capacity, and the tiering argument

Our measured figure is **≈26 concurrent tiled-ANPR streams per 20-core CPU
machine**. Naively, 80,000 cameras under continuous ANPR would need ~3,000 such
machines (or, per Tech Doc §4.9.2, ~2,667 GPUs at 30 streams each) — which is not
a serious proposal.

The measured full-frame figure of ~251 streams per machine is the other end of the
curve, and the correct answer is a **tiered analytics policy**:

| Tier | Share of estate | Workload | Rationale |
|---|---|---|---|
| Tier 1 — ANPR continuous | ~5–10% | Tiled ANPR, always on | Highways, border posts, ANPR-sited cameras |
| Tier 2 — event-triggered | ~20–30% | Analytics on motion or on demand | Urban junctions |
| Tier 3 — registry & view only | ~60–75% | Recording and live view | Coverage without analytics cost |

This turns an impossible capital requirement into a policy decision the department
can make per district, and it is directly supported by our measured numbers rather
than asserted.

### 9.5 Where linearity breaks

Honest limits of the projection: network fan-in at regional aggregation points;
metadata hot-partitioning when many cameras share a timestamp range; storage
rebuild times at petabyte scale; and cross-region route queries, which are
scatter-gather and degrade with shard count. Each needs load-testing before any
statewide commitment, and a benchmark of 200 streams with a transparent projection
is worth more than an unsupported claim of 80,000.

---

## 10. Integration with VAHAN, SARTHI, eGujCop and NAFIS

These are closed systems with no access route for a hackathon team, and we do not
pretend otherwise.

The correct engineering posture is **contract-first**: define the request/response
contract, implement the adapter against it, mock the endpoint with realistic
synthetic records, and document exactly what changes when real credentials arrive.

For VAHAN vehicle lookup, the adapter interface is a single call — registration
number in, owner and vehicle particulars out — behind which sits either the mock
or, with credentials, the real endpoint. What changes on the day access is
granted: the base URL, the authentication mechanism, a rate limiter, a response
cache, and the audit hook that records which officer looked up which vehicle and
why. Nothing above the adapter changes.

Stating this plainly is what "integration readiness" means, and it survives
questioning in a way that a claimed live integration would not.

---

## 11. Security, privacy and accountability

**Access control.** JWT authentication with three roles: state admin (full access
including audit), department operator (own department's cameras, search, watchlist),
viewer (live view and map only).

**Audit trail.** Every plate search, route reconstruction and report export writes
an `audit_log` row with actor, action, object, **stated purpose**, case reference,
IP and user agent. Purpose limitation is only meaningful if the purpose is captured
where the access happens, and an audit trail nobody can query is not an audit
trail — so `GET /api/v1/analytics/audit` exposes it.

**Data minimisation.** The index stores plate text, timestamp, camera and a small
evidence crop — not continuous video. Crops are the plate region plus a margin,
not the whole scene.

**DPDP Act 2023 alignment.** Purpose-bound access with a recorded purpose, role-based
restriction, minimisation to what policing requires, and a complete access trail.
Retention policy is a departmental decision; the schema supports time-bounded
deletion of detections independently of the camera registry.

**Transport and credentials.** Sandbox credentials live in environment
configuration, never in code, and are masked in every log line the platform emits.
Stream URLs carrying basic-auth are redacted before logging.

**Residency.** All inference is local. No frame, crop or plate read leaves the
deployment boundary.

---

## 12. Known limitations

Stated deliberately, because an honest limitations section is worth more than an
overclaim caught in questioning.

1. **The pipeline reads no valid plates from the sandbox grid.** These are
   wide-area night-time PTZ overviews where a plate is 5-15 px wide. §6.5 gives
   the stage-by-stage measurement showing the detector and OCR both working while
   every candidate is roadside signage, correctly rejected. This is a property of
   camera siting, not of the pipeline, which validates at 100% on legible
   footage.
2. **Camera coordinates are geocoded, not surveyed.** The catalogue publishes only
   id and name. Every camera records `geo_source` and `geo_confidence`; positions
   are accurate to the named site, not to the pole.
3. **Department attribution is inferred** from the site type in the camera name,
   and is labelled as inferred wherever it is displayed. A real deployment takes
   this from the department's own asset register.
4. **The route is a sequence of point sightings.** Between two cameras the vehicle's
   path is unknown; the road-snapped line is an interpolation, returned separately
   and never presented as evidence.
5. **Fuzzy matching can produce false positives** on similar registrations. Alerts
   carry the match type and score so an operator can weigh them, and exact matches
   are distinguished from fuzzy ones in the UI.
6. **No vehicle re-identification.** A vehicle whose plate is never legible is not
   tracked; we do not infer identity from colour or shape.
7. **Single-node deployment.** The prototype has no HA or DR. Section 9 describes
   the path; it is not implemented.
8. **HLS did not open through OpenCV's FFmpeg backend** from our network; RTSP on
   port 8554 is the working ingest path. Browser HLS playback is unaffected.

---

## 13. Deployment

```bash
# Database — PostgreSQL 16+ with PostGIS and pg_trgm
docker run -d --name sentinel-db -p 5432:5432 \
  -e POSTGRES_PASSWORD=sentinel postgis/postgis:16-3.4
psql -c "CREATE EXTENSION postgis; CREATE EXTENSION pg_trgm;"

# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env          # set DATABASE_URL and sandbox credentials
python run_server.py          # API on :8000, OpenAPI at /api/docs

# ANPR indexer — start early and leave running
python anpr_worker.py --max-streams 6

# Frontend
cd frontend && npm install && npm run dev    # :5173
```

Infrastructure sizing for the prototype: one 20-core CPU machine runs the API, the
database client and ~6 ANPR streams comfortably; ~26 streams saturates it. No GPU
is required, which is itself a deployability argument for district-level nodes.

---

## 14. Evidence index

| Claim | Where to verify |
|---|---|
| Measured throughput, both modes | `DOCS/MEASUREMENTS.md` §1; `python anpr_worker.py --benchmark` |
| 6/6 plate accuracy, 0 false positives | `DOCS/MEASUREMENTS.md` §2; `python tools/make_sample_feed.py --validate` |
| Live-grid yield, stage by stage | `DOCS/MEASUREMENTS.md` §2a |
| Grammar correction, noise rejection, VAHAN contract | `python -m pytest tests/ -q` (57 tests) |
| OCR model selection | `DOCS/MEASUREMENTS.md` §4 |
| Sandbox capture behaviour | `DOCS/MEASUREMENTS.md` §5 |
| Location provenance per camera | `GET /api/v1/ingest/status` |
| Audit trail | `GET /api/v1/analytics/audit` |
| API surface | `http://localhost:8000/api/docs` |
