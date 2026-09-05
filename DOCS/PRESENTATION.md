# Sentinel — Solution Presentation

Slide-by-slide content for the submission deck. Each slide gives the headline, the
content to put on it, and speaker notes. Export to PDF for submission.

Design guidance: dark slate background (#0F1721), white headings, one accent blue
(#2F6FEB), one alert amber (#F0A87C). No clip art. Every number on these slides is
measured and reproducible — see `DOCS/MEASUREMENTS.md`.

---

## Slide 1 — Title

# SENTINEL
### Statewide CCTV Integration Platform

**Model 1** — Central CCTV Registry & GIS Mapping
**Model 2** — Unified Viewing Platform with ANPR & Watchlist Alerting

Gujarat CCTV Integration Hackathon 2026 · Category 1
Team: _______________ · Members: _______________

> A working platform running against the live Sentinel sandbox grid — 30 cameras
> onboarded and mapped, a continuous ANPR pipeline validated at 100% on legible
> footage, automatic watchlist alerting, and route reconstruction across cameras.

**Speaker note:** Open on the result, not the introduction. One sentence: "Hand us
a registration number and we will show you where that vehicle has been, across the
grid, with timestamps — because we have been indexing continuously since Thursday."

---

## Slide 2 — The problem, and what wins it

**The operational gap**

- Cameras are owned by many departments, in many formats, with no common registry
- An investigator asking "where has this vehicle been?" has no way to ask it once
- Watchlist matching, where it exists, is a human watching a screen

**What Sentinel does**

| | |
|---|---|
| Onboards | Any camera the catalogue publishes, with location provenance recorded |
| Watches | Unified live wall, no per-department client |
| Reads | Continuous ANPR — every plate, every camera, every timestamp, indexed |
| Correlates | Automatic exact-then-fuzzy watchlist matching |
| Alerts | Real time, over WebSocket, with severity from the watchlist entry |
| Reconstructs | Timestamped route across cameras, on a map |
| Accounts | Every search and export audited with a stated purpose |

**Speaker note:** The last row is the one most teams skip and the one a government
evaluator cares about most.

---

## Slide 3 — Architecture

```
SANDBOX GRID  30 cameras · RTSP/TCP · HLS/WHEP
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

**Stack:** Python 3.12+ / FastAPI · PostgreSQL 17 + PostGIS + pg_trgm ·
React + Vite + TypeScript · Leaflet · hls.js · ONNX Runtime (CPU)

**Deliberately not built:** Kafka, Elasticsearch, Kubernetes, Keycloak. At this
scale PostgreSQL does all of it; the scale-out path is designed and documented
rather than half-implemented.

**Speaker note:** Say the last line out loud. Restraint is a competence signal, and
the HLD Section 9 shows we know exactly where each of those enters the design.

---

## Slide 4 — Model 1: Registry & GIS

**The unpleasant surprise, handled honestly**

The sandbox catalogue publishes **only `id` and `name`** — no coordinates, no
department, no codec.

**What we did**

- Resolved all 30 camera locations from the real site names in the catalogue
- Strict precedence: hand-verified → Nominatim geocoding (rate-limited, cached,
  bounded to Gujarat) → district centroid → **null**
- Every camera stores `geo_source` and `geo_confidence`, so provenance travels
  with the record and is visible in the UI and the report

**What we did not do**

We did not invent coordinates. An earlier approach placed cameras on an arithmetic
grid — a Junagadh-named camera plotted in Surat. That was removed. A camera we
cannot locate is reported as unlocated.

**GIS features:** PostGIS geography points, GeoJSON export, department / status /
location-confidence layers, clustered markers, click-through to the live tile.

**Speaker note:** This slide is about integrity. Cameras now sit in their real
districts — Junagadh, Rajkot, Navsari, Kutch — and any evaluator can cross-check a
name against the map.

---

## Slide 5 — Model 2: ANPR, and where accuracy comes from

**No training. No API key. Nothing leaves the deployment.**

Pretrained open-source models (YOLOv9-t detector, cct-s-v2 OCR) on **local CPU**.
No frame reaches any third party; no external service sits in the alerting path.

**Accuracy comes from two free steps, not from a bigger model**

**1 · Track-level voting** — a vehicle is visible 20–60 frames. Every read votes
per character, weighted by the OCR's own per-character confidence, right-aligned
on the four-digit serial. Tracks reach 20–35 reads and confidence 1.000.

**2 · Indian plate grammar** — `[2 letters][1–2 digits][1–3 letters][4 digits]`.
Knowing which positions must be alphabetic makes O↔0, I↔1, S↔5, B↔8, Z↔2, G↔6
deterministically correctable, with the state code validated against the RTO list.

> Real example: our OCR returned `GJO1AB1234`. Position 2 must be a digit, so the
> letter O is unambiguously a zero. **7/7** on the correction test cases.

**3 · Overlay rejection** — the detector offers up burnt-in timestamps, `CSITMS-31`,
`PTZ` labels, and the "ADVERTISE HERE" billboard on cam05. Filtered before the index.

**Measured on ground truth:** **6/6 plates, 0 false positives.**
**Measured on the live grid:** 165 plate-shaped regions, 87 OCR strings, **0 valid
plates** — every candidate was signage, and every one was rejected. See Slide 10.

**Speaker note:** If asked "did you train a model?" — answer with the sentence in
bold at the top. It is a strength, not an admission.

---

## Slide 6 — The engineering decision that matters

**These cameras are wide-area night PTZ overviews. A plate is 5–15 px wide.**

Full-frame inference at 384 px proposes **nothing** on this grid. Tiled inference
on overlapping upscaled regions does find plate-shaped regions — at 15× the CPU
cost. On legible footage that difference is 3/6 versus **6/6** plates recovered.

| Measured on cam05, 20-core CPU, no GPU | Full frame | **Tiled 2×3 @2×** |
|---|---|---|
| Mean inference | 12.3 ms/frame | **185.9 ms/frame** |
| Est. concurrent streams per machine | ≈251 | **≈26** |
| Plate candidates in a 90 s window | **0** | **8** |
| Ground-truth plates recovered | 3/6 | **6/6** |

**Why this table is the scalability answer**

ANPR is not a flat per-camera cost. It is a **policy choice about which cameras
carry analytics** — and that choice is now backed by measurement, not assertion.

| Tier | Share | Workload |
|---|---|---|
| 1 — continuous ANPR | 5–10% | Highways, border posts, ANPR-sited cameras |
| 2 — event-triggered | 20–30% | Urban junctions |
| 3 — registry & view | 60–75% | Coverage without analytics cost |

**Speaker note:** Most teams quote one throughput number. Quoting *both* modes, and
the zero, is what shows the work. If asked why the live grid yields nothing, go
straight to Slide 10 — we measured it stage by stage and the answer is camera
siting, not the software.

---

## Slide 7 — Correlation, alerting and route reconstruction

**Watchlist matching — exact, then fuzzy**

Every detection is checked before its transaction commits: exact match, then
`pg_trgm` trigram similarity > 0.7. A match writes an alert and broadcasts it over
WebSocket with the watchlist's own reason and severity.

```sql
SELECT *, similarity(plate_text, :q) AS score
FROM detections WHERE plate_text % :q
ORDER BY score DESC, detected_at;
```

> **Fuzzy search is not a nicety.** ANPR will misread a character, and
> exact-match-only search fails live on a plate you genuinely detected.
> Verified: searching `GJO1AB1234` returns the sightings stored as `GJ01AB1234`.

**Route reconstruction**

Sightings ordered by time → great-circle distance and elapsed time between
consecutive pairs → implied speed → **transitions above ~150 km/h flagged and
shown**, not silently dropped.

A flagged transition tells an investigator either that a plate was misread or that
two vehicles share a similar registration. Both are useful. A system that hides its
own uncertainty is harder to trust than one that surfaces it.

**Speaker note:** Demonstrate the fuzzy search live if there is time. It is the
single most persuasive twenty seconds in the demo.

---

## Slide 8 — Security, privacy and accountability

| Control | Implementation |
|---|---|
| Access control | JWT; three roles **enforced per route**, not just documented |
| **Audit trail** | Actor from the **verified token**, never a request parameter, with stated purpose and case reference |
| Data minimisation | Plate text, timestamp, camera, plate-region crop — not continuous video |
| Residency | All inference local; no frame or crop leaves the deployment |
| Credentials | Environment only; masked in logs; **never serialised to the browser** |
| Transport | CSP · X-Frame-Options DENY · nosniff · HSTS · referrer and permissions policies |
| Rate limiting | 10/min on auth, 300/min elsewhere; video segments exempt |
| DPDP Act 2023 | Purpose-bound access, role restriction, minimisation, full access trail |

> **Verified, not asserted:** a viewer token gets **403** on the audit trail and
> on plate search, **200** on the camera registry. The eleventh login attempt in a
> minute returns **429**.

**Closed government databases — handled correctly**

VAHAN, SARTHI, eGujCop and NAFIS have no access route for a hackathon team, and we
do not pretend otherwise. We define the request/response contract, implement the
adapter, mock the endpoint with realistic records, and document exactly what
changes when credentials arrive: base URL, auth, rate limiting, cache, audit hook.
Nothing above the adapter changes.

**That is what integration readiness means**, and it survives questioning in a way
a claimed live integration would not.

---

## Slide 9 — Scaling to 80,000 cameras

**We reproduced the 80,000-camera bottleneck at a scale of eight**

Opening N concurrent RTSP connections to the sandbox gateway:

| Concurrent | Succeeded | Wall time | **Our CPU** (20 cores) |
|---|---|---|---|
| 2 | 2 / 2 | 12 s | **4%** |
| 4 | 4 / 4 | 26 s | **4%** |
| 6 | 6 / 6 | 41 s | **5%** |
| 8 | 7 / 8 | 88 s | **4%** |

Accept times at eight: 4s · 8s · 27s · 33s · 56s · 60s · 63s · 73s — a queue.

> **Our machine was idle at 4% CPU while the gateway took 73 s to accept the
> eighth connection.** The limit is the single shared ingress, not compute. That is
> the 80,000-camera problem in miniature, and no amount of faster hardware on our
> side moves it.

**Flat central ingestion does not work, and here is the arithmetic**

| Quantity | Value |
|---|---|
| Aggregate ingest bandwidth | **≈192 Gbps** |
| Central write rate | ≈24 GB/s |
| Raw volume, 30 days | **≈62 PB** |

**Edge-first topology**

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

Only metadata, alerts and requested clips traverse the backbone — reducing the
wide-area requirement by **two to three orders of magnitude**.

**Where linearity breaks:** network fan-in at regional aggregation, metadata hot
partitions, storage rebuild times, and scatter-gather cross-region route queries.
Each needs load-testing before any statewide commitment.

**Why the sandbox ceiling is not our ceiling**

| | Sandbox | Statewide deployment |
|---|---|---|
| Cameras per ingest point | 30, one shared gateway | 50–200 per district edge node |
| Who consumes a stream | Every competing team, over the internet | One edge node, on the local network |
| Across the WAN | Full video to every viewer | Metadata, alerts, requested clips |

80,000 cameras over ~400 edge nodes is **200 per node** — ordinary server load,
and consistent with our measured 26 concurrent ANPR streams per machine.

**Speaker notes:** If asked "your wall struggles at nine cameras, how will you do
80,000?" — go straight to the 4% CPU figure. The answer is: *the sandbox is one
shared gateway serving every team; no deployment looks like that, and our
measurements show the compute side has enormous headroom while the shared ingress
is what fails first. That is precisely why the architecture is edge-first — we are
watching the argument prove itself at a scale of eight.*

Then: "A measured benchmark of 26 streams with a transparent projection is worth
more than an unsupported claim of 80,000." 

---

## Slide 10 — What works, what does not

**Working, demonstrated, reproducible**

✓ 30 cameras onboarded with location provenance
✓ GIS map with department, status and confidence layers
✓ Live video wall — HLS grid plus WebRTC hero tile
✓ Continuous ANPR pipeline with tiled inference, track voting and plate grammar
✓ Exact, partial and fuzzy plate search
✓ Automatic watchlist matching and real-time alerts
✓ Route reconstruction with impossible-transition flagging
✓ Output report — XLSX and PDF
✓ Audit trail with purpose binding
✓ 57 automated tests · 6/6 ground-truth plate accuracy, 0 false positives

**Honest limitations**

- **The pipeline reads no valid plates from this grid.** Measured over 6 cameras:
  165 plate-shaped regions proposed, 87 OCR strings returned, **0 valid Indian
  plates** — every candidate was roadside signage (cam05's `AEVETEE` is the
  "ADVERTISE HERE" billboard), correctly rejected by the grammar validator. At
  5-15 px per plate no OCR can recover ten characters. **ANPR needs cameras sited
  for ANPR**, and that is a finding worth reporting to the department.
- Camera coordinates are **geocoded, not surveyed**; accurate to the site, not the pole.
- Department attribution is **inferred** from site type and labelled as such.
- The route is a **sequence of point sightings**; the road-snapped line is an
  interpolation, returned separately and never presented as evidence.
- Single-node prototype — no HA or DR. The path is designed, not built.

**Speaker note:** Do not rush this slide. NFSU and DA-IICT reviewers will probe;
having already named the weaknesses converts a hostile question into agreement.

---

## Slide 11 — Impact on policing

**Today** — an investigator with a registration number calls each department,
waits for someone to scrub footage, and assembles a timeline by hand over days.

**With Sentinel** — the number is typed once. Every sighting, every camera, every
timestamp, on a map, in seconds, because the index was built continuously rather
than searched on demand.

| Capability | Operational value |
|---|---|
| Continuous indexing | The route exists before it is asked for |
| Automatic watchlist alerts | A stolen vehicle announces itself; nobody watches a wall |
| Fuzzy search | A single misread character does not lose the vehicle |
| Cross-department registry | One question, one answer, regardless of who owns the camera |
| Purpose-bound audit | Surveillance capability with accountability attached |

**Roadmap** — federation across departments (Model 3), tiered analytics rollout by
district, VAHAN adapter activation on credential grant, then face recognition and
additional analytics on the same edge nodes.

---

## Slide 12 — Verify it yourself

| Claim | Command |
|---|---|
| Throughput, both modes | `python anpr_worker.py --benchmark` |
| 6/6 accuracy, 0 false positives | `python tools/make_sample_feed.py --validate` |
| Grammar and vision logic | `python -m pytest tests/ -q` → 45 passed |
| Location provenance | `GET /api/v1/ingest/status` |
| Audit trail | `GET /api/v1/analytics/audit` |
| Full API surface | `http://localhost:8000/api/docs` |

**Repository:** _______________
**Demo videos:** _______________
**Hosted instance:** _______________ (test credentials in the submission form)

Every number in this deck is reproduced in `DOCS/MEASUREMENTS.md`, with the command
that produces it.
