# Statewide CCTV Integration Programme
## Technical Solution Document — Models 1 to 4

**Version:** 1.0
**Date:** 3 September 2026
**Scope:** Build-ready technical specification for four proposed models of statewide CCTV integration — Registry & GIS Mapping (Model 1), Unified Viewing Platform (Model 2), Middleware / Federation Layer (Model 3), and Consolidated Central VMS (Model 4).

---

## How to Use This Document

Each model is specified independently and can be read on its own. Sections that do not apply to a given model have been omitted rather than padded — for example, Model 1 has no AI/ML approach because it processes no video, and Model 3 has no GPU requirement because it federates metadata rather than pixels.

Three things are worth reading before the model sections:

- **§0.1 The four models at a glance** — what distinguishes each, and how they combine.
- **§0.2 Shared ground truth** — assumptions, legal constraints, and the reality of Indian government API access, which materially shapes what is buildable.
- **Appendices A–E** — a canonical camera metadata schema, a consolidated dataset register, an API register, demo asset sources, and selection guidance. These are shared across models and are not repeated inside each section.

Throughout, figures marked **(planning estimate)** are order-of-magnitude sizing intended for architecture decisions and must be validated against your own benchmarks before procurement.

---

# 0. Common Context

## 0.1 The Four Models at a Glance

| | **Model 1** Registry & GIS | **Model 2** Unified Viewer | **Model 3** Federation Middleware | **Model 4** Central VMS |
|---|---|---|---|---|
| **Core question answered** | What cameras exist and where? | What are the cameras seeing? | How do the systems talk to each other? | Can one platform own everything? |
| **Handles live video** | No | Yes — relays it | No — metadata only | Yes — ingests and records it |
| **Stores video centrally** | No | No | No | Yes |
| **Departmental VMS survives** | N/A | Yes, untouched | Yes, untouched | No — superseded |
| **Integration topology** | N/A | Point-to-point (direct) | Hub-and-spoke (via middleware) | Consolidation (single platform) |
| **Primary data object** | Camera asset record | Video stream + ANPR event | Normalised event message | Video + full analytics corpus |
| **Dominant engineering discipline** | Full-stack + GIS | Real-time video + CV | Distributed systems | Infrastructure at scale |
| **GPU required** | No | Yes (modest) | No | Yes (very large) |
| **Realistic prototype scope** | Complete system | Working subset | Working system, 2+ adapters | Working micro-scale + projection |
| **Complexity (1–5)** | 2 | 4 | 3.5 | 5 |

**How they combine.** Model 1 is explicitly foundational and is designed to pair with one of the others. Models 2 and 3 are competing answers to the same fragmentation problem and are largely alternatives — Model 2 optimises for operator experience, Model 3 for systemic interoperability. Model 4 supersedes both. The strongest full-programme architecture is **Model 1 + Model 3 + Model 2's viewer built on top of Model 3's middleware**, with Model 4 as the long-horizon target state.

## 0.2 Shared Ground Truth

### 0.2.1 Deployment context

The reference to **eGujCop** in Model 4 identifies this as a **Gujarat state** programme. This matters for data sourcing: Gujarat-specific administrative boundaries, ward maps, and city datasets should be preferred over generic national data where available, and the Gujarat Urban Development Mission / Smart City SPVs (Ahmedabad, Surat, Vadodara, Rajkot, Gandhinagar) are the realistic first-wave departments.

### 0.2.2 The government API reality — read this before planning any integration

This is the single most common planning error in projects of this type. The following systems are **not openly accessible** and cannot be integrated during a prototype or hackathon build:

| System | What it is | Access reality |
|---|---|---|
| **VAHAN** | National vehicle registration database (MoRTH/NIC) | No public API. Government-to-government access via NIC on approved MoU. Commercial resellers (Surepass, Signzy, IDfy, Cashfree, Masters India) offer RC-verification APIs at per-call pricing with KYC onboarding. |
| **SARATHI / SARTHI** | National driving licence database | Same as above. DigiLocker exposes citizen-consented DL/RC documents, not bulk lookup. |
| **eGujCop** | Gujarat Police operational system (CCTNS lineage) | Closed. Access only through State Police IT cell. |
| **AFIS / NAFIS** | Fingerprint identification (NCRB) | Closed law-enforcement system. No external API of any kind. |

**The correct engineering response** is not to abandon these integrations but to build them as **contract-first adapters against documented mock services**. Define the request/response contract, implement the adapter, stand up a mock endpoint that returns realistic synthetic data, and ship a swap-in note explaining exactly what changes when real credentials arrive. This is what "integration readiness" in Model 4's requirement list actually means, and it demonstrates more architectural maturity than a live integration would. Document this explicitly — evaluators reward the team that understood the constraint.

### 0.2.3 Legal and privacy constraints

The **Digital Personal Data Protection Act, 2023** and the **DPDP Rules, 2025** govern personal data processing in India. CCTV footage of identifiable persons, vehicle-owner lookups, and above all facial recognition fall within scope. State instrumentalities have certain exemptions for sovereign functions, but these are conditional, not blanket, and do not remove the obligations of purpose limitation, retention limits, and security safeguards.

Practical implications for the build:

- **Purpose limitation** must be encoded, not just documented — every search should be tied to a stated purpose code and a case/incident reference.
- **Retention** must be automatic and enforced by the storage tier lifecycle, not by policy alone.
- **Audit logging** of every access to identifiable data must be immutable and queryable.
- **Face recognition (Model 4 only)** is the highest-risk feature in the entire programme. If you build it, gate it behind a separate role, log every query with justification, and include a written proportionality note in the security architecture document. If you are building for evaluation rather than deployment, consider demonstrating the capability on synthetic or consented faces only.

Design decisions that respect these constraints are a differentiator, not a tax. Most competing solutions will ignore them entirely.

### 0.2.4 Assumed non-functional baseline (all models)

| Property | Target |
|---|---|
| API availability | 99.5% for prototype-grade, 99.9% for production-grade |
| Auth | OIDC / OAuth2 with department-scoped RBAC; no shared credentials |
| Transport security | TLS 1.3 everywhere; mTLS between internal services in Models 3 and 4 |
| Audit | Append-only audit log with actor, action, object, timestamp, purpose |
| Data residency | India-only; MeitY-empanelled cloud or state data centre |
| Time sync | NTP-disciplined clocks on all ingestion nodes — critical for cross-camera correlation |

---

# Model 1 — Centralised CCTV Registry and GIS Mapping Platform

## 1.1 Problem Statement

Departments across the state — Municipal Corporations, Transport, Police, education and health institutions, transport undertakings, and Smart City SPVs — have each deployed CCTV independently over more than a decade of disconnected procurement cycles. Each department knows its own inventory to varying degrees of accuracy; no one holds a consolidated view.

Consequently the state cannot answer basic questions that any coverage or investment decision depends on:

- How many cameras exist in a given district, city, or ward, and who owns each one?
- Which cameras are functional today, and which have been dark for months?
- Which high-footfall or high-incident zones have no coverage at all?
- How much of the installed base is past end-of-life and needs replacement budgeting?
- Which cameras are technically capable of being integrated later — and which are analogue, unaddressable, or on isolated networks?

The absence of this inventory blocks every downstream initiative. Feed integration (Models 2–4) cannot be scoped without knowing what is to be integrated. Procurement cannot be rationalised. Gap analysis is impossible.

**This model deliberately excludes live video.** It is an asset management and spatial analytics problem, not a surveillance problem. That exclusion is what makes it independently deliverable in weeks rather than years, and it should not be violated.

## 1.2 Objective and Expected Outcome

**Objective.** Establish a single authoritative, continuously maintained register of every CCTV asset in the state, spatially indexed, with department-scoped ownership and self-service maintenance, exposed through a map interface and a documented API.

**Expected outcome — the system succeeds when:**

1. A state administrator can open one map and see every registered camera in the state, filterable by department, type, status, and vintage.
2. A department nodal officer can onboard 5,000 cameras from an existing spreadsheet in a single guided upload, with errors surfaced row-by-row and correctable in place.
3. Any authorised user can generate a gap-analysis report for a chosen boundary showing uncovered zones ranked by a defensible priority score.
4. An ageing-infrastructure report identifies every camera past its expected service life, grouped by department, with replacement cost bands.
5. A third-party system (including a future Model 2/3/4 platform) can retrieve the camera inventory over a documented, versioned REST API without any human in the loop.
6. Every field-level change to any record is attributable to a user, timestamped, and reversible in the audit view.

## 1.3 Functional Requirements

### FR-1 Camera onboarding — three paths

**FR-1.1 Bulk import.** Accept CSV and XLSX. Downloadable template with a data dictionary. Two-phase upload: *validate then commit*. The validation phase returns a per-row report with severity (error / warning / info), and the file is never partially committed. Support up to 50,000 rows per file. Provide a column-mapping step so departments do not have to reshape their existing sheets.

**FR-1.2 Manual entry.** Multi-step form with map-based coordinate picking (drag pin, or paste coordinates, or geocode an address). Field-level help text. Draft-save. Duplicate warning before commit.

**FR-1.3 API onboarding.** `POST /api/v1/cameras` and `POST /api/v1/cameras/bulk` with department-scoped API keys, idempotency keys to make retries safe, and per-key rate limits. Webhook callback on async bulk completion.

### FR-2 Validation and data quality

- **Mandatory field enforcement** by camera class (a fixed dome and a mobile body-worn unit require different fields).
- **Coordinate validation:** within state polygon; reject `0,0`; warn on precision below 5 decimal places; warn if the point falls in water or outside any known administrative boundary.
- **Deduplication:** composite matching on (device serial), (IP address + department), and (coordinate proximity < 15 m + same department + same type). Present suspected duplicates for human resolution rather than auto-merging.
- **Referential integrity:** department, camera make/model, and connectivity type resolve against controlled vocabularies, with a request-new-value workflow rather than free text.
- **Data quality score** per record (0–100) derived from field completeness and validation warnings, so departments can be ranked and nudged.

### FR-3 GIS map interface

- Base layers: OSM standard, satellite imagery, and a plain administrative base.
- Camera layer with **server-side clustering** — non-negotiable at 80,000 points; browser-side clustering will not survive.
- Toggleable overlays: department, camera type, operational status, connectivity type, installation vintage, ownership model.
- **Coverage visualisation:** approximate field-of-view wedges rendered from bearing + horizontal FOV + effective range where those attributes exist; a simple radius buffer where they do not. Clearly label this as indicative, not surveyed.
- Administrative boundary overlays: district, taluka, municipal ward, police station jurisdiction.
- Heatmap mode for density.
- Draw-a-polygon spatial query: select an arbitrary area, get every camera inside it, export.
- Click a camera → detail panel with full metadata, photo, change history, and maintenance log.

### FR-4 Health and maintenance status

Because this model has no video feed, "health" is determined by three complementary mechanisms, and the system should be explicit about which one produced a given status:

1. **Active reachability probe** — scheduled ICMP ping and TCP port check (554/80/443) against the camera or its NVR, where the registry has network reachability. Result: `reachable` / `unreachable` / `not_probeable`.
2. **Departmental status ingestion** — a `PATCH /api/v1/cameras/{id}/status` endpoint a department's own NVR or NMS can call, plus a polling adapter for departments that expose a status API.
3. **Manual declaration** — field staff or nodal officers set status through the UI or a mobile-friendly view, with a mandatory reason code and optional photo.

Derived states: `operational`, `degraded`, `down`, `under_maintenance`, `decommissioned`, `unknown`. Track `last_seen_at`, `downtime_hours_30d`, and `consecutive_failed_probes`. Maintain a maintenance ticket log per camera with open/closed status and AMC vendor reference.

> **Note on scope discipline:** reachability is *not* proof the camera is producing usable imagery — a camera can ping while pointed at a wall or with a fogged dome. State this limitation openly in the documentation; it becomes a natural argument for pairing Model 1 with Model 2 or 4.

### FR-5 Gap analysis

Two distinct reports, both spatial:

**FR-5.1 Coverage gap.** Partition the area of interest into a grid (H3 hexagons at resolution 8–9, roughly 0.7 km² and 0.1 km² respectively, or a simple 250 m square grid). For each cell compute camera count, weighted coverage score, and a priority weight drawn from available context layers (population density, road class, reported incident density, presence of critical infrastructure). Output ranked uncovered and under-covered cells with a suggested number of additional cameras.

**FR-5.2 Ageing infrastructure.** Cameras where `today − installation_date > expected_service_life` (default 7 years, overridable per make/model), or where make/model appears on a defined end-of-support list. Grouped by department and district, with count, age distribution, and indicative replacement cost band.

Both reports exportable to PDF and XLSX, and both available as API endpoints so they can be scheduled.

### FR-6 Access control, search and audit

- **Role model:** `state_admin` (all departments, read/write, user management), `dept_admin` (own department read/write, manage own users), `dept_operator` (own department read/write on assigned assets), `viewer` (read-only, configurable department scope), `auditor` (read-only including full audit trail), `api_client` (scoped machine access).
- **Row-level security** enforced at the database layer, not only in application code — PostgreSQL RLS policies keyed on department, so a bug in an API handler cannot leak another department's rows.
- **Search:** full-text across name, address, landmark, asset tag, serial; plus faceted filtering; plus spatial (radius, polygon, boundary).
- **Export:** CSV, XLSX, GeoJSON, KML. Every export logged with user, filter criteria, row count, and purpose.
- **Audit trail:** field-level change history — old value, new value, actor, timestamp, source (UI / bulk / API), and request ID. Immutable, append-only, retained indefinitely, exposed as a per-record timeline in the UI.

## 1.4 Recommended Tech Stack

| Layer | Recommendation | Rationale and alternatives |
|---|---|---|
| **Frontend** | React 18 + TypeScript, Vite | Mandated by the brief. TypeScript is strongly advised given the schema's breadth. |
| **UI kit** | Tailwind CSS + shadcn/ui | Fast, accessible, no heavy theme lock-in. Alt: Mantine, Ant Design (better for dense government-style tables). |
| **Map** | **MapLibre GL JS** + `react-map-gl` | Vector tiles and GPU rendering handle 80k points far better than Leaflet's DOM markers. Use **Leaflet + react-leaflet** only if the team already knows it and the dataset stays small. |
| **Map data layer** | `deck.gl` ScatterplotLayer / HexagonLayer for large point sets | Renders 100k+ points at 60 fps. Optional but transformative for the demo. |
| **Vector tiles** | **Martin** or `pg_tileserv` | Serves MVT tiles straight from PostGIS with zero ETL. This is the single highest-leverage choice in the stack. |
| **State / data fetching** | TanStack Query + Zustand | Query handles caching, pagination and optimistic updates; Zustand for map UI state. |
| **Tables** | TanStack Table with server-side pagination | Essential — never load the full inventory client-side. |
| **Backend** | **Python 3.12 + FastAPI** | Async, automatic OpenAPI generation (which *is* your API documentation deliverable), excellent geospatial ecosystem. Alt: Django + DRF + GeoDjango if you want the admin panel free; Node.js + NestJS if the team is JS-native. |
| **ORM / spatial** | SQLAlchemy 2.x + GeoAlchemy2 | Alt: Django ORM + GeoDjango. |
| **Validation** | Pydantic v2 | Doubles as the schema definition and the API docs. |
| **Database** | **PostgreSQL 16 + PostGIS 3.4** | Mandated and correct. Enable `postgis`, `postgis_raster`, `pg_trgm` (fuzzy search), `uuid-ossp`, and optionally `h3-pg`. |
| **Spatial indexing** | GiST on geometry columns; H3 index column for grid analytics | Precompute an `h3_r8`/`h3_r9` column per camera — turns gap analysis from a slow spatial join into a `GROUP BY`. |
| **Cache / queue** | Redis 7 | Session store, rate limiting, and Celery/ARQ broker. |
| **Background jobs** | Celery (or ARQ / Dramatiq) | Bulk import processing, scheduled health probes, report generation. |
| **Auth** | **Keycloak** | Realms map cleanly to departments; gives you OIDC, RBAC, LDAP/AD federation, and MFA without writing auth code. Alt: hand-rolled JWT + `python-jose` if Keycloak is too heavy for the timeline. |
| **File/object storage** | MinIO (S3-compatible) | Camera site photos, uploaded source files, generated reports. |
| **Reports** | WeasyPrint or ReportLab (PDF); `openpyxl` / `xlsxwriter` (XLSX) | |
| **Deployment** | Docker Compose for prototype; Kubernetes for production | |
| **Observability** | Prometheus + Grafana + structured JSON logging (`structlog`) | |

## 1.5 Datasets Required

Model 1 needs **no machine-learning dataset**. It needs four categories of reference and seed data.

### D-1 Camera inventory (the core dataset — internally generated)

This does not exist yet; creating it *is* the project. For prototype purposes you must synthesise a realistic dataset. Do not use random points — a demo with cameras in the Arabian Sea is a self-inflicted wound.

**Recommended synthetic generation method:**

1. Pull the OSM road network and POI layer for two or three Gujarat cities (Ahmedabad, Surat, Gandhinagar).
2. Sample camera positions along road segments, weighted toward junctions, arterial roads, markets, transport hubs, and government buildings — this produces a plausible spatial distribution.
3. Assign departments by realistic zoning: Traffic Police clustered on junctions and highways, Municipal Corporation on public spaces and solid-waste points, Transport on bus depots and terminals, institutions on their own campuses.
4. Assign attributes from realistic distributions — installation dates skewed to 2016–2023 with a Smart City bulge in 2018–2020, a mix of makes (Hikvision, Dahua, CP Plus, Bosch, Axis, Matrix), types (fixed dome / bullet / PTZ / ANPR / thermal), resolutions, and connectivity (fibre / RF / 4G / LAN).
5. Inject deliberate data-quality defects into 5–8% of rows — missing coordinates, transposed lat/long, duplicate serials, malformed dates, non-standard department names. **This is important:** it lets your validation engine actually demonstrate something, and it reflects reality.

Target volume: 25,000–80,000 records so that performance claims are credible.

### D-2 Administrative boundaries (external, essential)

Required for jurisdictional filtering, gap analysis, and all reporting rollups. Needed at: state, district, taluka, municipal corporation, municipal ward, and — if obtainable — police station jurisdiction.

### D-3 Context layers for gap-analysis weighting (external, high value)

Gap analysis without weighting produces "the desert has no cameras," which is useless. Weight cells by:

- Population density (Census 2011 ward-level, or WorldPop / GHSL gridded population for something more current)
- Road network class and junction density (OSM)
- Points of interest — schools, hospitals, markets, banks, places of worship, transport hubs (OSM)
- Built-up area / urban footprint (GHSL, ESA WorldCover)
- Crime or incident density, if any open district-level data is obtainable (NCRB publishes aggregate crime statistics; use as a district multiplier only)

### D-4 Controlled vocabularies (internally defined)

Department master, camera make/model catalogue with expected service life, connectivity types, ownership models, status reason codes. Small, but define them early — they are what stop the whole registry degrading into free text.

## 1.6 Data Sources

| Data need | Source | Access | Notes |
|---|---|---|---|
| Road network, POIs, buildings | **OpenStreetMap** via [Geofabrik India extract](https://download.geofabrik.de/asia/india.html) | Free, ODbL | Best single source for realistic camera placement. Query with Overpass API for targeted extracts. |
| District / state boundaries | [Datameet Maps](https://github.com/datameet/maps), [india-geodata](https://github.com/yashveeeeeeer/india-geodata), [INDIAN-SHAPEFILES](https://github.com/datta07/INDIAN-SHAPEFILES) | Free, community | Fastest path to working boundaries. Verify vintage. |
| Official boundaries | [Survey of India online maps portal](https://onlinemaps.surveyofindia.gov.in/) | Registration required | Authoritative for production; slower to obtain. |
| Satellite base / Indian geospatial layers | [ISRO Bhuvan](https://bhuvan.nrsc.gov.in/) | Free with registration | WMS/WFS services available; Indian-origin data is a positive signal for a government evaluation. |
| Global admin boundaries | [GADM](https://gadm.org/) | Free, non-commercial | Convenient fallback. Check licence terms for the deployment context. |
| Ward boundaries | Municipal Corporation GIS cells; Smart City SPV portals; AMC/SMC open data pages | Varies | Often the hardest layer to obtain. Digitising from published ward maps is a legitimate fallback. |
| Population | [Census of India 2011](https://censusindia.gov.in/), [WorldPop](https://www.worldpop.org/), [GHSL](https://ghsl.jrc.ec.europa.eu/) | Free | Census for ward-level; WorldPop/GHSL for gridded and more current. |
| National open data | [data.gov.in](https://data.gov.in/) | Free | Variable quality; worth searching for state transport and urban datasets. |
| Urban data exchange | [India Urban Data Exchange (IUDX)](https://iudx.org.in/) | Free with registration | Smart-city data catalogues from participating cities including Gujarat cities; genuinely relevant reference architecture for a state data platform. |
| Land cover / built-up | [ESA WorldCover](https://esa-worldcover.org/), Bhuvan LULC | Free | For urban/rural weighting. |
| Geocoding | Nominatim (self-host for volume), MapMyIndia/Mappls API, Google Geocoding | Mixed | Self-host Nominatim to avoid rate limits during bulk import. Mappls has better Indian address coverage. |

## 1.7 APIs and Services Required

### Consumed (external)

| Service | Purpose | Priority |
|---|---|---|
| Nominatim / Mappls Geocoding | Address ↔ coordinate resolution during onboarding | High |
| OSM tile server or MapTiler/Mappls tiles | Map base layer | High |
| Bhuvan WMS | Indian satellite imagery layer | Medium |
| SMS / email gateway (state MSDG gateway, or SMTP + a commercial SMS provider) | Maintenance alerts, downtime notifications | Medium |
| LDAP / Active Directory | If the state has an existing employee directory to federate | Medium |

### Exposed (this is a deliverable — see §1.13)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/cameras` | GET | Paginated, filterable inventory |
| `/api/v1/cameras` | POST | Create single camera |
| `/api/v1/cameras/{id}` | GET / PATCH / DELETE | Retrieve, update, soft-delete |
| `/api/v1/cameras/bulk` | POST | Async bulk create/update, returns job ID |
| `/api/v1/cameras/bulk/validate` | POST | Dry-run validation, returns row-level report |
| `/api/v1/jobs/{id}` | GET | Bulk job status and result |
| `/api/v1/cameras/geojson` | GET | GeoJSON FeatureCollection for map consumption |
| `/api/v1/cameras/within` | POST | Spatial query by polygon / radius / boundary ID |
| `/api/v1/cameras/{id}/status` | PATCH | Health status push from departmental systems |
| `/api/v1/cameras/{id}/history` | GET | Field-level audit trail |
| `/api/v1/analytics/coverage-gaps` | GET | Gap analysis for a boundary |
| `/api/v1/analytics/ageing` | GET | Ageing infrastructure report |
| `/api/v1/analytics/summary` | GET | Dashboard aggregates |
| `/api/v1/boundaries/{level}` | GET | Administrative boundary geometries |
| `/api/v1/reference/{vocabulary}` | GET | Controlled vocabulary lookups |
| `/tiles/cameras/{z}/{x}/{y}.pbf` | GET | Vector tiles (served by Martin) |

Publish as OpenAPI 3.1. FastAPI generates this automatically — do not hand-write it.

## 1.8 Data Processing Approach

There is no ML here, but there is a real data pipeline.

**Bulk import pipeline (the most important flow in the system):**

```
Upload → virus scan → format detect (CSV/XLSX) → header inference
    → user-confirmed column mapping → per-row parse
    → schema validation (Pydantic)
    → business-rule validation (coordinates, vocabularies, dates)
    → geocoding backfill for rows with address but no coordinates
    → duplicate detection (serial → IP+dept → spatial proximity)
    → generate row-level validation report → PRESENT TO USER
    → user resolves errors / accepts warnings / confirms merges
    → transactional commit + audit entries + H3 index computation
    → completion webhook + summary email
```

Process asynchronously via Celery with progress reporting. A 50,000-row file must never block an HTTP request.

**Health probe pipeline.** Celery Beat schedules probes at a configurable interval (default 15 minutes for reachable cameras, hourly for previously-down ones to reduce noise). Probes run concurrently with a bounded worker pool and short timeouts. Results write to a time-series `camera_health_events` table; the current status on the camera record is a derived materialised value updated by the same job. Use a **three-strike rule** before flipping a camera to `down` — single-probe flapping generates alert fatigue and destroys trust in the system.

**Gap-analysis pipeline.** Precompute nightly rather than on request. For each administrative unit, generate the H3 cell set, join camera counts, join weighting layers, compute priority score, and materialise into a `coverage_analysis` table. Requests then read a table instead of running a heavy spatial join, which turns a 40-second query into a 40-millisecond one.

**Scoring formula (starting point, tune with domain input):**

```
priority = (w1 · normalised_population_density)
         + (w2 · normalised_road_junction_density)
         + (w3 · normalised_poi_criticality)
         + (w4 · normalised_incident_density)
         − (w5 · normalised_existing_coverage)
```

Expose the weights in configuration so departments can tune them, and show the component breakdown in the report so the score is explainable rather than a black box.

## 1.9 System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  CLIENTS                                                          │
│  React SPA (map, forms, reports)  │  Department systems (API)     │
└────────────┬──────────────────────────────────┬──────────────────┘
             │                                  │
┌────────────▼──────────────────────────────────▼──────────────────┐
│  EDGE — NGINX / Traefik: TLS, rate limiting, static assets        │
└────────────┬──────────────────────────────────┬──────────────────┘
             │                                  │
┌────────────▼─────────────────┐   ┌────────────▼──────────────────┐
│  Keycloak — OIDC, realms      │   │  Martin — MVT vector tiles     │
│  per department, RBAC, MFA    │   │  (reads PostGIS directly)      │
└────────────┬─────────────────┘   └────────────┬──────────────────┘
             │                                  │
┌────────────▼──────────────────────────────────▼──────────────────┐
│  FastAPI APPLICATION                                              │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐ ┌────────────┐ │
│  │Registry │ │Onboarding│ │Spatial  │ │Health  │ │Analytics & │ │
│  │  CRUD   │ │& Validate│ │ Query   │ │Monitor │ │  Reports   │ │
│  └─────────┘ └──────────┘ └─────────┘ └────────┘ └────────────┘ │
│  Cross-cutting: RBAC guard · audit interceptor · rate limit      │
└────────┬─────────────────────────┬──────────────────┬────────────┘
         │                         │                  │
┌────────▼─────────┐  ┌────────────▼──────┐  ┌────────▼──────────┐
│ PostgreSQL 16    │  │ Redis 7           │  │ MinIO (S3)        │
│ + PostGIS 3.4    │  │ cache · rate      │  │ photos · uploads  │
│ cameras          │  │ limit · broker    │  │ generated reports │
│ health_events    │  └────────────┬──────┘  └───────────────────┘
│ audit_log        │               │
│ boundaries       │  ┌────────────▼──────────────────────────────┐
│ coverage_analysis│  │ Celery workers + Beat                      │
│ RLS by department│  │ bulk import · health probes · nightly      │
└──────────────────┘  │ gap analysis · report generation           │
                      └────────────────────────────────────────────┘
```

**Key architectural decisions worth defending in a review:**

- **Vector tiles served directly from PostGIS by Martin** — no tile pre-generation, no ETL, and the map updates the instant a camera record changes.
- **PostgreSQL row-level security** — department isolation enforced by the database, so an application bug cannot cause a cross-department data leak. This is a strong governance answer.
- **Precomputed H3 indices and materialised gap analysis** — the difference between a demo that responds instantly and one that hangs.
- **Two-phase bulk import** — validate-then-commit, so a bad file never half-lands in production data.

## 1.10 Development Requirements

**Prototype / demonstration environment**

| Resource | Specification |
|---|---|
| Compute | 1 VM: 4 vCPU, 16 GB RAM, 100 GB SSD |
| Database | Same VM or separate 4 vCPU / 16 GB with 100 GB SSD |
| GPU | **None** |
| Bandwidth | Modest — no video |
| Cost | Runs comfortably on a single mid-tier cloud instance, or entirely on a developer laptop via Docker Compose |

**Production environment (statewide, ~100k assets, ~500 concurrent users)**

| Component | Specification |
|---|---|
| App servers | 3 × (4 vCPU, 16 GB), autoscaled behind a load balancer |
| Database | Primary 8 vCPU / 32 GB / 500 GB NVMe + 1 streaming replica for reads and reporting |
| Redis | 2 vCPU / 8 GB, with persistence |
| Workers | 2 × (4 vCPU, 8 GB) — scale by probe volume, not user count |
| Object storage | 500 GB initial, growth driven by site photos |
| Tile server | 2 vCPU / 4 GB (Martin is very light) |
| Backup | Daily full + WAL archiving; 30-day PITR window |
| Environments | dev / staging / prod, plus a UAT instance for departmental onboarding trials |

**Team profile:** 1 backend, 1 frontend, 1 GIS/data engineer, 0.5 DevOps. Approximately 8–12 person-weeks for a strong prototype; 4–6 person-months for a production system with departmental onboarding.

## 1.11 Implementation Approach

**Phase 0 — Schema and reference data (days 1–3)**
Define the canonical camera schema (Appendix A) and the controlled vocabularies. Load administrative boundaries into PostGIS and validate geometry. Everything else depends on this being right, so do not rush it — a schema change in week three is expensive.

**Phase 1 — Core registry (days 4–8)**
FastAPI skeleton, SQLAlchemy models, CRUD endpoints, Pydantic validation, Keycloak integration, PostgreSQL RLS policies, audit interceptor. Seed with 1,000 synthetic records. Ship OpenAPI docs from day one.

**Phase 2 — Map (days 9–14)**
React app, MapLibre canvas, Martin tile service, clustering, layer toggles, detail panel, filter sidebar, boundary overlays. Scale seed data to full volume here and fix what breaks — this is where naive implementations fall over.

**Phase 3 — Onboarding (days 15–20)**
Bulk import with column mapping, two-phase validation, Celery job processing, row-level error UI, duplicate resolution workflow, manual entry form with map picker, API onboarding with idempotency. Build the deliberately-defective sample file at the same time as the validator.

**Phase 4 — Health and analytics (days 21–26)**
Probe scheduler, status ingestion endpoint, maintenance log, health dashboard. Then H3 grid generation, weighting layer ingestion, gap-analysis computation and report, ageing report, PDF/XLSX export.

**Phase 5 — Hardening and packaging (days 27–30)**
RBAC test matrix across all roles, audit trail UI, export logging, load test at target volume, API documentation polish, seed dataset finalisation, demo script, deployment packaging.

**Sequencing advice:** build the map early even with fake data. It is the thing everyone looks at, it surfaces performance problems while they are still cheap to fix, and it keeps the team's mental model spatial rather than tabular.

## 1.12 Expected Deliverables

1. **Working registry portal** — deployed, accessible, with GIS map view, full CRUD, search, filter, and export.
2. **Onboarding demonstration** — a scripted walkthrough covering all three paths: a bulk XLSX upload of several thousand rows including deliberate errors, showing validation and correction; a manual entry with map placement; and an API call from a client (Postman collection or a short script).
3. **Sample camera metadata dataset** — 25,000+ realistic records as CSV/XLSX plus GeoJSON, with a data dictionary, generation methodology note, and the defective-rows variant used in the validation demo.
4. **Registry API documentation** — OpenAPI 3.1 specification, rendered Swagger/Redoc, a Postman collection, authentication guide, and an integration guide written for a departmental IT team.
5. **Sample gap-analysis report** — a real generated PDF for a chosen city, showing methodology, weighting, ranked uncovered zones, a map figure, and recommendations. Plus an ageing-infrastructure report.
6. **Supporting documentation** — data dictionary, ER diagram, architecture diagram, RBAC matrix, deployment guide, and a departmental onboarding SOP.

## 1.13 Evaluation and Success Criteria

**Functional**

| Test | Pass criterion |
|---|---|
| Bulk import of 10,000 valid rows | Completes < 60 s, 100% committed, audit entries for all |
| Bulk import with 8% defective rows | Zero rows committed until user resolution; every defect correctly classified |
| Duplicate detection | ≥ 95% of injected duplicates flagged; false-positive rate < 5% |
| Map render at 50,000 cameras | Initial paint < 3 s; pan/zoom stays interactive |
| Spatial polygon query | Correct result set, < 500 ms |
| RBAC isolation | Department A user cannot read, write, or export any Department B record via UI *or* direct API call |
| Audit completeness | Every mutation produces an audit record with old value, new value, actor, timestamp |
| Gap analysis | Report generates for a full district < 10 s from precomputed table; results are spatially sensible on inspection |

**Non-functional**

- API p95 latency < 300 ms for list endpoints at full data volume.
- Tile serving p95 < 150 ms.
- Concurrent user load: 200 simulated users, no error-rate increase (test with k6 or Locust).
- Data quality: 100% of committed records pass mandatory-field and coordinate validation.

**Qualitative (what a reviewer will actually judge)**

- Does the map communicate coverage at a glance, or is it a wall of undifferentiated pins?
- Does the gap-analysis report contain a genuine, defensible insight, or a generic ranking?
- Is the API something a real department could integrate against without a phone call?
- Does the audit trail satisfy a governance reviewer?

## 1.14 Dependencies and Risks

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Ward-level boundary data unobtainable for target cities | Gap analysis loses its most useful granularity | High | Fall back to H3 grid analysis which needs no ward polygons; digitise wards from published maps for the demo city only |
| R2 | Departments will not supply real inventory data | No real dataset to demonstrate | Very High | Fully planned for — synthetic dataset is a first-class deliverable; document the generation methodology to establish credibility |
| R3 | Map performance collapses at full data volume | Demo failure at the worst moment | Medium | Server-side clustering + vector tiles from day one; load-test at 2× target volume |
| R4 | Health probes cannot reach cameras (private departmental networks, NAT, firewalls) | Health monitoring is non-functional in reality | **Very High** | Design status ingestion (push) as the primary mechanism and probing as opportunistic; be explicit about this in the architecture note rather than pretending probes will work |
| R5 | Schema too rigid for departmental variation | Onboarding stalls on unmappable fields | Medium | Include a typed `extended_attributes` JSONB column with a per-department schema registry |
| R6 | Duplicate detection over-merges genuinely distinct cameras | Data corruption | Low | Never auto-merge; always require human confirmation |
| R7 | Coordinate quality in source data is poor (rooftop-level, transposed, or address-only) | Map is misleading | High | Precision scoring, transposition detection heuristic, geocoding backfill, and a visible data-quality score per record |
| R8 | Geocoding rate limits during bulk import | Import stalls | Medium | Self-host Nominatim; cache aggressively; make geocoding optional and async |

**Key assumptions:** departments will nominate nodal officers; existing inventory exists in *some* digital form even if messy; the state can mandate participation; no live video is in scope.

## 1.15 Estimated Complexity

**Overall: 2 / 5 — Moderate.**

This is the most tractable of the four models and the only one fully deliverable at production quality within a short timeline.

| Area | Effort | Difficulty | Notes |
|---|---|---|---|
| Schema and data modelling | High | **Medium-High** | Genuinely the hardest intellectual work here — designing for departmental heterogeneity without free-text chaos |
| CRUD, auth, RBAC | High | Low | Well-trodden; Keycloak removes most of it |
| GIS map at scale | Medium | Medium | Easy to build, easy to build badly; performance is the whole game |
| Bulk import and validation | High | Medium | Deceptively large — the error-handling UX is most of the work |
| Gap analysis | Medium | **Medium-High** | The spatial statistics and the weighting model are where the real value is |
| Health monitoring | Low | Medium | Constrained by network reality more than by code |
| Reporting and export | Medium | Low | |
| Audit and compliance | Medium | Low | Tedious but mechanical |

**Where teams lose points:** treating this as pure CRUD and shipping a map of undifferentiated dots. The differentiators are the quality of the synthetic dataset, the sophistication of the gap-analysis weighting, and the robustness of the bulk-import error experience.
---

# Model 2 — Unified Viewing Platform (Direct Integration)

## 2.1 Problem Statement

Departments run their own Video Management Systems, procured separately, from different vendors, at different times. A state or city command centre that needs situational awareness across departments today has to operate several client applications side by side — a Milestone client for one department, a Hikvision iVMS console for another, a browser-based portal for a third — each with separate credentials, separate camera trees, separate PTZ controls, and no common timeline.

The operational consequences are concrete:

- An operator responding to an incident must know *in advance* which department owns the nearest camera, and which application to open.
- Cross-departmental awareness — following a situation as it moves from a municipal road onto a transport corridor — requires manual coordination between operators.
- Onboarding a new operator means training on four systems.
- Nothing correlates. A vehicle seen on a Traffic camera and again on a Municipal camera is two unrelated observations.

**The binding constraint** is that departmental systems must continue operating exactly as they are. No department will surrender control of its cameras or its recordings, and the model explicitly preserves their independence. The unified platform is a **read-only consumer**, not a replacement.

**The distinguishing constraint** is architectural: this model connects **directly** to each departmental CCTV/VMS endpoint via RTSP, ONVIF, vendor SDK, or vendor API, *without* an intermediate middleware or federation layer. That is what separates it from Model 3.

> **A note on interpreting this constraint.** The model text forbids a middleware/federation layer, yet the accompanying diagram includes a "Unified Stream Gateway" performing relay, transcode, and session control. These are reconcilable: what is excluded is a *federation abstraction tier* that departments must deploy or conform to, and that mediates all communication. Your own stream relay — a process that pulls RTSP and re-packages it for browsers — is a technical necessity, not a federation layer, because browsers cannot consume RTSP. **State this interpretation explicitly in your architecture note.** Demonstrating that you noticed and reasoned about the distinction is worth more than silently building either version.

## 2.2 Objective and Expected Outcome

**Objective.** Deliver a single browser-based operational interface through which authorised users can view, arrange, and search live and recent video from cameras belonging to multiple independent departmental systems, and generate searchable vehicle-movement metadata from those streams — all without central video storage and without modifying any departmental system.

**Expected outcome — the system succeeds when:**

1. An operator logs in once and sees a unified camera tree spanning at least two structurally different source systems.
2. Any camera can be dragged into a configurable video wall (1×1, 2×2, 3×3, 4×4, or custom layouts) and plays in the browser with sub-second to low-second latency, with no plugin installation.
3. Layouts can be saved, named, recalled, and shared with other operators.
4. ANPR runs on designated streams, and every plate read is indexed with plate text, confidence, timestamp, camera ID, and a cropped evidence image.
5. An investigator can enter a partial or complete plate number and receive a chronologically ordered list of every camera that observed it, plotted on a map as a reconstructed route.
6. A vehicle added to a watchlist triggers a real-time alert with a camera jump-link the moment it is detected anywhere on the network.
7. An architecture note demonstrates — with network diagrams and access-pattern documentation — that no departmental system is written to, reconfigured, or load-burdened beyond a defined read budget.

## 2.3 Functional Requirements

### FR-1 Feed aggregation

**FR-1.1 Source connectors.** Support at minimum:

- **Generic RTSP** — direct URL with credentials. The universal fallback; almost every device and VMS supports it.
- **ONVIF Profile S** — device discovery via WS-Discovery, capability query, stream URI retrieval, and PTZ control via the standard service. This is what lets you onboard cameras without knowing vendor specifics.
- **Vendor SDK/API** — at least one implemented for real (Hikvision ISAPI over HTTP is the most accessible and best documented for prototype purposes; Dahua HTTP API is a close second). Milestone Integration Platform SDK and Genetec SDK are the enterprise cases to *document* even if you cannot obtain licences.
- **HLS/DASH pull** — for departmental systems that already publish web-playable streams.

**FR-1.2 Camera onboarding.** Manual URL entry, ONVIF network scan with discovered-device list, and bulk import from the Model 1 registry (`GET /api/v1/cameras`) — this is the natural integration point between the two models and should be demonstrated.

**FR-1.3 Connection management.** Per-source connection pooling with a configurable maximum concurrent session count, so you never exceed a department's licensed stream limit. Exponential-backoff reconnection. Health state per feed (`connected` / `reconnecting` / `failed` / `unauthorised`). Credential storage in a secrets vault, never in the database in plaintext.

**FR-1.4 Lazy streaming.** **Critical design rule:** pull a stream from a department only while at least one operator is actually watching it, or while it is designated for analytics. Never maintain 500 idle connections. This is both a resource decision and the core of your "we do not burden departmental systems" argument.

### FR-2 Stream relay and delivery

- **Transport conversion:** RTSP (and vendor formats) → **WebRTC** for the live wall, **LL-HLS** as a fallback and for higher-scale or higher-latency-tolerant viewing.
- **Codec handling:** pass through H.264 untouched wherever possible. H.265 requires transcoding for broad browser compatibility — this is the single largest CPU/GPU cost in the system, so detect codec at connect time and route accordingly.
- **Adaptive substreams:** request the camera's low-resolution substream for grid views and the main stream only for a maximised single view. A 4×4 grid of main streams is wasteful and unnecessary; nobody can perceive 4 MP detail in a 480-pixel tile.
- **Session control:** per-user stream quotas, idle timeout with automatic teardown, and forced release on tab close or disconnect.

### FR-3 Video analytics

**FR-3.1 ANPR.** Two-stage pipeline — plate detection (object detector) followed by plate recognition (OCR/sequence model) — running on a configurable subset of streams at a sampled frame rate (5–10 fps is sufficient; 25 fps is wasted compute). Output per detection: plate string, per-character and overall confidence, bounding box, source camera, UTC timestamp, and a cropped plate image plus a wider vehicle context crop.

**FR-3.2 Event tagging.** Manual tagging by operators (mark a time range on a camera with a category, note, and severity) and automatic tagging from analytics events. Tags are searchable and appear on a timeline.

**FR-3.3 Camera-wise indexing.** Every generated event is indexed against its camera, so any camera's history can be browsed as a timeline of detections and tags without touching video.

**FR-3.4 Searchable vehicle movement records.** The flagship capability. Given a plate query (exact, partial, or fuzzy to tolerate OCR error), return all sightings ordered by time, with camera location, timestamp, evidence crop, and a map rendering of the inferred route with speed and travel-time between consecutive sightings.

**FR-3.5 Alerts.** Vehicle watchlists (individual plates, plate patterns, or uploaded lists) with alert delivery in-app, by email, and by webhook. Alert includes camera, time, evidence image, and a one-click jump to that camera's live view.

### FR-4 Operator interface

- Configurable video walls with saved layouts, per-slot camera assignment, and a spot-monitor pattern (click any grid tile to promote it to a large view).
- Camera tree grouped by department, location, and type, with search.
- Map view with cameras plotted, click-to-view.
- PTZ control where the source supports it (ONVIF PTZ service or vendor API) — with a clear permission gate, since PTZ is a *write* to a departmental device and is the one place this model touches their system. Make this opt-in per department.
- Timeline scrubbing over the department's own recorded video where the source VMS exposes playback (ONVIF Profile G, or vendor playback API) — retrieved on demand, never cached centrally.
- Alert panel with acknowledge/dismiss and audit.
- Search interface for plates, events, and tags.

### FR-5 Access control and audit

Department-scoped RBAC as in Model 1, plus: per-camera view permissions, PTZ permission separate from view permission, and **every stream view logged** — who watched which camera, when, and for how long. In a surveillance context this log is a compliance requirement, not a nicety.

## 2.4 Recommended Tech Stack

| Layer | Recommendation | Rationale and alternatives |
|---|---|---|
| **Stream relay** | **MediaMTX** (formerly rtsp-simple-server) | Single Go binary; ingests RTSP/RTMP/SRT and publishes WebRTC (WHEP), HLS, LL-HLS and RTSP simultaneously. Has a control API for dynamic path management. By far the fastest path to a working relay. MIT licensed. |
| **Alternative relay** | **go2rtc** | Even lighter, excellent codec negotiation and camera compatibility, zero-copy where possible. Strong choice; smaller feature surface than MediaMTX. |
| **Alternative relay (enterprise)** | Janus Gateway (streaming plugin), LiveKit, Pion (custom Go), Ant Media Server | Janus is battle-tested but heavier to operate. LiveKit is excellent for SFU workloads but is designed for conferencing topologies rather than one-way camera fan-out. Build on Pion only if you need something the others cannot do. |
| **Transcoding / frame extraction** | **FFmpeg** (`libavcodec`) with NVENC/NVDEC hardware acceleration; **GStreamer** for complex pipelines | Hardware decode is what makes multi-stream analytics affordable. |
| **ONVIF** | Python: `onvif-zeep` / `onvif-zeep-async`, or the newer `onvif-python`; discovery via `WSDiscovery`. Node: `onvif` npm package | Test against real devices early — vendor ONVIF conformance varies enormously. |
| **Vendor SDK** | Hikvision ISAPI (plain HTTP + digest auth, well documented) as the primary demonstration; Dahua HTTP API second | Do not build your demo around an SDK you cannot obtain. |
| **Object detection (plate)** | **RT-DETR** or **YOLOX** (both Apache-2.0) | ⚠️ **Licensing:** Ultralytics YOLOv8/v11 is **AGPL-3.0**, which is a genuine problem for a government deployment that does not want to publish source. Use it for prototyping if you must, but recommend an Apache-2.0 model for production and say so explicitly — this is a detail evaluators with legal awareness notice. |
| **Plate OCR** | **PaddleOCR** (Apache-2.0), or a purpose-trained **CRNN**/**PARSeq** on cropped plates | PaddleOCR out of the box is a good baseline. A small model fine-tuned on Indian plates will substantially outperform it. **EasyOCR** is the quickest baseline of all. |
| **Ready-made ANPR** | **OpenALPR** (open core), **FastALPR**, or commercial (Plate Recognizer, Rekor) | Use an off-the-shelf engine as your accuracy baseline and to de-risk the demo; ship your own model as the differentiator. |
| **Inference serving** | **NVIDIA Triton Inference Server**, or **NVIDIA DeepStream** for the full decode→infer→track pipeline | DeepStream is dramatically more efficient for many concurrent streams but has a steeper learning curve. For ≤ 8 streams, plain PyTorch + FFmpeg is fine. |
| **Runtime optimisation** | TensorRT (NVIDIA), ONNX Runtime, OpenVINO (Intel CPU/iGPU) | 2–5× throughput gain over raw PyTorch for the same model. |
| **Object tracking** | ByteTrack or BoT-SORT | Deduplicates the same vehicle across consecutive frames — without this you record the same plate 40 times. |
| **Backend** | **Python 3.12 + FastAPI** for API and analytics orchestration; **Go** for the relay control plane if throughput demands it | FastAPI's async model suits the many-concurrent-connections shape of this workload. |
| **Message bus** | **Redis Streams** (prototype) or **Kafka / Redpanda** (production) | Decouples inference workers from indexing and alerting. Redpanda is Kafka-compatible with far lower operational overhead. |
| **Search index** | **OpenSearch** or **Elasticsearch** | Fuzzy plate matching, time-range queries, and aggregations. Configure an n-gram analyser on the plate field so partial searches work. |
| **Database** | **PostgreSQL 16 + PostGIS** | Cameras, users, layouts, watchlists, audit. PostGIS for camera positions and route rendering. |
| **Time-series (optional)** | TimescaleDB or ClickHouse | If detection volume is high, ClickHouse handles event analytics far better than Postgres. |
| **Object storage** | **MinIO** | Evidence crops only — never full video. |
| **Frontend** | React 18 + TypeScript + Vite | |
| **Video playback** | Native `RTCPeerConnection` with **WHEP** signalling (WebRTC); **hls.js** for HLS fallback | MediaMTX exposes WHEP endpoints directly — you can play a stream with ~40 lines of client code. |
| **Grid layout** | `react-grid-layout` or CSS Grid with a custom drag layer | |
| **Map** | MapLibre GL JS + deck.gl for route rendering | |
| **Auth** | Keycloak (OIDC) | |
| **Secrets** | HashiCorp Vault, or SOPS + age for a lighter prototype | Camera credentials must not sit in the database in plaintext. |
| **Deployment** | Docker Compose (prototype) → Kubernetes with the NVIDIA device plugin (production) | |

## 2.5 Datasets Required

### D-1 ANPR training and evaluation data (essential)

Indian number plates are a genuinely distinct recognition problem: the `XX ## XX ####` format, a mix of embossed HSRP and hand-painted plates, widely varying fonts, state-code prefixes, two-line motorcycle plates, and heavy occlusion and dirt. A model trained on European or Chinese plates will underperform badly.

**Recommended dataset stack:**

| Purpose | Dataset | Notes |
|---|---|---|
| Plate **detection** (Indian) | [Roboflow Universe — Indian Number Plate datasets](https://universe.roboflow.com/anpr-gfpt1/indian-number-plate-bkaj2) and [DataCluster Labs Indian Number Plates](https://universe.roboflow.com/datacluster-labs-agryi/indian-number-plates-9oobq) | Free, YOLO-format, immediately usable. Several thousand annotated images. Quality varies — inspect before trusting. |
| Plate **detection + recognition** (Indian) | [`sanchit2843/Indian_LPR`](https://github.com/sanchit2843/Indian_LPR) | Purpose-built Indian LPR project with dataset and trained weights. Strong starting point. |
| Indian plates, raw images | [DataCluster Labs on Hugging Face](https://huggingface.co/datasets/Dataclusterlabspvtltd/indian-number-plates-dataset) | Real-world captures across Indian cities. |
| **Pretraining** at scale | **CCPD** (Chinese City Parking Dataset — ~250k in the original ECCV 2018 release, 300k+ in the current repository) | Chinese plates, but excellent for pretraining detection and OCR backbones before fine-tuning on smaller Indian sets. This transfer-learning step is the highest-return single decision in your ANPR pipeline. |
| Benchmark / cross-check | **UFPR-ALPR** (Brazilian), **OpenALPR benchmark**, **AOLP** (Taiwanese) | Useful for validating that your pipeline generalises. |
| Vehicle detection | **UA-DETRAC**, **BDD100K**, COCO (vehicle classes) | For the vehicle-detection stage feeding plate detection. |
| Vehicle re-identification (advanced) | [**VeRi-776**](https://github.com/JDAI-CV/VeRidataset), **VERI-Wild**, NVIDIA **AI City Challenge** datasets | Enables tracking a vehicle across cameras *by appearance* when the plate is unreadable — a strong differentiator if you have time. |

### D-2 Synthetic augmentation (strongly recommended)

Real Indian ANPR data is scarce. Generate synthetic plates: render the correct Indian font (HSRP uses a defined typeface — Charles Wright derivative), apply realistic perspective warp, motion blur, varying illumination, rain and dust artefacts, partial occlusion, and composite onto real vehicle crops. A synthetic-plus-real training mix routinely beats real-only when real data is under a few thousand images. Libraries: `albumentations` for augmentation, `Pillow`/`OpenCV` for rendering.

### D-3 Test video footage (essential for demonstration)

You need actual traffic video to demo against. Sources:

- Public webcam and traffic-camera streams (verify terms of use before recording).
- Dashcam and traffic footage on YouTube/Vimeo under permissive licences.
- **Self-captured footage** — a phone on a tripod at a roadside for an hour produces the most convincing demo material, and it is unambiguously yours to use.
- Traffic datasets with video: UA-DETRAC, AI City Challenge.
- Test RTSP endpoints: `rtsp.stream` and Wowza's public test streams for connectivity testing.

### D-4 Camera inventory

Reuse Model 1's synthetic registry — this demonstrates the intended composition of the two models.

## 2.6 Data Sources

| Need | Source | Access |
|---|---|---|
| Annotated Indian plate images | Roboflow Universe, Hugging Face Datasets, Kaggle | Free; check per-dataset licence |
| Large-scale plate pretraining | CCPD (GitHub), UFPR-ALPR (request form) | Free / academic |
| Vehicle detection & re-ID | UA-DETRAC, BDD100K (Berkeley), VeRi-776 (GitHub), AI City Challenge (NVIDIA, registration) | Free / academic registration |
| Pretrained weights | Hugging Face Hub, PaddleOCR model zoo, Ultralytics hub, OpenALPR | Free; **check licence** — see the AGPL note in §2.4 |
| Live test RTSP | `rtsp.stream`, Wowza public test streams, `bigbuckbunny` sample streams | Free |
| Real camera hardware | Any ONVIF-compliant IP camera (a ₹2,000–4,000 CP Plus or Hikvision unit) | Purchase — **strongly recommended**, one real camera transforms the credibility of the demo |
| Simulated second VMS | Self-hosted **ZoneMinder**, **Shinobi**, or **Frigate** fed by looping video files | Free — this is how you satisfy "at least two different systems" without two real departments |
| Vendor API documentation | Hikvision ISAPI developer portal, Dahua developer portal, ONVIF specifications (onvif.org) | Free registration |
| Camera positions | Model 1 registry, or OSM-derived synthetic | Internal |

> **How to satisfy "at least two different systems" credibly:** stand up **ZoneMinder** on one host and **Frigate** (or Shinobi) on another, feed each with looping video files exposed as RTSP via MediaMTX or FFmpeg, and integrate them through genuinely different code paths — ONVIF for one, direct RTSP + vendor-style HTTP API for the other. Add one real physical IP camera as a third source if budget allows. This is architecturally honest: they *are* different systems with different APIs, and it demonstrates exactly the heterogeneity the model exists to handle.

## 2.7 APIs and Services Required

### Consumed

| Interface | Protocol | Purpose |
|---|---|---|
| Departmental camera / VMS streams | **RTSP** (RFC 2326), RTP/RTCP | Live video retrieval |
| ONVIF Device Service | SOAP/HTTP | Capabilities, device info |
| ONVIF Media Service | SOAP/HTTP | Profile enumeration, stream URI retrieval |
| ONVIF PTZ Service | SOAP/HTTP | Pan/tilt/zoom control |
| ONVIF Events Service | SOAP/HTTP + WS-BaseNotification | Motion and device events from cameras |
| ONVIF Profile G / Replay Service | SOAP/HTTP + RTSP | On-demand playback of departmental recordings |
| WS-Discovery | SOAP over UDP multicast | Automatic camera discovery on a subnet |
| Hikvision ISAPI | HTTP + digest auth | Device info, streams, PTZ, events |
| Dahua HTTP API | HTTP | Equivalent |
| Model 1 Registry API | REST | Camera inventory import |
| Notification gateway | SMTP / SMS / webhook | Alert delivery |
| VAHAN RC lookup | REST (via NIC or a commercial aggregator) | Owner/vehicle enrichment on plate hits — **see §0.2.2; mock this** |

### Exposed

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/sources` | Register a departmental source system |
| `POST /api/v1/sources/{id}/discover` | ONVIF scan of a source network |
| `GET /api/v1/cameras` | Unified camera tree across all sources |
| `POST /api/v1/streams/{cameraId}/session` | Request a viewing session; returns WHEP/HLS URL and session token |
| `DELETE /api/v1/streams/session/{id}` | Release a stream session |
| `POST /api/v1/cameras/{id}/ptz` | PTZ command (permission-gated) |
| `GET /api/v1/playback/{cameraId}?from=&to=` | Proxy to source VMS playback |
| `GET/POST/PUT /api/v1/layouts` | Video wall layout management |
| `GET /api/v1/detections?plate=&from=&to=&camera=` | Plate/event search |
| `GET /api/v1/vehicles/{plate}/track` | Movement reconstruction — sightings + route |
| `GET/POST/DELETE /api/v1/watchlists` | Watchlist management |
| `GET /api/v1/alerts` + WebSocket `/ws/alerts` | Alert feed |
| `POST /api/v1/tags` | Manual event tagging |
| `GET /api/v1/analytics/config` | Which cameras have analytics enabled |

## 2.8 Data Processing and ML Approach

### 2.8.1 Pipeline

```
RTSP source
  → FFmpeg/GStreamer decode (NVDEC hardware decode where available)
  → frame sampler (5–10 fps, not full rate)
  → [Stage 1] vehicle detection (RT-DETR / YOLOX)
  → crop vehicle region
  → [Stage 2] plate detection within vehicle crop
  → plate crop → perspective rectification (four-point transform)
  → [Stage 3] plate OCR (PaddleOCR / PARSeq / CRNN)
  → format validation against Indian plate grammar
  → [Stage 4] multi-object tracking (ByteTrack) for temporal deduplication
  → confidence-weighted voting across the track's frames → single best read
  → emit event to message bus
  → index in OpenSearch + persist crop to MinIO + evaluate watchlists
```

**Why two-stage detection:** detecting vehicles first and searching for plates only inside vehicle crops improves small-plate recall substantially and reduces false positives from signage and text on buildings.

**Why track-level voting matters:** a vehicle is visible for 20–60 frames. Reading the plate independently each frame gives you 40 noisy strings. Aggregating across the track with confidence weighting — per-character majority voting — typically lifts end-to-end accuracy by 10–20 percentage points over single-frame reading. **This is the single highest-value engineering decision in the ANPR pipeline** and is frequently skipped.

### 2.8.2 Indian plate grammar post-processing

Enforce and correct against the known format `[State 2 letters][District 1–2 digits][Series 1–3 letters][Number 4 digits]`, plus BH-series and older formats.

Resolve the classic OCR confusions using positional knowledge: `O↔0`, `I↔1`, `S↔5`, `B↔8`, `Z↔2`, `G↔6`, `D↔0`. Because you know which positions must be alphabetic and which numeric, most of these confusions are deterministically correctable. Validate the state code against the list of valid RTO state prefixes. This post-processing step alone is typically worth 5–10 points of accuracy and costs almost nothing.

### 2.8.3 Training approach

1. **Pretrain** the detector on CCPD (large) — learns "what a plate looks like" generically.
2. **Fine-tune** on the Indian datasets, augmented with synthetic plates.
3. **Train the OCR head separately** on cropped, rectified plates — this decoupling lets you iterate on recognition without re-running detection training.
4. **Augment** aggressively: rotation ±15°, perspective warp, motion blur, brightness/contrast jitter, JPEG compression artefacts, rain/dust overlays, partial occlusion. Real cameras see all of these.
5. **Validate** on a held-out set drawn from *your actual demo footage*, not just the public test split — domain shift between dataset images and your camera angles is the biggest source of demo-day disappointment.
6. **Export** to ONNX → TensorRT for deployment. Expect 2–4× throughput improvement.

### 2.8.4 Realistic accuracy expectations

State these honestly in your documentation; overclaiming is easily caught.

| Condition | Realistic plate-read accuracy |
|---|---|
| Good angle, daylight, clean HSRP plate, < 40 km/h | 90–96% |
| Night with IR illumination, clean plate | 80–90% |
| Oblique angle, dirty or damaged plate | 55–75% |
| Motorcycle two-line plates | 50–75% |
| Hand-painted / non-standard plates | 30–60% |
| Detection-only (plate located, not read) | 95%+ |

Report **character-level accuracy**, **exact full-plate match**, and **match-within-one-character** separately. The last is the operationally useful one, because fuzzy search recovers near-misses.

### 2.8.5 Route reconstruction

Given sightings of plate P at cameras C₁…Cₙ with timestamps t₁…tₙ:

1. Sort by timestamp.
2. For each consecutive pair, compute great-circle distance and elapsed time → implied average speed.
3. Flag physically impossible transitions (implied speed > 150 km/h) as probable misreads and surface them as low-confidence rather than silently dropping them.
4. Optionally snap the path to the OSM road network using a routing engine (**OSRM** or **Valhalla**) so the drawn route follows roads rather than straight lines. This is a small effort with a large visual payoff in a demo.

## 2.9 System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  DEPARTMENTAL SYSTEMS (untouched, independently operated)            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ Dept A VMS   │  │ Dept B VMS   │  │ Dept C direct│              │
│  │ (Milestone)  │  │ (Hikvision)  │  │ IP cameras   │              │
│  │ own storage  │  │ own storage  │  │ own NVR      │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
└─────────┼─────────────────┼─────────────────┼──────────────────────┘
          │ RTSP/ONVIF      │ ISAPI/RTSP      │ ONVIF/RTSP
          │ READ-ONLY       │ READ-ONLY       │ READ-ONLY
┌─────────▼─────────────────▼─────────────────▼──────────────────────┐
│  SECURE ACCESS LAYER — per-department VPN/VLAN, credential vault,   │
│  connection pool with licensed-session cap, health monitoring       │
└─────────┬──────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────────────────┐
│  UNIFIED STREAM GATEWAY (MediaMTX / go2rtc)                         │
│  ┌──────────────┐ ┌───────────────┐ ┌────────────┐ ┌────────────┐ │
│  │ RTSP ingest  │ │ Codec detect  │ │ Transcode  │ │ Session &  │ │
│  │ + reconnect  │ │ + substream   │ │ (FFmpeg/   │ │ quota mgmt │ │
│  │              │ │   selection   │ │  NVENC)    │ │            │ │
│  └──────────────┘ └───────────────┘ └────────────┘ └────────────┘ │
│  Publishes: WebRTC (WHEP) · LL-HLS · internal RTSP for analytics    │
└─────┬───────────────────────────────────────────────┬──────────────┘
      │ (viewer traffic)                              │ (analytics tap)
      │                          ┌────────────────────▼──────────────┐
      │                          │  ANALYTICS WORKERS (GPU)          │
      │                          │  decode → sample → detect →       │
      │                          │  OCR → track → vote → emit        │
      │                          │  Triton / DeepStream              │
      │                          └────────────────────┬──────────────┘
      │                                               │
      │                          ┌────────────────────▼──────────────┐
      │                          │  EVENT BUS (Kafka / Redis Streams)│
      │                          └──┬──────────┬──────────┬──────────┘
      │                             │          │          │
      │              ┌──────────────▼──┐ ┌─────▼─────┐ ┌──▼─────────┐
      │              │ Indexer         │ │ Watchlist │ │ Evidence   │
      │              │ → OpenSearch    │ │ evaluator │ │ → MinIO    │
      │              └──────────────┬──┘ └─────┬─────┘ └────────────┘
      │                             │          │
┌─────▼─────────────────────────────▼──────────▼─────────────────────┐
│  APPLICATION API (FastAPI) — auth · sessions · search · alerts      │
│  PostgreSQL+PostGIS (cameras, users, layouts, watchlists, audit)    │
└─────┬───────────────────────────────────────────────────────────────┘
      │
┌─────▼───────────────────────────────────────────────────────────────┐
│  OPERATOR UI (React) — video wall · map · search · alerts · timeline│
└─────────────────────────────────────────────────────────────────────┘
```

**Non-disturbance guarantees to document explicitly** (this maps directly to a required deliverable):

1. All departmental interactions are **read-only** except optional, per-department-opt-in PTZ.
2. **No writes** to departmental configuration, user accounts, or storage.
3. **Bounded session count** per source, configured never to exceed licensed limits.
4. **Lazy connection** — streams pulled only when watched or under analytics.
5. **Read-only service accounts** on each departmental system, with credentials held in a vault and rotatable by the department.
6. **Network isolation** — one-way initiated connections from the platform into departmental networks over dedicated VPN/VLAN; departmental systems never need to reach the platform.
7. **Measured load** — publish the actual bandwidth and session count consumed per department, as a monitored, alertable metric.

## 2.10 Development Requirements

**Prototype (4–8 cameras, ANPR on 2–4 streams)**

| Resource | Specification |
|---|---|
| Application host | 8 vCPU, 32 GB RAM, 200 GB SSD |
| **GPU** | 1 × NVIDIA GPU with ≥ 8 GB VRAM — RTX 3060/4060, T4, or L4. A T4 or L4 is ideal (low power, NVENC/NVDEC, data-centre form factor) |
| Network | 100 Mbps+ |
| Cameras | 1–2 physical ONVIF IP cameras (highly recommended) + simulated sources via MediaMTX/FFmpeg loops |
| Cloud equivalent | AWS `g4dn.2xlarge`, GCP `n1-standard-8` + T4, or Azure `NC4as_T4_v3` |

**Production (per regional node, ~500 cameras viewed, ~100 under analytics)**

| Component | Specification |
|---|---|
| Gateway nodes | 3 × (16 vCPU, 64 GB) — CPU-bound if transcoding H.265 |
| GPU analytics nodes | 4–8 × NVIDIA L4 or A30. **Planning estimate: 25–40 concurrent 1080p streams per L4** at 5–10 fps analytic rate with TensorRT + DeepStream — *benchmark this yourself, it varies hugely with model size and frame rate* |
| Bandwidth | ~2 Mbps per concurrently viewed stream + ~1 Mbps per analytics substream. 500 viewed + 100 analysed ≈ 1.1 Gbps sustained |
| Database | 8 vCPU / 32 GB / 500 GB |
| OpenSearch | 3 nodes × (8 vCPU, 32 GB, 1 TB) — sized by detection volume, not camera count |
| Object storage | Evidence crops at roughly 30 KB each; 100 cameras × 500 detections/day × 30 KB ≈ 1.5 GB/day ≈ 550 GB/year |
| Kafka | 3 brokers × (4 vCPU, 16 GB) |

**Team profile:** 1 video/streaming engineer, 1 ML engineer, 1 backend, 1 frontend, 0.5 DevOps. Approximately 16–24 person-weeks for a strong prototype.

## 2.11 Implementation Approach

**Phase 0 — De-risk the streaming path first (days 1–4).** Before writing any application code, prove end-to-end that you can get an RTSP stream into a browser. Stand up MediaMTX, point it at a test RTSP source, and play it in a plain HTML page over WHEP. **If this does not work, nothing else matters.** Teams that build the UI first and leave streaming for week three routinely fail.

**Phase 1 — Source connectors (days 5–10).** ONVIF discovery and stream URI retrieval; generic RTSP with credentials; one vendor HTTP API. Connection manager with pooling, backoff, and health state. Credential vault.

**Phase 2 — Simulated environment (days 8–12, parallel).** Stand up ZoneMinder and Frigate as two distinct "departmental systems," each serving looped video over RTSP. This is your test bed for everything downstream and removes your dependency on real departmental cooperation.

**Phase 3 — Viewer (days 11–18).** React app, WHEP playback component, video wall grid with drag-and-drop, layout save/recall, camera tree, map view, session lifecycle management. Handle the ugly cases: stream failure, reconnection, tab backgrounding, and cleanup on close.

**Phase 4 — ANPR (days 15–26, parallel with Phase 3).** Frame extraction pipeline → baseline with an off-the-shelf engine to establish a working end-to-end path early → train and fine-tune the custom detector and OCR → tracking and track-level voting → grammar post-processing → benchmark against your own footage → TensorRT export.

**Phase 5 — Search and alerts (days 24–30).** Event bus, OpenSearch indexing with fuzzy plate matching, evidence storage, search UI, movement reconstruction with map route, watchlist management, real-time alert delivery over WebSocket.

**Phase 6 — Hardening and evidence (days 29–35).** Non-disturbance architecture note with network diagrams and measured load figures, RBAC, view-audit logging, load testing, accuracy benchmark report, demo script and rehearsal.

**Sequencing advice:** run streaming and ANPR as two parallel tracks that meet in Phase 5. They have almost no shared code and blocking one on the other wastes half your calendar.

## 2.12 Expected Deliverables

1. **Unified viewer** connected to at least two structurally different source systems, demonstrably using different integration paths (ONVIF vs vendor API), with configurable multi-camera walls and live browser playback.
2. **ANPR demonstration** on live and recorded feeds — plates detected and read in real time, with visible bounding boxes, confidence scores, and evidence crops.
3. **Searchable metadata dashboard** — plate search (exact, partial, fuzzy), time and camera filters, results with evidence images, and multi-camera movement reconstruction rendered on a map.
4. **Architecture note on non-disturbance** — network topology diagrams, access-pattern documentation, the seven guarantees from §2.9 with evidence for each, measured bandwidth and session counts per source, and a statement of what the platform *cannot* do to a departmental system.
5. **ANPR accuracy benchmark report** — methodology, test-set description, per-condition accuracy table, failure-case gallery, and honest limitations.
6. **API documentation** — OpenAPI spec and integration guide.
7. **Deployment package** — Docker Compose / Helm charts, configuration reference, camera-onboarding runbook.

## 2.13 Evaluation and Success Criteria

**Streaming**

| Metric | Target |
|---|---|
| Glass-to-glass latency (WebRTC) | < 1 s LAN, < 2 s WAN |
| Glass-to-glass latency (LL-HLS fallback) | < 5 s |
| Time to first frame on camera open | < 3 s |
| 4×4 grid, 16 concurrent streams | Stable for 30 min, no memory growth, no frame stall |
| Reconnection after source outage | Automatic within 15 s |
| Stream sessions per source | Never exceeds configured cap (verify under load) |

**ANPR**

| Metric | Target |
|---|---|
| Plate detection recall (good conditions) | ≥ 95% |
| Full-plate exact match (good conditions) | ≥ 90% |
| Within-one-character match (good conditions) | ≥ 95% |
| False-positive rate | < 2% |
| End-to-end processing latency | < 500 ms per detection |
| Throughput per GPU | ≥ 20 concurrent 1080p streams at 10 fps analytic rate |
| Duplicate suppression | One event per vehicle pass, not one per frame |

**Search and correlation**

- Plate search across 1M+ indexed detections returns in < 1 s.
- Fuzzy search recovers ≥ 80% of plates with a single OCR character error.
- Movement reconstruction across ≥ 3 cameras renders correctly with plausible speeds.
- Watchlist alert fires within 5 s of detection.

**Non-disturbance verification (test this explicitly and document it)**

- Departmental VMS CPU, memory, and recording continuity measured before, during, and after platform operation — no material change.
- Confirm no writes occur: audit the service account's permissions on the source system and show it is read-only.
- Simulate platform failure and confirm departmental systems are entirely unaffected.

## 2.14 Dependencies and Risks

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | No access to any real departmental VMS | Cannot demonstrate the core premise | **Very High** | Simulated environment (ZoneMinder + Frigate) planned as the primary path; treat real access as a bonus |
| R2 | Vendor ONVIF implementations are non-conformant | Connectors fail on real hardware | **High** | Test against multiple vendors early; always keep direct RTSP as a fallback path; log and document conformance gaps |
| R3 | Vendor SDKs are licensed and unobtainable | Cannot build the enterprise connectors | High | Use HTTP-based APIs (Hikvision ISAPI, Dahua) which need no SDK; document the SDK adapter contract for the ones you cannot obtain |
| R4 | H.265 transcoding overwhelms available compute | Streams stutter or fail at scale | High | Prefer substreams; pass through H.264; use hardware NVENC/NVDEC; cap concurrent transcodes and degrade gracefully |
| R5 | ANPR accuracy is poor on real Indian plates | Flagship feature underwhelms | Medium-High | CCPD pretraining + synthetic augmentation + track-level voting + grammar post-processing; benchmark honestly and report limitations rather than overclaiming |
| R6 | Departmental network access blocked by firewall/NAT | Cannot reach cameras at all | High | Design for a departmental-side relay/jump host initiated outbound; document network prerequisites as an explicit dependency |
| R7 | Exceeding licensed concurrent-stream limits on a departmental VMS | Degrades or breaks the department's own operations — the worst possible outcome | Medium | Hard session caps, lazy connection, per-source quota configuration, and load monitoring with alerts |
| R8 | GPU unavailable or too small | Analytics cannot run at demonstrable scale | Medium | Design analytics as a separately-scalable service; support CPU inference with OpenVINO at reduced fps as a degraded mode |
| R9 | Clock drift between cameras | Movement reconstruction produces impossible sequences | Medium | Mandate NTP; detect and flag implausible transitions; record ingest time alongside camera time |
| R10 | Privacy/legal challenge to plate retention | Programme delay | Medium | Retention policy with automatic expiry, purpose-coded search, full access audit, DPDP alignment note |

**Key dependencies:** network reachability to departmental systems; read-only service accounts issued by each department; NTP across all sources; GPU availability; camera credentials.

## 2.15 Estimated Complexity

**Overall: 4 / 5 — High.**

| Area | Effort | Difficulty | Notes |
|---|---|---|---|
| RTSP/ONVIF integration | High | **High** | Vendor inconsistency is relentless; expect to spend real time on edge cases |
| Stream relay and transcode | High | **High** | MediaMTX removes much of it, but codec, latency, and scale issues are genuinely hard |
| Video wall UI | Medium | Medium | Playback is easy; lifecycle management under 16 concurrent streams is not |
| ANPR model | High | **High** | Achieving demo-quality accuracy on Indian plates is real ML work |
| Tracking and deduplication | Medium | Medium | Off-the-shelf trackers work well |
| Search and indexing | Medium | Low-Medium | OpenSearch does the heavy lifting |
| Movement reconstruction | Medium | Medium | Straightforward logic, high demo value |
| Non-disturbance evidence | Low | Low | Documentation-heavy, but a required deliverable — do not skip it |

**Where teams lose points:** leaving streaming until late and discovering in week three that RTSP-to-browser is harder than expected; and building a viewer with no analytics, which is a much less compelling story than a viewer with working plate search. If time is short, **cut the number of cameras, not the ANPR**.
---

# Model 3 — Middleware / Federation Layer

## 3.1 Problem Statement

The state's CCTV estate is not merely fragmented at the viewing layer — it is fragmented at the *information* layer. Each departmental VMS holds camera metadata, motion events, device alarms, analytics results, recording indices, and user activity in its own proprietary schema, reachable only through its own proprietary interface. Nothing crosses departmental boundaries.

The consequences are structural rather than cosmetic:

- **No cross-system correlation.** An ANPR hit in the Transport system and a perimeter-breach alarm in the Municipal system are two isolated facts. Nothing can observe that they are three minutes and two kilometres apart and therefore probably one incident.
- **Every new consumer re-integrates from scratch.** A GIS dashboard, an analytics engine, an incident-management system, and a mobile app each independently write four vendor-specific integrations. Integration cost grows as *(consumers × sources)* rather than *(consumers + sources)*.
- **No common event vocabulary.** "Motion detected" means different things, carries different fields, and arrives by different transports in each system.
- **Onboarding a new vendor is a project.** When a department procures a fifth VMS, every downstream consumer must change.
- **No unified operational workflow.** An alert cannot be acknowledged, assigned, escalated, and resolved consistently, because there is no place where all alerts exist.

**The distinguishing architectural decision:** unlike Model 2, this solution does **not** connect directly to each departmental system from the consuming application. A middleware/federation layer sits between them, absorbing all vendor heterogeneity and exposing **one** normalised interface upward — to dashboards, AI services, mobile applications, and any future consumer.

This inverts the integration economics. It also means the product is the *platform*, not the screen. The unified dashboard is a reference consumer that proves the platform works.

## 3.2 Objective and Expected Outcome

**Objective.** Build an extensible integration platform that connects to multiple heterogeneous departmental VMS systems through pluggable adapters, normalises their camera metadata and event streams into a common canonical model, correlates events across system boundaries into unified incidents, and exposes a single well-documented API and event stream for all downstream consumers — without replacing or modifying any departmental system.

**Expected outcome — the system succeeds when:**

1. Two or more structurally different VMS platforms are federated through the middleware, each via its own adapter, with no source-specific code anywhere outside its adapter.
2. A single API call returns the unified camera inventory across all federated systems in one canonical schema.
3. Events from all sources arrive on a single normalised event stream in real time, with a common envelope and typed payloads.
4. The correlation engine links events from **different** source systems into a single incident based on spatial, temporal, and semantic rules — and this is demonstrated live.
5. A unified dashboard shows correlated incidents with full operational workflow: acknowledge → assign → escalate → resolve, with an audit trail.
6. A new vendor adapter can be added by implementing a documented interface and dropping in a plugin, with **zero changes to the middleware core** — and this is proven by actually doing it.
7. Departments retain complete operational control; the middleware holds read-only credentials and can be disconnected without any effect on departmental operations.

## 3.3 Functional Requirements

### FR-1 Adapter / plugin architecture

**FR-1.1 Adapter contract.** A formally specified interface every adapter implements:

```python
class VMSAdapter(Protocol):
    # Identity & lifecycle
    adapter_id: str
    supported_capabilities: set[Capability]

    async def connect(self, config: SourceConfig) -> ConnectionHandle: ...
    async def health_check(self) -> HealthStatus: ...
    async def disconnect(self) -> None: ...

    # Discovery
    async def list_cameras(self) -> list[CanonicalCamera]: ...
    async def get_camera(self, native_id: str) -> CanonicalCamera: ...
    async def list_sites(self) -> list[CanonicalSite]: ...

    # Events
    async def subscribe_events(self) -> AsyncIterator[CanonicalEvent]: ...
    async def get_events(self, since: datetime, until: datetime) -> list[CanonicalEvent]: ...

    # Media references (URIs only — the middleware never proxies pixels)
    async def get_stream_uri(self, native_id: str, profile: str) -> StreamReference: ...
    async def get_playback_uri(self, native_id: str, t0: datetime, t1: datetime) -> StreamReference: ...
    async def get_snapshot(self, native_id: str) -> bytes: ...

    # Optional control (capability-gated)
    async def ptz_command(self, native_id: str, cmd: PTZCommand) -> None: ...
```

**FR-1.2 Capability declaration.** Adapters declare what they support (`EVENTS_PUSH`, `EVENTS_POLL`, `PTZ`, `PLAYBACK`, `SNAPSHOT`, `ANALYTICS_METADATA`, `HEALTH`). The middleware degrades gracefully — a source with no push events is polled, a source with no PTZ simply does not expose PTZ. Consumers query capabilities rather than assuming them.

**FR-1.3 Plugin loading.** Adapters are discovered and loaded dynamically — via Python entry points, a plugin directory, or as separate containerised sidecar services registering with the core. Adding a vendor must not require rebuilding or redeploying the core. Version each adapter independently.

**FR-1.4 Reference adapters.** Ship at least: ONVIF (the generic, standards-based adapter that covers the long tail), one HTTP-vendor adapter (Hikvision ISAPI), and one adapter for a genuinely different open-source VMS (ZoneMinder or Frigate, whose APIs differ substantially from each other). A fourth "database adapter" reading directly from a legacy system's tables is worth including because it demonstrates the pattern's flexibility.

### FR-2 Canonical model and metadata exchange

**FR-2.1 Canonical camera schema.** One representation for every camera regardless of origin, preserving the native identifier and native payload for round-tripping. See Appendix A.

**FR-2.2 Canonical event schema.** A CloudEvents-compatible envelope with a typed payload:

```json
{
  "specversion": "1.0",
  "id": "01J8Z2K3N4P5Q6R7S8T9",
  "source": "vms://transport-dept/milestone-01",
  "type": "cctv.event.anpr.plate_detected",
  "subject": "camera:transport-dept:CAM-4471",
  "time": "2026-09-03T14:02:11.482Z",
  "datacontenttype": "application/json",
  "data": {
    "camera_id": "urn:cctv:transport-dept:CAM-4471",
    "native_camera_id": "4471",
    "department": "transport",
    "location": { "lat": 23.0225, "lon": 72.5714, "site": "Iskcon Junction" },
    "event_class": "anpr",
    "severity": "info",
    "confidence": 0.91,
    "plate": "GJ01AB1234",
    "direction": "inbound",
    "evidence_uri": "s3://evidence/2026/09/03/…jpg",
    "native_payload": { "…": "verbatim source event for round-tripping" }
  },
  "ingested_at": "2026-09-03T14:02:11.930Z",
  "trace_id": "…"
}
```

**Event class taxonomy** (extensible): `motion`, `tamper`, `device_status`, `line_crossing`, `intrusion`, `loitering`, `crowd_density`, `object_left`, `object_removed`, `anpr`, `face_match`, `vehicle_count`, `people_count`, `analytics_generic`, `recording_status`, `user_action`.

**FR-2.3 Identity mapping.** A durable mapping between canonical URNs and native IDs, surviving adapter restarts and source-system renumbering. Never leak native IDs upward as primary keys.

**FR-2.4 Metadata synchronisation.** Scheduled full reconciliation plus incremental delta sync. Detect and report drift — cameras added, removed, renamed, or moved in the source system. Optionally publish inventory changes to the Model 1 registry, closing the loop between the two models.

### FR-3 Event and metadata bus

- Durable, ordered, replayable event log — Kafka or equivalent. Partition by department or camera to preserve per-camera ordering.
- Topic design: `cctv.events.raw.{source_id}` (as received), `cctv.events.normalised` (canonical), `cctv.incidents` (correlated), `cctv.inventory.changes`, `cctv.system.health`.
- **Schema registry** with enforced compatibility rules — this is what keeps the canonical model from rotting as adapters are added.
- Dead-letter topic for events that fail normalisation, with a replay tool after the adapter is fixed.
- Consumer groups so multiple downstream services consume independently at their own pace.
- Configurable retention (7–30 days for replay; the durable record lives in the database).

### FR-4 Cross-system event correlation

**This is the feature that justifies the model.** Correlation means deriving a fact that no single source system can know.

**Correlation dimensions:**

- **Temporal** — events within a configurable window (default 0–300 s, per rule).
- **Spatial** — events at cameras within a configurable distance, or within the same zone/ward/jurisdiction polygon, or along a known corridor.
- **Semantic** — matching on a shared entity: the same plate, the same tracked object, the same alarm zone identifier.
- **Sequential** — an ordered pattern (A then B then C within T) rather than mere co-occurrence.
- **Threshold** — N events of a class within a window (five tamper alarms across a district in ten minutes suggests coordinated interference, which no single camera can conclude).

**Rule engine.** Declarative rules, editable without redeployment:

```yaml
rule:
  id: cross-dept-vehicle-of-interest
  name: "Watchlisted vehicle observed across departments"
  description: >
    Correlates ANPR hits on the same plate from cameras belonging to
    different departments within a 15-minute window.
  when:
    all:
      - event.event_class == "anpr"
      - event.plate in watchlist("vehicles_of_interest")
  correlate:
    key: event.plate
    window: 15m
    require:
      distinct_departments: ">= 2"
      min_events: 2
  then:
    create_incident:
      type: vehicle_of_interest_movement
      severity: high
      title: "Watchlisted vehicle {{plate}} tracked across {{department_count}} departments"
      attach: [source_events, evidence_uris, inferred_route]
    notify: [control_room, transport_nodal, police_nodal]
```

Provide at least four working rules, each demonstrating a different dimension, and at least one that spans two *different source systems* — that is the one to demo.

**Deduplication.** The same physical occurrence often produces events in multiple systems (an overlapping camera pair, or a camera registered in two systems during migration). Collapse these into one incident with multiple corroborating sources — this is a correlation *feature*, not noise, and it visibly improves signal quality.

### FR-5 Unified workflow and alert dashboard

- **Incident inbox** — correlated incidents with severity, source events, involved departments, and a map.
- **Workflow state machine:** `new → acknowledged → assigned → in_progress → escalated → resolved → closed`, with mandatory notes on state transitions and SLA timers per severity.
- **Incident detail view** — timeline of constituent events, map of involved cameras, evidence thumbnails, and **deep links back into the source VMS** for the actual video (the middleware hands off; it does not proxy pixels).
- **Cross-department assignment and escalation** with notification routing.
- **Rule management UI** — create, test against historical events, enable/disable, and view per-rule hit rate. A rule that fires 4,000 times a day is broken; make that visible.
- **Federated search** across all sources: by camera, department, event class, time, entity (plate), and geography.
- **System health view** — per-adapter connection status, event throughput, normalisation error rate, and lag.

### FR-6 Downstream API surface

The middleware exists to be consumed. Expose:

- **REST** for synchronous queries (inventory, events, incidents, health).
- **GraphQL** (optional, high value) for consumers that need flexible joins across cameras, events, and incidents without N+1 calls.
- **WebSocket / SSE** for real-time event and incident streaming to browsers.
- **Kafka topics** for high-volume machine consumers (an AI service, a data lake).
- **Webhooks** for external systems that prefer push.

## 3.4 Recommended Tech Stack

| Layer | Recommendation | Rationale and alternatives |
|---|---|---|
| **Middleware core** | **Java 21 + Spring Boot 3** *or* **Python 3.12 + FastAPI** | Spring Boot is the conventional government-integration choice: mature Kafka/JMS support, strong typing, first-class plugin patterns, and a large hiring pool. FastAPI is faster to build in and better if the same team also builds ML services. **Pick one and be consistent** — the brief permits either. |
| **Alternative** | Node.js + NestJS | NestJS's module/provider DI system maps very naturally onto a plugin architecture. |
| **Adapter runtime** | In-process plugins (Python entry points / Java SPI + `ServiceLoader`), **or** containerised sidecar adapters registering over gRPC | Sidecars are more work but give per-adapter isolation, independent scaling, and independent deployment — a genuinely better architecture, and a strong point to argue. |
| **Message bus** | **Apache Kafka** (production) or **Redpanda** (Kafka-compatible, single binary, no ZooKeeper — far easier to operate) | Redpanda is the pragmatic prototype choice. **RabbitMQ** is acceptable but lacks Kafka's replay and log-retention semantics, which you want for correlation. |
| **Schema registry** | Confluent Schema Registry, Apicurio, or Redpanda's built-in | Avro or JSON Schema. Enforce backward compatibility. |
| **Stream processing** | **Kafka Streams** (Java) or **Faust** / **Quix Streams** (Python); **Apache Flink** for complex event processing at scale | Windowed joins across topics are exactly what correlation needs. Flink is the right long-term answer; Kafka Streams is enough for a prototype. |
| **Rule engine** | **Drools** (Java, mature, business-rule oriented), **Esper** (CEP), or a custom evaluator over **CEL** / **JSONLogic** / **Durable Rules** | A custom evaluator over a YAML DSL is often the best prototype choice — full control, no learning curve, and it demos better because the rules are readable. |
| **API gateway** | **Kong** or **Traefik**; NGINX if you prefer | Auth offload, rate limiting, per-consumer quotas, request logging. |
| **Database** | **PostgreSQL 16 + PostGIS** | Canonical inventory, identity mappings, incidents, workflow state, rules, audit. PostGIS for spatial correlation. |
| **Cache / state** | **Redis 7** | Correlation window state, adapter connection state, dedup keys, rate limits. |
| **Event store / analytics** | **ClickHouse** or **TimescaleDB** | Postgres alone will not enjoy hundreds of millions of events. ClickHouse is exceptional for this shape of data. |
| **Search** | OpenSearch / Elasticsearch | Federated event and incident search. |
| **Frontend** | React 18 + TypeScript + Vite, TanStack Query, MapLibre GL JS | |
| **Real-time UI transport** | WebSocket (Socket.IO or native) or SSE | |
| **Auth** | **Keycloak** — realm per department, service accounts per adapter and per downstream consumer | |
| **Secrets** | HashiCorp Vault | Departmental credentials, per-adapter, rotatable by the department. |
| **Observability** | **OpenTelemetry** + Prometheus + Grafana + Jaeger/Tempo | **Distributed tracing is not optional here.** When an event fails to correlate, you must be able to follow it from source through adapter, bus, normaliser, and rule engine. |
| **API docs** | OpenAPI 3.1 + AsyncAPI 2.6 | AsyncAPI documents the *event* contracts — a professional touch that most teams miss and evaluators notice. |
| **Deployment** | Docker Compose (prototype) → Kubernetes + Helm (production) | |

## 3.5 Datasets Required

Model 3 requires **no machine-learning dataset**. It requires event and inventory data to federate, most of which is generated by the systems it connects to.

| Need | Approach |
|---|---|
| **Camera inventory** | Pulled live from adapters. Seed the source systems with Model 1's synthetic registry so the federated inventory is realistic and the two models compose. |
| **Event streams** | Generated by the source systems. For volume and repeatability, build an **event simulator** that replays realistic event patterns across sources — this is essential for demonstrating and testing correlation, and it is a legitimate deliverable in its own right. |
| **Correlation test scenarios** | Hand-authored scripted scenarios — each a timed sequence of events across ≥ 2 source systems that a specific rule should catch. These double as your regression test suite and your demo script. |
| **Spatial reference data** | Administrative boundaries and camera coordinates (see Model 1 §1.6) for spatial correlation and jurisdiction routing. |
| **Historical event corpus** | Synthesise several million events across 30 days for rule backtesting and performance testing. Include realistic diurnal patterns — event rates are not uniform across a day, and a rule tuned on flat data will misbehave at rush hour. |

**Designing the event simulator well matters.** It should produce: background noise (routine motion, device heartbeats) at realistic rates; scripted incident scenarios that *should* correlate; and near-miss scenarios that should *not* correlate (same plate, but 45 minutes apart; two events close in time but 30 km apart). Demonstrating that your engine correctly *rejects* near-misses is more persuasive than showing it accepts obvious ones.

## 3.6 Data Sources

| Need | Source | Access |
|---|---|---|
| Source system A | Self-hosted **ZoneMinder** with its Event API and zmNinja API | Free, open source |
| Source system B | Self-hosted **Frigate** — MQTT event stream + HTTP API (deliberately a very different integration shape from ZoneMinder's) | Free, open source |
| Source system C (optional) | Self-hosted **Shinobi** or **Kerberos.io** | Free |
| Generic standards adapter | **ONVIF** Events Service against real or virtual cameras | Free specification |
| Vendor HTTP adapter | Hikvision ISAPI / Dahua HTTP API against a real camera or emulator | Free docs; camera purchase optional |
| Video to drive the source systems | Looping traffic footage served as RTSP via MediaMTX or FFmpeg | Self-generated |
| Camera inventory | Model 1 synthetic registry | Internal |
| Boundaries / spatial context | OSM, Datameet, Bhuvan (see §1.6) | Free |
| Event schema conventions | [CloudEvents specification](https://cloudevents.io/), ONVIF event topic taxonomy | Free |
| Reference architecture | [IUDX](https://iudx.org.in/) data exchange model, NGSI-LD / FIWARE context broker patterns | Free — worth citing; IUDX solves a structurally similar federation problem for Indian smart cities and referencing it signals domain awareness |

> **Why ZoneMinder and Frigate specifically:** they are genuinely dissimilar. ZoneMinder is a PHP/MySQL system with a REST API and a relational event model. Frigate is a Python/MQTT system with a push event stream and an object-detection-native event model. Writing adapters for both proves your abstraction handles real heterogeneity rather than two flavours of the same thing. Add ONVIF as a third and you have covered pull-REST, push-MQTT, and SOAP-notification — three fundamentally different integration paradigms.

## 3.7 APIs and Services Required

### Consumed (northbound from source systems)

| Source | Interface | Notes |
|---|---|---|
| ONVIF-compliant devices/VMS | Device, Media, Events (WS-BaseNotification), PTZ, Replay services | The standards-based long-tail adapter |
| Hikvision | ISAPI over HTTP + digest auth; event alert stream | No SDK licence needed |
| Dahua | HTTP API + event subscription | |
| Milestone XProtect | MIP SDK / MIP VMS API | Licence required — document the adapter contract, mock the implementation |
| Genetec Security Center | SDK / Web SDK | Licence required — same approach |
| ZoneMinder | REST API (`/api/events`, `/api/monitors`) | Open |
| Frigate | HTTP API + MQTT topics (`frigate/events`) | Open |
| Legacy/DB sources | Direct read-only SQL, or CSV drop | Demonstrates the pattern's reach |
| Model 1 Registry | REST | Inventory reconciliation |
| Vault | HTTP API | Credential retrieval |

### Exposed (southbound to consumers — the actual product)

**REST**

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/sources` | Federated source systems and their capabilities |
| `GET /api/v1/sources/{id}/health` | Per-adapter health, lag, error rate |
| `POST /api/v1/sources` | Register a new source (adapter type + config) |
| `GET /api/v1/cameras` | Unified canonical inventory across all sources |
| `GET /api/v1/cameras/{urn}` | Canonical camera detail, including native payload |
| `GET /api/v1/cameras/{urn}/stream-reference` | Stream URI + credentials handle (a reference, not the video) |
| `GET /api/v1/events` | Federated event query — filter by time, class, source, department, geography, entity |
| `GET /api/v1/incidents` | Correlated incidents |
| `GET /api/v1/incidents/{id}` | Incident with constituent events and evidence |
| `POST /api/v1/incidents/{id}/transition` | Workflow state change with note |
| `GET/POST/PUT/DELETE /api/v1/rules` | Correlation rule management |
| `POST /api/v1/rules/{id}/backtest` | Evaluate a rule against historical events |
| `GET /api/v1/capabilities` | What each source supports — consumers query, never assume |

**Streaming**

| Interface | Purpose |
|---|---|
| `WS /ws/events` | Real-time normalised event stream (filtered per subscription) |
| `WS /ws/incidents` | Real-time incident stream |
| Kafka `cctv.events.normalised` | High-volume machine consumption |
| Kafka `cctv.incidents` | Incident consumption |
| `POST` webhooks | Push to external systems |

**GraphQL** (optional) — a single `/graphql` endpoint allowing a consumer to fetch an incident with its events, each event's camera, and each camera's department in one round trip.

## 3.8 Data Processing Approach

**Normalisation pipeline:**

```
Source event (native format, any transport)
  → adapter receives (push subscription or poll)
  → publish verbatim to cctv.events.raw.{source_id}   [audit + replay]
  → normaliser: field mapping, unit conversion, timezone → UTC,
                severity mapping, event_class assignment,
                identity resolution (native_id → canonical URN),
                spatial enrichment (attach coordinates, ward, jurisdiction)
  → schema validation against registry
     ├─ pass → cctv.events.normalised
     └─ fail → cctv.events.dlq  (with error detail, replayable after fix)
  → correlation engine (stateful, windowed)
  → incidents → cctv.incidents + PostgreSQL
  → notification dispatcher
  → ClickHouse (analytics) + OpenSearch (search)
```

**Preserving the raw event verbatim is important.** It gives you an audit trail against the source, lets you replay after fixing a mapping bug, and settles disputes about whether a field was wrong at the source or mangled in transit.

**Correlation engine design.** Implement as a stateful stream processor holding windowed state in Redis (or Kafka Streams' state stores):

1. Consume `cctv.events.normalised`.
2. For each active rule, evaluate the `when` predicate.
3. On match, compute the correlation key and look up the open window for that key.
4. Append the event; re-evaluate `require` conditions.
5. On satisfaction, emit an incident and mark the window fired (with a cooldown to prevent re-firing on every subsequent event).
6. Expire windows on timeout.

**Ordering and lateness.** Events arrive out of order — different adapters have different latencies, and polled sources lag pushed ones. Use event time (source timestamp) for correlation, not ingest time, and allow a grace period for late arrivals. Record both timestamps. Where a source's clock is untrustworthy, flag it and consider correcting by measured offset.

**Backpressure.** If a downstream consumer is slow, Kafka absorbs it. If an *adapter* is slow, apply per-adapter concurrency limits and circuit breakers so one misbehaving source cannot stall the platform. Publish per-adapter lag as a first-class metric.

## 3.9 System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  DEPARTMENTAL SOURCE SYSTEMS (independent, unmodified)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │Milestone │ │Hikvision │ │ZoneMinder│ │ Frigate  │ │Legacy DB  │  │
│  │  (SDK)   │ │ (ISAPI)  │ │  (REST)  │ │  (MQTT)  │ │  (SQL)    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
└───────┼────────────┼────────────┼────────────┼─────────────┼────────┘
        │            │            │            │             │
┌───────▼────────────▼────────────▼────────────▼─────────────▼────────┐
│  ADAPTER / CONNECTOR TIER  (one plugin per vendor, isolated)         │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ │
│  │Milestone│ │Hikvision│ │ZoneMdr │ │Frigate │ │  SQL   │ │ ONVIF  │ │
│  │ Adapter │ │ Adapter │ │Adapter │ │Adapter │ │Adapter │ │Adapter │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ │
│  Each implements VMSAdapter · declares capabilities · versioned      │
│  ← NEW VENDORS PLUG IN HERE. Core is never modified. →              │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  FEDERATION MIDDLEWARE CORE                                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ Adapter    │ │ Identity   │ │ Normaliser │ │ Credential Vault │  │
│  │ Registry & │ │ Resolver   │ │ + Schema   │ │ (per-department, │  │
│  │ Lifecycle  │ │ URN↔native │ │ Validator  │ │  read-only)      │  │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────────┘  │
│  ┌────────────┐ ┌────────────┐ ┌────────────────────────────────┐   │
│  │ Inventory  │ │ Health &   │ │ AuthN/AuthZ · routing ·        │   │
│  │ Sync       │ │ Circuit Bk │ │ orchestration · tracing        │   │
│  └────────────┘ └────────────┘ └────────────────────────────────┘   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  EVENT & METADATA BUS  (Kafka / Redpanda + Schema Registry)           │
│  cctv.events.raw.{src} │ cctv.events.normalised │ cctv.incidents      │
│  cctv.inventory.changes │ cctv.system.health │ cctv.events.dlq        │
└───┬──────────────────────┬───────────────────────┬───────────────────┘
    │                      │                       │
┌───▼──────────────┐ ┌─────▼──────────┐ ┌──────────▼─────────────────┐
│ CORRELATION      │ │ Indexers       │ │ Notification Dispatcher    │
│ ENGINE           │ │ → ClickHouse   │ │ email · SMS · webhook · WS │
│ temporal·spatial │ │ → OpenSearch   │ └────────────────────────────┘
│ semantic·seq·thr │ └────────────────┘
│ rule DSL + state │
└───┬──────────────┘
    │
┌───▼──────────────────────────────────────────────────────────────────┐
│  UNIFIED API LAYER  (Kong gateway → REST · GraphQL · WS · webhooks)   │
│  PostgreSQL+PostGIS: inventory · mappings · incidents · rules · audit │
└───┬─────────────────┬──────────────────┬─────────────────────────────┘
    │                 │                  │
┌───▼───────────┐ ┌───▼──────────┐ ┌────▼────────────┐ ┌─────────────┐
│ Unified       │ │ Model 1      │ │ AI / Analytics  │ │ Future      │
│ Dashboard     │ │ GIS Registry │ │ Services        │ │ Consumers   │
│ (reference    │ │              │ │                 │ │ (mobile,    │
│  consumer)    │ │              │ │                 │ │  Model 2 UI)│
└───────────────┘ └──────────────┘ └─────────────────┘ └─────────────┘
```

**Architectural principles to state and defend:**

1. **The core knows nothing about any vendor.** Every vendor-specific line of code lives inside an adapter. Prove it — `grep` for "hikvision" outside the adapter directory should return nothing.
2. **Metadata flows through the middleware; video does not.** The middleware hands out stream *references*. This keeps it lightweight, keeps departmental video on departmental infrastructure, and is the cleanest possible answer to "does this burden our network?"
3. **Raw events are preserved verbatim** before normalisation, for audit and replay.
4. **Capability negotiation, not assumption.** Consumers ask what a source can do.
5. **The dashboard is a consumer, not the product.** Anything the dashboard can do, a third party can do through the same public API.

## 3.10 Development Requirements

**Prototype**

| Resource | Specification |
|---|---|
| Middleware host | 8 vCPU, 32 GB RAM, 200 GB SSD |
| Source system simulators | 2 × (4 vCPU, 8 GB) for ZoneMinder and Frigate, plus looping RTSP feeders |
| **GPU** | **None required** |
| Bandwidth | Low — metadata only |
| Cloud equivalent | A single 8-core VM runs the whole stack via Docker Compose |

**Production (statewide federation)**

| Component | Specification |
|---|---|
| Middleware core | 3+ replicas × (8 vCPU, 32 GB), horizontally scaled |
| Adapter instances | 1–2 per source system, sized by event volume; isolate noisy sources |
| Kafka | 3–5 brokers × (8 vCPU, 32 GB, 2 TB NVMe) |
| Correlation engine | 3 × (8 vCPU, 32 GB) — stateful, so plan partition-aware scaling |
| PostgreSQL | 8 vCPU / 32 GB / 1 TB + replica |
| ClickHouse | 3 nodes × (16 vCPU, 64 GB, 4 TB) — sized by event retention |
| OpenSearch | 3 nodes × (8 vCPU, 32 GB, 1 TB) |
| Redis | 4 vCPU / 16 GB, clustered |
| API gateway | 2 × (4 vCPU, 8 GB) |
| Observability stack | 8 vCPU / 32 GB / 1 TB |

**Team profile:** 2 backend/integration engineers, 1 data/streaming engineer, 1 frontend, 0.5 DevOps. Approximately 14–20 person-weeks for a strong prototype. Notably **no ML engineer and no GPU** — this is the model to choose if your team's strength is systems architecture rather than computer vision.

## 3.11 Implementation Approach

**Phase 0 — Define the canonical model first (days 1–5).** Camera schema, event envelope, event class taxonomy, capability enumeration, and the adapter interface. Write these as versioned schemas in the registry before writing any adapter. **Everything downstream depends on getting this right**, and changing it after three adapters exist is painful. Resist the urge to start coding adapters on day one.

**Phase 1 — Source simulators (days 3–7, parallel).** Deploy ZoneMinder and Frigate, feed them looped video, and confirm both actually produce events. This is your test bed and it must exist before adapters can be developed meaningfully.

**Phase 2 — Adapter framework and first adapter (days 6–13).** Plugin loading, adapter registry, lifecycle management, health checks, circuit breakers, credential vault integration. Then the first adapter (ZoneMinder — the simplest REST case) end to end: connect, list cameras, subscribe to events, normalise, publish to Kafka.

**Phase 3 — Second and third adapters (days 12–18).** Frigate (MQTT push — a fundamentally different transport) and ONVIF (SOAP notification). **This is the phase where your abstraction is tested.** If you find yourself adding source-specific branches to the core, stop and refactor — that is the whole thesis of the model failing.

**Phase 4 — Bus, normalisation, persistence (days 15–22).** Kafka topics, schema registry, normaliser service, DLQ handling, identity resolution, inventory sync with drift detection, ClickHouse and OpenSearch indexing.

**Phase 5 — Correlation engine (days 20–29).** Rule DSL and parser, stateful windowed evaluator, the five correlation dimensions, incident generation, deduplication, cooldowns, backtesting against historical events. Author and test the demonstration rules.

**Phase 6 — Dashboard and API (days 26–34).** Incident inbox, detail view with timeline and map, workflow state machine, rule management UI, federated search, system health view. Public REST/GraphQL/WS API with generated documentation.

**Phase 7 — The proof and the polish (days 33–38).** **Write a fourth adapter for a vendor you have not yet integrated, time how long it takes, and document it.** If it takes under a day with no core changes, you have proven the model's central claim — and that measured number is the most persuasive sentence in your submission. Then: load testing, event simulator scenarios, AsyncAPI documentation, plugin developer guide, demo rehearsal.

## 3.12 Expected Deliverables

1. **Working middleware federating ≥ 2 different systems** — deployed, with adapters for structurally dissimilar sources (REST-pull, MQTT-push, SOAP-notification), each surfacing cameras and events into one canonical model.
2. **Unified event-correlation dashboard** — incident inbox, detail view with cross-system event timeline and map, full workflow state machine with audit, rule management UI, federated search, and a live system health view.
3. **Adapter/plugin architecture documentation** — the interface specification, capability model, canonical schemas (camera + event, with the full event-class taxonomy), a step-by-step *"how to write a new adapter"* developer guide, and the sample skeleton adapter. **This is the intellectual core of the deliverable and should be treated as a primary artefact, not an appendix.**
4. **Evidence of extensibility** — the fourth adapter, with a written record of the time taken and the number of core files changed (target: zero).
5. **Sample federated analytics report** — cross-department event volumes, correlation hit rates by rule, coverage of federated cameras by department, adapter reliability statistics, and at least one genuine cross-departmental insight derived from the federated data that no single source could produce.
6. **API documentation** — OpenAPI 3.1 for REST, **AsyncAPI 2.6 for the event contracts**, GraphQL schema if implemented, and a consumer integration guide.
7. **Event simulator and scenario suite** — the tool plus the scripted correlation scenarios, usable as a regression test suite.
8. **Deployment package** — Helm charts / Compose files, configuration reference, adapter onboarding runbook.

## 3.13 Evaluation and Success Criteria

**Federation**

| Test | Pass criterion |
|---|---|
| Adapter isolation | Zero vendor-specific identifiers anywhere in the core codebase (verifiable by search) |
| New adapter onboarding | A working adapter for a previously unintegrated source in < 1 developer-day, zero core changes |
| Canonical fidelity | 100% of source cameras appear with correct canonical fields; native payload preserved verbatim |
| Capability degradation | A source lacking push events, PTZ, or playback works correctly with those features gracefully absent |
| Adapter failure isolation | Killing one adapter leaves all other sources fully operational; the failure is visible in health within 30 s |
| Inventory drift detection | Adding, renaming, or removing a camera at the source is detected and reported within one sync cycle |

**Event pipeline**

| Metric | Target |
|---|---|
| End-to-end latency, source event → normalised on bus | < 2 s (push sources) |
| Normalisation success rate | > 99.5%; all failures land in DLQ with diagnosable errors |
| Throughput | ≥ 10,000 events/sec sustained on prototype hardware |
| Ordering | Per-camera event ordering preserved |
| Replay | DLQ events replay successfully after an adapter fix |

**Correlation**

| Metric | Target |
|---|---|
| Cross-system correlation demonstrated live | ✅ Required — must involve ≥ 2 *different source systems* |
| Correlation latency | < 5 s from the triggering event |
| Scenario detection rate | 100% of scripted positive scenarios detected |
| **False-positive rate on near-miss scenarios** | **0% — this is the more impressive number; demonstrate it explicitly** |
| Deduplication | Duplicate events from overlapping sources collapse into a single incident with multiple corroborations |
| Rule backtest | Runs over 30 days of historical events in < 60 s |

**Workflow**

- All state transitions enforced, audited, and attributed.
- SLA timers fire correctly.
- Cross-department assignment routes to the correct nodal officer.
- Deep links open the correct camera and time in the source VMS.

## 3.14 Dependencies and Risks

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Canonical model proves too rigid for real vendor diversity | Adapters need core changes; the core thesis fails | Medium | Include `native_payload` passthrough and typed extension fields from day one; version the schema; test against dissimilar sources early |
| R2 | Commercial SDKs (Milestone, Genetec) unobtainable | Cannot demonstrate enterprise adapters | High | Build against open systems; document the SDK adapter contract and ship a mock implementation; make clear this is a licensing constraint, not a design gap |
| R3 | Correlation rules produce alert flood | Dashboard is unusable; operators disable it | **High** | Backtesting before enabling; per-rule hit-rate monitoring; cooldowns; severity thresholds; make rule tuning a first-class UI |
| R4 | Clock skew between departmental systems | Correlation windows misfire | **High** | Mandate NTP; record both event time and ingest time; detect per-source offset and correct; flag untrustworthy sources |
| R5 | Departments will not issue API credentials | Nothing to federate | Very High | Simulated sources as the primary demonstration path; treat real access as a bonus |
| R6 | Kafka operational complexity overwhelms the timeline | Delivery slips on infrastructure, not features | Medium | Use **Redpanda** — Kafka-compatible, single binary, no ZooKeeper; migrate later if needed |
| R7 | Correlation state grows unbounded | Memory exhaustion | Medium | Strict window expiry, TTL on all Redis keys, bounded per-key state, and monitoring on state size |
| R8 | Out-of-order and late events break windowed correlation | Missed correlations | Medium | Event-time processing with a configurable grace period; document the trade-off between latency and completeness |
| R9 | The demo is visually unimpressive next to a video wall | Loses to Model 2 on presentation despite better architecture | **Medium-High** | Invest deliberately in the incident visualisation — timeline, map, and an animated "two events collapsing into one incident" sequence. **This is a real risk; budget for it.** |
| R10 | Schema evolution breaks existing consumers | Downstream outages | Low-Medium | Schema registry with enforced backward compatibility; versioned API; deprecation policy |

**Key dependencies:** read-only API credentials from each source system; network reachability; NTP; source systems that actually emit events (a VMS with analytics disabled emits almost nothing — verify early).

## 3.15 Estimated Complexity

**Overall: 3.5 / 5 — Moderate-High.**

Conceptually the most demanding of the four, but the implementation is more forgiving than Model 2: no real-time video, no latency budget measured in milliseconds, no GPU, no model training.

| Area | Effort | Difficulty | Notes |
|---|---|---|---|
| Canonical model design | Medium | **High** | The core intellectual work; getting it wrong is expensive to fix later |
| Adapter framework | High | **High** | Designing a genuinely extensible plugin system is harder than it looks |
| Individual adapters | High | Medium | Each is moderate; the volume is what costs |
| Event bus and normalisation | Medium | Medium | Well-trodden patterns |
| Correlation engine | High | **High** | Stateful windowed stream processing with out-of-order tolerance is real distributed-systems work |
| Rule DSL | Medium | Medium | A YAML DSL plus evaluator is very achievable |
| Workflow dashboard | High | Low-Medium | Large surface area, low individual difficulty |
| API surface (REST/GraphQL/WS/Kafka) | Medium | Low-Medium | |
| Observability and tracing | Medium | Medium | Essential here — do not defer it |

**Where teams lose points:** building two adapters that are secretly the same shape (two REST APIs) and calling it federation; and under-investing in the demo of correlation, which is the only thing that distinguishes this model from a well-organised API gateway.

**Where teams win:** the measured "new adapter in under a day, zero core changes" result, and a correlation demonstration that shows the engine correctly rejecting near-misses as well as catching true positives.
---

# Model 4 — Consolidated Central VMS (Statewide Platform)

## 4.1 Problem Statement

Models 2 and 3 both accept fragmentation as permanent and engineer around it. Model 4 rejects that premise. It proposes that the state stop federating and instead **consolidate**: one platform that ingests, records, stores, plays back, and analyses video from every eligible camera in Gujarat, replacing the patchwork of departmental VMS deployments with a single operational system.

The problems this addresses that no federation model can:

- **Federation cannot deliver capabilities the source systems do not have.** If a department's VMS has no analytics, Model 3 has nothing to federate and Model 2 must tap the raw stream anyway. Only central ingestion guarantees uniform capability across every camera.
- **Recording policy cannot be enforced across systems you do not own.** Retention, quality, redundancy, and legal-hold behaviour vary per department and per procurement. Evidence integrity is not assured.
- **Statewide vehicle tracking requires statewide analytics.** Reconstructing a vehicle's route across districts demands ANPR on cameras owned by many departments, running consistently, with synchronised clocks and a single index. Federation gives you whichever subset already happens to have ANPR.
- **Cross-departmental analytics — crowd density, anomaly detection, multi-camera object tracking — need the pixels**, not just the events.
- **Cost and operational duplication.** Dozens of parallel VMS licences, storage arrays, support contracts, and operator training programmes.
- **Integration with national databases** (VAHAN, SARATHI, NAFIS, eGujCop) is impossible to do consistently across dozens of independent systems, and legally fraught to do in dozens of places.

**This is the only model in which departmental VMS platforms do not survive.** Every other model's text contains a variant of "without disturbing existing infrastructure." That constraint is deliberately absent here.

**The defining engineering fact is the scale.** The deliverables specify a load-test report at approximately **80,000 cameras**. Every architectural decision follows from that number, and most conventional VMS architectures fail long before it.

## 4.2 Objective and Expected Outcome

**Objective.** Design and prototype a statewide video platform capable of ingesting, recording, storing, retrieving, and analysing video from ~80,000 cameras across all departments, with tiered storage, GPU-accelerated analytics, statewide vehicle tracking, integration readiness for authorised government databases, and the redundancy, disaster-recovery, and security controls appropriate to critical state infrastructure.

**Expected outcome — the system succeeds when:**

1. A working prototype ingests, records, and plays back video from multiple simulated departmental sources through a single platform.
2. Storage demonstrably tiers — data physically moves hot → warm → cold on policy, and retrieval works from every tier.
3. ANPR runs on ingested streams and populates a searchable statewide index.
4. **Multi-location vehicle tracking is demonstrated** — a vehicle observed at three or more camera locations, reconstructed as an ordered route on a map with timestamps and evidence.
5. Additional analytics (crowd counting, vehicle counting, anomaly detection) run and produce indexed results.
6. Adapters for VAHAN, SARATHI, AFIS/NAFIS and eGujCop exist as **contract-first implementations against documented mocks**, with a written swap-in procedure for real credentials.
7. A **credible, measured** scalability report projects to 80,000 cameras from benchmarked evidence — not from assertion.
8. Disaster-recovery, redundancy, and security architecture documents exist at a standard a state CISO would engage with.

**Critical framing:** you cannot build this system in a project timeline, and you are not expected to. Three of the five required deliverables are documents. **Model 4 is graded on architecture, measurement, and evidence** — a small system that works perfectly plus a rigorous projection beats a large system that half-works.

## 4.3 Functional Requirements

### FR-1 Centralised ingestion

- Ingest via RTSP, ONVIF, RTMP, SRT, and vendor protocols.
- **Hierarchical ingestion topology:** camera → district edge node → regional data centre → state core. Direct camera-to-core ingestion at 80,000 cameras is not viable and should be explicitly rejected in the architecture note. Edge nodes do first-pass recording, transcoding, and analytics; only metadata, alerts, and requested clips travel upstream.
- Automatic reconnection, stream health monitoring, ingest-lag metrics per camera.
- Codec normalisation policy — transcode on ingest only where necessary, prefer H.265 for storage efficiency.
- Camera provisioning at scale: bulk onboarding from the Model 1 registry, zero-touch provisioning where devices support it, configuration templates by camera class.

### FR-2 Recording, storage and lifecycle

**Tiering policy (illustrative, configurable per camera class):**

| Tier | Age | Medium | Quality | Retrieval | Purpose |
|---|---|---|---|---|---|
| **Hot** | 0–7 days | NVMe / SSD, edge + regional | Full bitrate, full fps | Instant | Live review, active incidents |
| **Warm** | 8–30 days | HDD object storage, regional | Transcoded ~⅓ bitrate | Seconds | Recent investigation |
| **Cold** | 31–90 days | High-density HDD / erasure-coded object store, central | Transcoded ~1/10, reduced fps | Minutes | Case support |
| **Archive** | 90 days–7 years | Tape (LTO-9) or deep archive object storage | Key segments only, under legal hold | Hours | Evidentiary retention |

- **Legal hold:** flagged footage is exempt from lifecycle deletion until the hold is released, with full audit.
- **Motion/event-based recording** for low-value cameras — continuous recording of every camera is neither necessary nor affordable, and selective recording is a legitimate, defensible cost control.
- **Automatic expiry** with certificate of deletion, satisfying retention-limitation obligations.
- **Integrity:** cryptographic hashing of stored segments, hash chain per camera per day, so evidentiary integrity can be proven in court.

### FR-3 Monitoring, playback and operations

- Multi-camera video walls (as Model 2), scaled to command-centre displays with per-operator and per-role layouts.
- Synchronised multi-camera playback — several cameras replayed on a common timeline, essential for incident review.
- Timeline scrubbing with event markers overlaid.
- Instant replay, bookmarking, and **evidence export** with a chain-of-custody manifest (who exported, when, what time range, hash, purpose, case reference).
- PTZ control with priority arbitration between operators.
- Map-based camera selection and situational display.

### FR-4 Analytics suite

| Capability | Description | Difficulty |
|---|---|---|
| **ANPR** | Plate detection and recognition, statewide index (as Model 2 §2.8) | High |
| **Vehicle counting & classification** | Directional counts by class (2W/3W/4W/LCV/HCV/bus) per camera per interval | Medium |
| **Crowd counting / density** | Head-count estimation and density heatmaps; threshold alerts for overcrowding | Medium-High |
| **Anomaly detection** | Unusual motion patterns, wrong-way movement, sudden dispersal, abandoned objects, loitering | **High** |
| **Multi-camera vehicle tracking** | Re-identification linking sightings across cameras, including where plates are unreadable | **Very High** |
| **Face recognition** | Detection, embedding, and matching against an authorised watchlist | **Very High — and the highest-risk feature in the programme; see §4.4 and §0.2.3** |

### FR-5 Statewide vehicle tracking and route reconstruction

- Statewide plate index across all ANPR-enabled cameras.
- Query by plate (exact, partial, fuzzy) returning a full sighting history.
- Route reconstruction with map rendering, road-snapping, inter-sighting speed, and dwell detection.
- **Convoy / co-travel detection** — identify vehicles repeatedly observed together across multiple cameras.
- Predictive next-camera estimation from road topology (optional, high demo value).
- Watchlist alerting statewide, with district-level routing.

### FR-6 Government database integration (build as contract-first mocks — see §0.2.2)

| System | Integration purpose | Sensitivity |
|---|---|---|
| **VAHAN** | Enrich a plate read with registration, owner, vehicle class, insurance and PUC validity | High — personal data |
| **SARATHI** | Driving licence verification linked to a vehicle or person | High |
| **eGujCop** | Push detections to police case records; pull vehicles/persons of interest into watchlists | Very High |
| **AFIS / NAFIS** | Fingerprint identification — architecturally adjacent, not a video function | Very High |

For each: define the request/response contract, implement the adapter, stand up a mock returning realistic synthetic data, implement caching and rate limiting, log every lookup with actor, purpose, and case reference, and document exactly what changes when real credentials arrive.

### FR-7 Redundancy, disaster recovery and security

- **Redundancy:** N+1 at every tier; active-active regional data centres; no single point of failure in ingestion, storage, or control.
- **DR:** a defined RPO and RTO per data class (see §4.9.4), cross-region replication, and documented, *tested* failover runbooks.
- **Encryption:** TLS 1.3 in transit; AES-256 at rest; per-tenant/department key separation via HSM or a managed KMS.
- **Network segmentation:** camera VLANs isolated from operator networks isolated from management networks; a strictly controlled DMZ for external integrations; no direct internet path to cameras.
- **RBAC + ABAC:** role plus attribute-based access — jurisdiction, clearance level, case assignment, and time-bounded grants.
- **Immutable audit:** every view, search, export, and configuration change logged to append-only storage (WORM or hash-chained), retained separately from the operational database.
- **Purpose-bound access:** searches — especially face and plate searches — require a stated purpose and case reference, enforced at the API layer.
- **Security operations:** SIEM integration, anomaly detection on operator behaviour, mandatory MFA, session recording for privileged actions.

## 4.4 Recommended Tech Stack

| Layer | Recommendation | Notes |
|---|---|---|
| **VMS core** | **Custom platform** built on open components, or an extended open-source base | Building on **MediaMTX** (ingest/relay) + **Frigate**-derived analytics patterns + custom recording and lifecycle services gives control. Extending a monolithic open-source VMS (ZoneMinder, Shinobi) does *not* scale to 80,000 — say so explicitly and justify the custom path. |
| **Ingest / relay** | MediaMTX, go2rtc, GStreamer pipelines | Horizontally scaled, stateless, autoscaled per edge node. |
| **Transcode** | FFmpeg with NVENC/NVDEC; NVIDIA Video Codec SDK | Hardware encode is mandatory at this scale. |
| **Object storage** | **Ceph** (RADOS + RGW) for self-hosted; **MinIO** for the prototype; S3-compatible cloud for the hybrid tier | Ceph with **erasure coding** (e.g. 8+3, ~1.375× overhead) rather than 3× replication — the difference between 85 PB and 186 PB of raw disk for the same data. |
| **Alternative storage** | SeaweedFS (very efficient for many small objects), JuiceFS over object storage | |
| **Tape archive** | LTO-9 library with LTFS | The only economically viable medium for multi-year retention at petabyte scale. |
| **Segment format** | fMP4 / CMAF segments, 2–10 s each | Enables partial retrieval, efficient tiering, and direct HTTP playback without repackaging. |
| **Stream processing** | **Apache Kafka** (or Redpanda) for events; **Apache Flink** for stateful analytics at scale | Flink is the right tool for windowed statewide aggregation. |
| **Inference serving** | **NVIDIA DeepStream** (full decode→infer→track pipeline on GPU) or **Triton Inference Server** | DeepStream keeps frames in GPU memory end to end — typically several times the throughput of a naive PyTorch pipeline. This choice alone changes your GPU count materially. |
| **Alternative inference** | **Savant** (open-source DeepStream framework), OpenVINO for CPU/iGPU tiers | |
| **Models** | ANPR per Model 2 §2.4; vehicle detection RT-DETR/YOLOX; crowd counting CSRNet/**P2PNet**/DM-Count; anomaly MGFN/RTFM/**AnomalyCLIP**; vehicle re-ID **TransReID**/FastReID; face **InsightFace/ArcFace** | ⚠️ Check every licence. Ultralytics YOLO is AGPL-3.0; InsightFace models have use restrictions; some crowd datasets prohibit commercial use. |
| **Model optimisation** | TensorRT with INT8 quantisation, and model distillation | INT8 typically 2–4× throughput over FP16 with small accuracy loss — at 500+ GPUs this is a very large capital saving. |
| **Orchestration** | **Kubernetes** + Helm; NVIDIA GPU Operator + device plugin; **KubeEdge** or **k3s** for district edge nodes | |
| **Database** | **PostgreSQL 16 + PostGIS** (metadata, config, users, cases) | |
| **Time-series / event store** | **ClickHouse** (strongly preferred at this scale) or **TimescaleDB** | Billions of detection events. ClickHouse's compression and aggregation performance are in a different class for this workload. |
| **Search** | **OpenSearch** / Elasticsearch cluster | Plate, event, and case search. |
| **Cache** | Redis Cluster | |
| **Vector search** (face/vehicle re-ID) | **Milvus**, **Qdrant**, or FAISS | Embedding similarity at scale. |
| **API gateway** | Kong / Envoy | |
| **Auth** | Keycloak with LDAP/AD federation; MFA mandatory; PKI for service identity | |
| **Secrets / keys** | HashiCorp Vault + HSM-backed KMS | |
| **Service mesh** | Istio or Linkerd — mTLS everywhere | |
| **Observability** | OpenTelemetry, Prometheus + Thanos (long-term metrics), Grafana, Loki, Jaeger | |
| **SIEM** | Wazuh (open source) or a commercial SOC platform | |
| **IaC** | Terraform + Ansible; GitOps via ArgoCD | |
| **Frontend** | React 18 + TypeScript; WebRTC/LL-HLS playback; MapLibre GL + deck.gl | |
| **Network** | 100 GbE spine-leaf in the core; MPLS/dark fibre state backbone; SD-WAN to district nodes | |

## 4.5 Datasets Required

Model 4 needs everything Model 2 needs, plus datasets for the additional analytics.

| Capability | Datasets |
|---|---|
| **ANPR** | As Model 2 §2.5 — CCPD (pretraining), Indian plate datasets from Roboflow/DataCluster/`Indian_LPR`, UFPR-ALPR, synthetic augmentation |
| **Vehicle detection & classification** | **UA-DETRAC**, **BDD100K**, COCO, **IDD (India Driving Dataset)** — IDD is particularly valuable because it is Indian road scenes with Indian vehicle classes including auto-rickshaws |
| **Vehicle re-identification** | **VeRi-776**, **VERI-Wild**, **VehicleID**, NVIDIA **AI City Challenge** (Tracks 1 & 2 are exactly multi-camera vehicle tracking) |
| **Crowd counting** | **ShanghaiTech Part A/B**, **UCF-QNRF**, **JHU-CROWD++**, **NWPU-Crowd** |
| **Anomaly detection** | **UCF-Crime** (1,900 real surveillance videos, 13 anomaly classes — the standard benchmark), **ShanghaiTech Campus**, **CUHK Avenue**, **XD-Violence** |
| **Multi-camera tracking** | **AI City Challenge** MTMC track, **WILDTRACK**, **MTA (Multi-camera Track Auto)** |
| **Face recognition** | ⚠️ **Proceed with caution.** LFW / IJB-C for benchmarking; MS1M and Glint360K have significant licensing and ethical issues; WebFace260M requires agreement. **For a demonstration, strongly prefer synthetic faces (e.g. StyleGAN-generated) or explicitly consented team member images.** Using scraped face datasets in a government-facing submission is a reputational risk that outweighs the benefit. |
| **Test video** | Self-captured footage, IDD, UA-DETRAC, AI City, and public traffic feeds (check terms) |
| **Load-test synthetic streams** | Generated — see §4.8.4 |
| **Camera inventory** | Model 1 synthetic registry, scaled to 80,000 |
| **Government DB mocks** | Synthetic VAHAN/SARATHI-shaped records — realistic field structure, entirely fabricated content |

## 4.6 Data Sources

| Need | Source | Access |
|---|---|---|
| Indian road scenes | [India Driving Dataset (IDD)](https://idd.insaan.iiit.ac.in/) — IIIT Hyderabad | Free, registration |
| Traffic / vehicle detection | UA-DETRAC, [BDD100K](https://bdd-data.berkeley.edu/) | Free / academic |
| Vehicle re-ID | [VeRi-776](https://github.com/JDAI-CV/VeRidataset), VERI-Wild, [AI City Challenge](https://www.aicitychallenge.org/) | Free with registration |
| Crowd counting | ShanghaiTech (GitHub), UCF-QNRF (UCF CRCV), NWPU-Crowd, JHU-CROWD++ | Free, academic |
| Anomaly detection | UCF-Crime (UCF CRCV), XD-Violence, CUHK Avenue | Free, academic |
| Plate datasets | Roboflow Universe, Hugging Face, CCPD (GitHub) | Free |
| Pretrained weights | Hugging Face Hub, NVIDIA NGC catalogue (DeepStream-ready models), PaddleOCR zoo, OpenMMLab | Free — **check licences** |
| Government DB specifications | [Parivahan](https://parivahan.gov.in/) public documentation, NIC integration guidelines, [NCRB](https://ncrb.gov.in/) NAFIS public material, [MHA press releases](https://www.pib.gov.in/) | Public documentation only; **actual access is closed — see §0.2.2** |
| Legal framework | [DPDP Act 2023 (MeitY)](https://www.meity.gov.in/), DPDP Rules 2025, IT Act 2000, Indian Evidence Act §65B (electronic evidence admissibility) | Public |
| Standards | ONVIF specifications, ISO/IEC 27001, ISO 22301 (business continuity), **CERT-In** directions, MeitY cloud empanelment guidelines, **NIST SP 800-53** | Public |
| Storage/infra reference | Ceph documentation, NVIDIA DeepStream performance benchmarks, Kubernetes at-scale case studies | Public |
| Sample RTSP at volume | Self-generated via FFmpeg + MediaMTX (see §4.8.4) | Internal |

## 4.7 APIs and Services Required

### Consumed

| Service | Interface | Status |
|---|---|---|
| Camera / edge streams | RTSP, ONVIF, SRT, RTMP | Direct |
| Model 1 Registry | REST | Camera provisioning source |
| **VAHAN** | REST (NIC G2G, or commercial aggregator) | **Mock — see §0.2.2** |
| **SARATHI** | REST | **Mock** |
| **eGujCop** | REST / state police integration bus | **Mock** |
| **AFIS / NAFIS** | NCRB-defined interface | **Mock** |
| GIS / boundaries | WMS/WFS (Bhuvan), internal PostGIS | Available |
| Notification | SMS gateway, SMTP, push, webhook | Available |
| Identity | LDAP / Active Directory | State infrastructure |
| Time | NTP / PTP (IEEE 1588) | **PTP recommended at the core** — sub-microsecond sync makes multi-camera correlation far more reliable |
| KMS / HSM | PKCS#11, cloud KMS | |

### Exposed

| Category | Endpoints |
|---|---|
| **Cameras** | `GET/POST /api/v1/cameras`, `POST /api/v1/cameras/bulk-provision`, `GET /api/v1/cameras/{id}/health` |
| **Live** | `POST /api/v1/streams/{id}/session`, `DELETE /api/v1/streams/session/{sid}` |
| **Playback** | `GET /api/v1/playback/{cameraId}?from=&to=&quality=`, `GET /api/v1/playback/multi` (synchronised) |
| **Storage** | `GET /api/v1/recordings/{cameraId}/index`, `POST /api/v1/recordings/legal-hold`, `GET /api/v1/storage/tier-status` |
| **Export** | `POST /api/v1/export` (clip + chain-of-custody manifest), `GET /api/v1/export/{id}` |
| **Analytics** | `GET /api/v1/detections`, `GET /api/v1/analytics/counts`, `GET /api/v1/analytics/crowd`, `GET /api/v1/analytics/anomalies` |
| **Vehicle tracking** | `GET /api/v1/vehicles/{plate}/sightings`, `GET /api/v1/vehicles/{plate}/route`, `POST /api/v1/vehicles/convoy-analysis`, `POST /api/v1/vehicles/reid-search` |
| **Watchlists** | `GET/POST/DELETE /api/v1/watchlists`, `POST /api/v1/watchlists/{id}/entries` |
| **Enrichment** | `GET /api/v1/enrich/vehicle/{plate}` (VAHAN adapter — purpose and case reference **mandatory**) |
| **Cases** | `POST /api/v1/cases`, `POST /api/v1/cases/{id}/evidence` |
| **Admin** | `GET /api/v1/system/health`, `GET /api/v1/system/capacity`, `GET /api/v1/audit` |
| **Streaming** | Kafka topics; `WS /ws/alerts`; webhooks |

## 4.8 Data Processing and ML Approach

### 4.8.1 Hierarchical processing — the central architectural idea

Do not process everything centrally. The architecture that works is:

```
CAMERA
  ↓ RTSP (local network)
DISTRICT EDGE NODE  (one per district / large municipal zone)
  • Ingest, hardware-decode
  • Primary recording — HOT tier lives HERE, not centrally
  • First-pass analytics on GPU (ANPR, counting, motion)
  • Emit metadata + evidence crops + alerts upstream
  • Retain full video locally; ship only on request
  ↓ metadata (kbps, not Mbps) + requested clips
REGIONAL DATA CENTRE  (3–4 across the state)
  • WARM tier storage, transcoded
  • Heavier analytics (re-ID, anomaly, crowd)
  • Regional command centre serving
  • Cross-district correlation
  ↓ metadata + cold-tier migration + selected evidence
STATE CORE
  • COLD + ARCHIVE storage
  • Statewide index (plates, faces, embeddings, events)
  • Statewide correlation and tracking
  • Government DB integrations
  • State command centre
```

**Why this matters and must be argued explicitly:** direct central ingestion of 80,000 streams requires ~192 Gbps of sustained backhaul into one facility (§4.9.1) and ~2 PB/day of central write. Edge recording reduces the wide-area requirement by **two to three orders of magnitude**, because only metadata and requested clips traverse the backbone. A submission that proposes flat central ingestion for 80,000 cameras has not engaged with the scale, and an informed evaluator will notice immediately. This single design decision is the strongest signal of competence you can send.

### 4.8.2 Inference pipeline (per edge node)

```
N RTSP streams
  → NVDEC hardware decode (batched, frames stay in GPU memory)
  → DeepStream / Savant pipeline
     → nvstreammux (batch across streams)
     → primary detector (vehicles, persons) — TensorRT INT8
     → nvtracker (NvDCF / ByteTrack)
     → secondary classifiers on tracked objects only:
         · plate detector → plate OCR
         · vehicle class + colour
         · person re-ID embedding (if enabled)
     → nvdsanalytics (line crossing, ROI occupancy, direction)
  → track-level aggregation and confidence voting
  → metadata messages → Kafka
  → evidence crops → local object store → async upstream
```

**Key efficiency decisions:** batch across streams in the muxer rather than processing streams independently; run secondary classifiers only on *tracked* objects rather than every detection; and keep frames in GPU memory from decode to inference. Each of these is worth a significant multiple in throughput, and together they are the difference between 500 GPUs and 2,000.

### 4.8.3 Additional analytics approaches

**Crowd counting.** Density-map regression (CSRNet, DM-Count) or point-based (P2PNet). Detection-based counting fails badly in dense crowds where heads overlap. Calibrate per camera using its homography so counts are comparable across viewpoints; report density (persons/m²) rather than raw counts, because that is what actually drives safety thresholds.

**Anomaly detection.** Weakly-supervised multiple-instance learning (RTFM, MGFN) trained on UCF-Crime is the pragmatic approach — it needs only video-level labels, not frame-level annotation. Supplement with rule-based detectors for well-defined anomalies (wrong-way movement, stopped vehicle on a carriageway, loitering beyond a threshold), which are more reliable and far more explainable. **Expect high false-positive rates from learned anomaly detection** and design the UI to present anomalies as ranked suggestions for review, never as alarms.

**Multi-camera vehicle tracking (re-ID).** Extract appearance embeddings (TransReID / FastReID) for each tracked vehicle, store in a vector database, and match across cameras using embedding similarity constrained by spatio-temporal plausibility (a vehicle cannot appear 60 km away in 4 minutes). Fuse with ANPR: when the plate is readable use it as ground truth; when it is not, fall back to appearance. This fusion is what makes tracking robust in real conditions and is a genuine technical differentiator.

**Face recognition.** RetinaFace or SCRFD for detection, ArcFace embeddings, vector search against an authorised watchlist. **Governance is not optional here:** a separate role, mandatory purpose and case reference on every query, a similarity threshold tuned for very low false-positive rate (a false match has real consequences for a real person), human review before any action, and full immutable audit. Document the false-match-rate/true-match-rate trade-off explicitly with a chosen operating point and the reasoning behind it.

### 4.8.4 Load testing at scale — how to actually do this

This is a required deliverable and the one most teams fudge. The credible method:

1. **Generate synthetic camera streams.** FFmpeg looping a video file, published to MediaMTX, exposed as RTSP. A single 16-core machine can host several hundred such streams at low resolution. Distribute across a handful of machines (or cheap spot cloud instances) to reach 1,000–2,000 concurrent synthetic cameras.
2. **Benchmark one full ingestion node** to saturation: measure maximum concurrent streams, CPU, GPU utilisation, memory, network, and disk write throughput. Find the *actual* breaking point and record what breaks first.
3. **Benchmark one GPU analytics node** the same way: streams per GPU at a given model, resolution, and analytic frame rate, with and without TensorRT/INT8, with and without batching. Publish the curve, not a single number.
4. **Benchmark the storage tier:** sustained write throughput, tier-migration rate, retrieval latency from each tier.
5. **Benchmark the metadata path:** Kafka throughput, ClickHouse ingest rate, OpenSearch indexing rate, and query latency at 10⁸–10⁹ indexed detections (generate these synthetically — you do not need real video to test the index).
6. **Project with stated assumptions.** Derive nodes required, GPUs required, storage required, and bandwidth required for 80,000 cameras. Show the arithmetic. State every assumption. Identify where linearity breaks down (network fan-in, metadata hot partitions, storage rebuild times) rather than assuming it holds forever.
7. **Report honestly**, including what you could not test and what would need validation at scale.

**A measured benchmark of 200 streams with a transparent projection to 80,000 is worth far more than an unsupported claim of 80,000.** Say so in the report.

## 4.9 System Architecture and Capacity Model

### 4.9.1 Bandwidth and storage arithmetic (planning estimates)

**Assumed camera mix at 80,000 cameras, H.265:**

| Class | Count | Bitrate | Aggregate |
|---|---|---|---|
| 2 MP @ 15 fps | 48,000 (60%) | 1.5 Mbps | 72 Gbps |
| 4 MP @ 15 fps | 24,000 (30%) | 3 Mbps | 72 Gbps |
| 8 MP @ 15 fps | 8,000 (10%) | 6 Mbps | 48 Gbps |
| **Total** | **80,000** | | **≈ 192 Gbps** |

**Derived storage, continuous recording:**

| Metric | Value |
|---|---|
| Aggregate write rate | 192 Gbps ÷ 8 ≈ **24 GB/s** |
| Per day | 24 GB/s × 86,400 s ≈ **2.07 PB/day** |
| 30 days, raw | **≈ 62 PB** |
| 30 days with 3× replication | ≈ 186 PB — **not viable** |
| 30 days with erasure coding (8+3, ×1.375) | **≈ 85 PB** |

**With tiering and transcoding (the realistic plan):**

| Tier | Days | Effective rate | Logical volume |
|---|---|---|---|
| Hot (full rate, at edge) | 7 | 2.07 PB/day | 14.5 PB |
| Warm (⅓ bitrate) | 23 | 0.69 PB/day | 15.9 PB |
| Cold (1/10 bitrate) | 60 | 0.21 PB/day | 12.4 PB |
| **Total logical (90 days)** | | | **≈ 43 PB** |
| **Raw disk with EC 8+3** | | | **≈ 59 PB** |

**Further reductions available and recommended:**

- **Event/motion-based recording** on low-value cameras: 40–70% reduction on that subset.
- **Edge-local hot tier** — the 14.5 PB hot tier is distributed across ~33 district nodes (~440 TB each), which is an entirely ordinary storage array, not an exotic one.
- **Selective retention by camera class** — a municipal park camera does not need the same retention as a border checkpoint.

**Conclusion to state explicitly:** even with aggressive tiering, statewide continuous recording at 80,000 cameras is a **tens-of-petabytes** problem. This is the argument for edge-first architecture, selective recording, and phased rollout — and presenting it with the arithmetic shown is far more persuasive than presenting a diagram.

### 4.9.2 GPU sizing (planning estimate — benchmark yours)

Throughput varies enormously with model, resolution, analytic frame rate, and pipeline efficiency. Use this as a **framework**, and replace the coefficient with your measured value:

```
GPUs_required = (cameras_under_analytics) / (streams_per_GPU)

Illustrative:  streams_per_GPU (NVIDIA L4, DeepStream, TensorRT INT8,
               1080p, 10 fps analytic rate, detector + tracker + ANPR)
               ≈ 25–40   ← MEASURE THIS YOURSELF

If 20% of cameras run analytics:  16,000 / 30 ≈ 533 GPUs
If 100% of cameras run analytics: 80,000 / 30 ≈ 2,667 GPUs
```

**The practical conclusion:** analytics coverage is a budget decision, not a technical one. Recommend a **tiered analytics policy** — 100% ANPR on transport corridors and checkpoints, motion and counting analytics broadly, face recognition on a small authorised subset only. Present this as a cost/coverage curve so decision-makers can choose a point on it. That framing is exactly what a state IT department needs and almost no one provides.

### 4.9.3 Reference architecture

```
╔═══════════════════════════════════════════════════════════════════════╗
║ EDGE TIER — one node per district / municipal zone (≈ 33 nodes)        ║
║  Cameras (≈2,400 avg/node) → RTSP over local network                  ║
║  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────────────────┐ ║
║  │ Ingest     │ │ Recorder   │ │ GPU      │ │ Local object store    │ ║
║  │ MediaMTX   │ │ fMP4 seg   │ │ analytics│ │ HOT tier ~440 TB      │ ║
║  │ + NVDEC    │ │ + hashing  │ │DeepStream│ │ NVMe + HDD            │ ║
║  └────────────┘ └────────────┘ └──────────┘ └──────────────────────┘ ║
║  k3s / KubeEdge · store-and-forward buffer for WAN outage             ║
║  UPSTREAM: metadata + alerts + evidence crops + requested clips ONLY  ║
╚════════════════════════════════╤══════════════════════════════════════╝
                                 │ SD-WAN / MPLS  (kbps–Mbps, not Gbps)
╔════════════════════════════════▼══════════════════════════════════════╗
║ REGIONAL TIER — 3–4 data centres (active-active)                      ║
║  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────────────────┐ ║
║  │ WARM tier  │ │ Heavy      │ │ Regional │ │ Kafka · Flink        │ ║
║  │ Ceph EC    │ │ analytics  │ │ command  │ │ regional correlation │ ║
║  │ transcoded │ │ re-ID·crowd│ │ centre   │ │                      │ ║
║  └────────────┘ └────────────┘ └──────────┘ └──────────────────────┘ ║
╚════════════════════════════════╤══════════════════════════════════════╝
                                 │ Dark fibre / state backbone
╔════════════════════════════════▼══════════════════════════════════════╗
║ STATE CORE — primary + DR site                                        ║
║  ┌──────────────────────────────────────────────────────────────────┐║
║  │ COLD + ARCHIVE: Ceph EC (deep) + LTO-9 tape library               │║
║  ├──────────────────────────────────────────────────────────────────┤║
║  │ STATEWIDE INDEX: ClickHouse (events) · OpenSearch (search)        │║
║  │                  Milvus (face/vehicle embeddings) · PostGIS       │║
║  ├──────────────────────────────────────────────────────────────────┤║
║  │ STATEWIDE SERVICES: vehicle tracking · correlation · watchlists   │║
║  ├──────────────────────────────────────────────────────────────────┤║
║  │ INTEGRATION DMZ (isolated): VAHAN · SARATHI · eGujCop · NAFIS     │║
║  │   → purpose-bound · rate-limited · fully audited · mTLS           │║
║  ├──────────────────────────────────────────────────────────────────┤║
║  │ SECURITY: Vault+HSM · Keycloak · Istio mTLS · SIEM · WORM audit   │║
║  └──────────────────────────────────────────────────────────────────┘║
║  STATE COMMAND CENTRE — video wall · statewide map · case management  ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### 4.9.4 Redundancy and disaster recovery targets

| Data class | RPO | RTO | Mechanism |
|---|---|---|---|
| Live streams | 0 (transient) | < 30 s | Redundant ingest paths; edge store-and-forward buffers during WAN outage |
| Hot recordings | < 5 min | < 15 min | Local RAID/EC + async replication to region |
| Metadata & index | < 1 min | < 5 min | Synchronous replication; Kafka retention as replay buffer |
| Case & evidence data | **0** | < 5 min | Synchronous multi-site replication; WORM |
| Audit logs | **0** | < 5 min | Append-only, replicated, off-site |
| Config & IaC | < 1 h | < 30 min | Git-backed, ArgoCD reconciliation |

**Failure-mode design:** edge nodes buffer locally and continue recording through a WAN outage — a district must never lose video because a fibre was cut. Regional data centres are active-active so a site loss degrades capacity, not function. The state core has a full DR site with tested, documented, and *rehearsed* failover; an untested runbook is not a DR plan, and saying so in the document demonstrates operational maturity.

## 4.10 Development Requirements

**Prototype (the version you can actually build)**

| Resource | Specification |
|---|---|
| Compute | 1–2 servers: 16–32 vCPU, 64–128 GB RAM |
| **GPU** | 1–2 × NVIDIA L4 / T4 / RTX 4090 (≥ 16 GB VRAM preferred for DeepStream + multiple models) |
| Storage | 4–8 TB, partitioned to simulate hot (NVMe) / warm (SSD) / cold (HDD) tiers — **physically distinct volumes**, so tiering is real and demonstrable rather than simulated |
| Cameras | 2–4 real IP cameras + 20–50 simulated streams |
| Load-test rig | 2–4 additional machines (or spot cloud instances) generating 500–2,000 synthetic streams |
| Cloud equivalent | AWS `g5.2xlarge`/`g6.2xlarge`, GCP `g2-standard-8` (L4), Azure `NC`-series; spot instances for the load-test rig |

**Production (statewide, indicative)**

| Component | Indicative scale |
|---|---|
| Edge nodes | ~33 × (32–64 cores, 256 GB RAM, 2–4 GPUs, 400–500 TB storage) |
| Regional DCs | 3–4 × (multi-rack: ~200 cores, ~50 GPUs, 5–10 PB Ceph each) |
| State core | Primary + DR: 20–40 PB cold storage, LTO-9 library, ClickHouse/OpenSearch/Milvus clusters, integration DMZ |
| Total GPUs | 500–2,700 depending on analytics coverage policy (§4.9.2) |
| Network | 100 GbE core, 10–40 GbE regional, 1–10 Gbps district uplinks, MPLS/dark fibre backbone |
| Power/cooling | Multi-megawatt across sites — a genuine constraint that belongs in the architecture note |

**Team profile (production programme):** this is a multi-year, multi-crore systems-integration programme requiring 30–60 engineers across video, ML, infrastructure, security, and application teams, plus a dedicated programme management and governance function. **State this honestly** — a document that presents a statewide VMS as a small project loses credibility instantly.

**Team profile (prototype):** 1 video engineer, 2 ML engineers, 1 infrastructure/K8s engineer, 1 backend, 1 frontend, 1 security/architecture author. Approximately 24–36 person-weeks.

## 4.11 Implementation Approach

**Phase 0 — Architecture and capacity model first (days 1–6).** Before writing code: the tiered topology, the capacity arithmetic of §4.9.1, the GPU sizing framework, the storage tiering policy, the DR targets, and the security architecture skeleton. **In Model 4 the documents are the primary deliverables**, so they should be started first and refined throughout, not written in the last week.

**Phase 1 — Ingestion and recording core (days 5–14).** MediaMTX ingest, segmented fMP4 recorder with hashing, camera provisioning from the Model 1 registry, health monitoring, storage abstraction over MinIO/Ceph.

**Phase 2 — Tiered storage (days 12–20).** Physically distinct hot/warm/cold volumes, lifecycle policy engine, transcoding on tier migration, retrieval from every tier, legal hold, automatic expiry with deletion certificates, integrity hash chain. **Demonstrate actual physical movement between tiers** — this is a required deliverable and it is easy to fake and easy to catch.

**Phase 3 — Analytics (days 15–30, parallel).** DeepStream/Triton pipeline; ANPR first (highest value); then vehicle counting and classification; then crowd counting; then anomaly detection; then vehicle re-ID if time permits. TensorRT/INT8 optimisation. Face recognition last, and only with the governance controls of §4.8.3 in place.

**Phase 4 — Statewide tracking (days 25–34).** Plate index in ClickHouse/OpenSearch, embedding index in Milvus, sighting query, route reconstruction with OSRM road-snapping and map rendering, plate/appearance fusion, convoy detection, watchlist alerting. **This is your headline demo — budget for making it visually excellent.**

**Phase 5 — Integration adapters (days 30–36).** Contract-first VAHAN, SARATHI, eGujCop, NAFIS adapters against mocks, with purpose-bound access, caching, rate limiting, and full audit. Write the swap-in procedure.

**Phase 6 — Command centre UI (days 28–38, parallel).** Video wall, synchronised multi-camera playback, timeline with event markers, statewide map, search, alerts, case management, evidence export with chain-of-custody manifest.

**Phase 7 — Load testing and the reports (days 34–44).** Synthetic stream generation at scale, node saturation benchmarks, GPU throughput curves, storage and metadata benchmarks, the projection to 80,000 with stated assumptions. Then finalise the DR design, the security architecture document, and a DR failover rehearsal.

**Sequencing advice:** the load-test rig should be built early (Phase 1–2), not at the end. Teams that leave it to the final week produce a projection with no measurement behind it, which is exactly the failure mode this deliverable is designed to detect.

## 4.12 Expected Deliverables

1. **Working centralised VMS prototype** — multi-source ingestion, recording, live view, synchronised playback, and camera management through one platform, demonstrated with feeds representing at least two departments.
2. **ANPR and multi-location vehicle tracking demonstration** — live plate recognition, and a vehicle tracked across ≥ 3 camera locations with an ordered route on a map, timestamps, evidence crops, and inter-sighting speed. This is the centrepiece.
3. **Scalability and load-test report for ~80,000 cameras** — measured benchmarks of ingestion, GPU analytics, storage, and metadata tiers; the full capacity model; the projection with every assumption stated; identification of where linearity breaks; and an honest account of what was not tested.
4. **Disaster-recovery and redundancy design** — failure-mode analysis, RPO/RTO table per data class, replication topology, edge buffering behaviour, failover runbooks, and results of a rehearsed failover test.
5. **Security architecture document** — threat model, network segmentation diagram, encryption design (in transit, at rest, key management), RBAC/ABAC model, immutable audit design, purpose-limitation enforcement, **DPDP Act 2023 alignment analysis**, evidence integrity and §65B admissibility approach, and a proportionality note on face recognition.
6. **Tiered storage demonstration** — data physically moving hot → warm → cold, with retrieval from each tier and lifecycle policy enforcement shown.
7. **Government integration adapters** — VAHAN/SARATHI/eGujCop/NAFIS contract-first implementations with mocks, interface documentation, and the swap-in procedure.
8. **Analytics accuracy report** — per-capability benchmarks with methodology, test sets, results, failure galleries, and honest limitations.
9. **Deployment package and operations documentation** — Helm charts, Terraform/Ansible, capacity planning calculator, runbooks.

## 4.13 Evaluation and Success Criteria

**Ingestion and recording**

| Metric | Target |
|---|---|
| Concurrent streams per ingestion node | Measured and documented (expect 200–500 per well-specified node) |
| Recording continuity | Zero frame loss over a 24-hour soak test |
| Ingest-to-recorded latency | < 10 s |
| Recovery from source outage | Automatic within 30 s, no gap beyond the outage window |
| Edge buffering during WAN outage | Recording continues; backlog forwards correctly on restoration |

**Storage**

| Metric | Target |
|---|---|
| Hot → warm → cold migration | Executes on policy; verified by physical location |
| Retrieval latency | Hot < 1 s, warm < 5 s, cold < 60 s |
| Integrity | Hash verification passes on every retrieved segment |
| Legal hold | Held footage survives an expiry cycle that deletes everything else |
| Expiry | Expired footage is unrecoverable; deletion certificate generated |

**Analytics**

| Capability | Target |
|---|---|
| ANPR (good conditions) | ≥ 90% exact match, ≥ 95% within-one-character |
| Vehicle detection | ≥ 95% mAP@0.5 on the test set |
| Vehicle classification | ≥ 90% accuracy across 6 classes |
| Crowd counting | MAE < 15% of true count at moderate density |
| Anomaly detection | AUC ≥ 0.80 on UCF-Crime; **and a documented false-positive rate at the chosen operating threshold** |
| Vehicle re-ID | Rank-1 ≥ 80%, mAP ≥ 70% on VeRi-776 |
| Face recognition (if built) | TAR ≥ 95% at FAR = 1e-5; **operating point and rationale documented** |
| GPU throughput | Measured streams/GPU curve published, not a single asserted figure |

**Vehicle tracking**

- ≥ 3-camera route reconstruction correct in the demonstration.
- Statewide plate query over ≥ 10⁸ indexed detections returns in < 2 s.
- Impossible transitions detected and flagged, not silently accepted.
- Convoy detection identifies planted co-travelling vehicles in the test scenario.

**Scale projection credibility (how this deliverable is actually judged)**

- Every projection traceable to a measurement.
- Every assumption stated and justified.
- Bottlenecks identified with the evidence that identified them.
- Non-linear effects acknowledged rather than assumed away.
- Limitations stated plainly. **An honest "we measured 400 streams and here is why we believe it extrapolates, and here is where it might not" is the strongest possible answer.**

**Security and compliance**

- Full RBAC/ABAC matrix tested, including negative cases.
- No plaintext credentials anywhere; verified by scan.
- Audit log immutable and complete; verified by attempted tampering.
- Purpose-bound access enforced at the API, not merely in the UI.
- DPDP alignment analysis reviewed against the Act's actual text.
- Failover test executed and documented.

## 4.14 Dependencies and Risks

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Scale is impossible to demonstrate directly | Core deliverable cannot be met literally | **Certain** | Reframe as measure-then-project; build the load-test rig early; be transparent about what was and was not tested |
| R2 | Insufficient GPU access for the prototype | Analytics cannot be shown at meaningful scale | High | Cloud spot GPU instances; INT8 quantisation; demonstrate on fewer streams with a published throughput curve |
| R3 | Storage cost at true scale is politically prohibitive | Model is rejected on economics | **High** | Lead with the tiering, edge-recording, and selective-recording economics; present the cost/coverage curve as a decision instrument rather than defending a single number |
| R4 | Departments resist replacement of their VMS | Adoption fails regardless of technical merit | **Very High** | Present a phased migration path with Model 3 federation as the transitional state; do not present Model 4 as a big-bang cutover |
| R5 | Government DB access unobtainable | Integration deliverable appears unmet | **Certain** | Contract-first adapters with documented mocks, framed as the correct engineering response — see §0.2.2 |
| R6 | Face recognition attracts legal or civil-society challenge | Programme delay or cancellation | **Medium-High** | Rigorous governance design; proportionality analysis; consider demonstrating on synthetic/consented faces only; make the controls a visible feature of the submission |
| R7 | Network backbone insufficient for even the metadata path | Architecture invalid in practice | Medium | Edge-first design minimises WAN dependence; quantify actual WAN requirement per district and state it as a prerequisite |
| R8 | Anomaly detection false-positive rate makes it operationally useless | Feature discredited | **High** | Present as ranked review suggestions, not alarms; combine learned detection with explainable rule-based detectors; report FPR honestly |
| R9 | Clock skew across 80,000 cameras | Statewide tracking produces wrong sequences | High | PTP at the core, NTP everywhere, per-camera offset detection and correction, dual timestamps |
| R10 | Vendor lock-in on GPU (CUDA/DeepStream) | Procurement inflexibility | Medium | Abstract the inference layer behind a serving interface; validate an ONNX Runtime / OpenVINO fallback path |
| R11 | Erasure-coding rebuild times at petabyte scale | Extended degraded windows after disk failure | Medium | Model rebuild time explicitly in the DR design; choose EC parameters with rebuild in mind, not only overhead |
| R12 | Prototype scope creep across six analytics capabilities | Nothing finished well | **High** | Strict priority order: ANPR → tracking → counting → crowd → anomaly → face. Ship three excellently rather than six poorly |

**Key assumptions:** state backbone connectivity to district nodes; capital funding at programme scale; political mandate to consolidate; cameras are IP-based and reachable (analogue cameras need encoders, which is a separate cost line); power and cooling available at edge sites.

## 4.15 Estimated Complexity

**Overall: 5 / 5 — Very High.** The most demanding of the four by a wide margin, and the only one that cannot be completed as specified within a project timeline.

| Area | Effort | Difficulty | Notes |
|---|---|---|---|
| Ingestion at scale | Very High | **Very High** | The hierarchical topology is the make-or-break design decision |
| Recording and tiered storage | High | **High** | Lifecycle, integrity, and legal hold are all genuinely hard |
| Analytics suite (6 capabilities) | Very High | **Very High** | Each is a substantial ML project in its own right |
| Statewide tracking and re-ID | High | **Very High** | Multi-camera tracking is an open research problem, not solved engineering |
| Government integrations | Medium | Medium | Contract design is easy; access is the blocker |
| Redundancy and DR | High | High | Largely design work, but design that must be right |
| Security architecture | High | **High** | Threat modelling and DPDP analysis are specialist work |
| Load testing and projection | High | **High** | The most under-invested deliverable and the most discriminating one |
| Command centre UI | High | Medium | Large surface, moderate individual difficulty |

**Where teams lose points:** attempting all six analytics capabilities and finishing none; asserting 80,000-camera scale with no measurement; proposing flat central ingestion; and treating the security and DR documents as an afterthought when they are three of the five required deliverables.

**Where teams win:** the edge-first architecture argued with arithmetic; a measured, honest scalability projection; a visually excellent multi-camera vehicle-tracking demo; and a security architecture that engages seriously with the DPDP Act. **Depth on the documents beats breadth on the features in this model.**
---

# Appendix A — Canonical Camera Metadata Schema

Shared across all four models. Model 1 is its system of record; Models 2–4 consume and extend it. Designed so that a camera from any department, any vendor, and any vintage maps into one representation without free-text chaos.

```yaml
camera:
  # ─── Identity ───────────────────────────────────────────────
  id: uuid                              # internal primary key
  urn: string                           # urn:cctv:{dept_code}:{native_id}
  asset_tag: string                     # departmental asset number
  native_id: string                     # ID in the source system
  source_system_id: uuid                # which VMS/NVR owns it (Models 2–4)
  name: string
  description: text

  # ─── Ownership & governance ─────────────────────────────────
  department_id: fk                     # controlled vocabulary
  sub_department: string
  owning_entity: string                 # for PPP / third-party assets
  ownership_model: enum                 # owned | leased | ppp | citizen_contributed
  custodian_name: string
  custodian_contact: string
  nodal_officer_id: fk
  funding_source: string                # e.g. Smart City Mission, state budget

  # ─── Location ───────────────────────────────────────────────
  geom: geography(Point, 4326)          # PostGIS — the authoritative position
  latitude: decimal(10,7)
  longitude: decimal(10,7)
  altitude_m: decimal                   # nullable
  coordinate_precision: enum            # surveyed | gps | map_picked | geocoded | approximate
  address_line: string
  landmark: string
  ward_id: fk
  taluka_id: fk
  district_id: fk
  police_station_id: fk                 # nullable — jurisdiction routing
  zone: string
  location_type: enum                   # junction | road | market | transport_hub |
                                        # govt_building | school | hospital | park |
                                        # religious | industrial | residential | border | other

  # ─── Physical & optical ─────────────────────────────────────
  camera_type: enum                     # fixed_dome | fixed_bullet | ptz | anpr |
                                        # thermal | fisheye_360 | multisensor |
                                        # body_worn | mobile | drone
  make: fk                              # controlled vocabulary
  model: fk
  serial_number: string                 # unique where present
  resolution: enum                      # 1mp | 2mp | 4mp | 5mp | 8mp | 12mp | other
  sensor_mp: decimal
  lens_type: enum                       # fixed | varifocal | motorised_zoom
  focal_length_mm: decimal
  horizontal_fov_deg: decimal           # → coverage wedge rendering
  bearing_deg: decimal                  # 0–360, true north → coverage direction
  tilt_deg: decimal
  effective_range_m: decimal            # useful identification distance
  mounting_type: enum                   # pole | wall | ceiling | tower | gantry | vehicle
  mounting_height_m: decimal
  ir_capable: boolean
  ir_range_m: decimal
  weatherproof_rating: string           # IP66, IK10 …
  ptz_capable: boolean
  audio_capable: boolean

  # ─── Network & connectivity ─────────────────────────────────
  ip_address: inet                      # nullable — many are unreachable centrally
  mac_address: macaddr
  hostname: string
  connectivity_type: enum               # fibre | ethernet | wifi | rf_pt_to_pt | 4g | 5g | analogue
  bandwidth_mbps: decimal
  isp_provider: string
  network_segment: string
  onvif_compliant: boolean
  onvif_profiles: string[]              # [S, G, T, M]
  rtsp_url_template: string             # stored encrypted
  vendor_api_type: enum                 # none | isapi | dahua_http | milestone_mip |
                                        # genetec_sdk | zoneminder | frigate | other
  credentials_ref: string               # vault path — NEVER the credential itself

  # ─── Recording & storage ────────────────────────────────────
  recording_mode: enum                  # continuous | motion | event | schedule | none
  primary_codec: enum                   # h264 | h265 | mjpeg | other
  primary_bitrate_kbps: integer
  primary_fps: integer
  substream_available: boolean
  substream_resolution: string
  retention_days: integer
  storage_location: string              # local_sd | nvr | dvr | central | cloud
  nvr_id: fk
  storage_capacity_gb: integer

  # ─── Operational status ─────────────────────────────────────
  operational_status: enum              # operational | degraded | down |
                                        # under_maintenance | decommissioned | unknown
  status_source: enum                   # probe | dept_api | manual | vms_reported
  status_reason_code: fk
  last_seen_at: timestamptz
  last_probe_at: timestamptz
  consecutive_failed_probes: integer
  downtime_hours_30d: decimal
  uptime_percent_30d: decimal

  # ─── Lifecycle ──────────────────────────────────────────────
  installation_date: date
  commissioning_date: date
  warranty_expiry: date
  amc_vendor: string
  amc_expiry: date
  expected_service_life_years: integer  # default 7, overridable by model
  age_years: computed
  is_ageing: computed                   # age > expected_service_life
  decommissioned_date: date
  replacement_camera_id: fk

  # ─── Integration & analytics readiness ──────────────────────
  integration_ready: boolean            # IP-based, reachable, ONVIF/API capable
  integration_blockers: string[]        # ["analogue", "no_network_route", "no_credentials"]
  analytics_enabled: boolean
  analytics_capabilities: string[]      # ["anpr","vehicle_count","crowd","anomaly","face"]
  analytics_priority: integer           # 1–5 — drives GPU allocation

  # ─── Spatial analytics helpers ──────────────────────────────
  h3_r8: string                         # precomputed — makes gap analysis fast
  h3_r9: string
  coverage_polygon: geography(Polygon)  # derived FOV wedge, indicative only

  # ─── Data quality & audit ───────────────────────────────────
  data_quality_score: integer           # 0–100, computed from completeness + warnings
  validation_warnings: jsonb
  extended_attributes: jsonb            # per-department extras, schema-registered
  native_payload: jsonb                 # verbatim source record (Models 2–4)
  created_at / created_by
  updated_at / updated_by
  source_of_record: enum                # manual | bulk_import | api | adapter_sync
  version: integer                      # optimistic locking
```

**Design notes worth defending:**

- **`extended_attributes` with a per-department schema registry** — gives departments room for their own fields without letting the core schema rot into free text.
- **`native_payload`** — preserves the source record verbatim for audit, round-tripping, and debugging mapping errors.
- **`credentials_ref`, never credentials** — the schema physically cannot leak a password.
- **`coordinate_precision` and `data_quality_score`** — make data quality visible rather than pretending all records are equal.
- **`integration_blockers`** — turns the registry into a direct input for Model 2/3/4 planning, which is the whole point of Model 1 being foundational.
- **Precomputed H3 columns** — turn gap analysis from a heavy spatial join into a `GROUP BY`.

---

# Appendix B — Consolidated Dataset Register

| # | Dataset | Type | Used by | Licence / access | Link |
|---|---|---|---|---|---|
| **Geospatial** ||||||
| B1 | OpenStreetMap (Geofabrik India) | Roads, POIs, buildings | M1, M2, M4 | ODbL, free | [download.geofabrik.de](https://download.geofabrik.de/asia/india.html) |
| B2 | Datameet Maps | Indian admin boundaries | M1, M3, M4 | Community, free | [github.com/datameet/maps](https://github.com/datameet/maps) |
| B3 | india-geodata | Districts, census geometries, GeoJSON/Parquet | M1 | Open | [github.com/yashveeeeeeer/india-geodata](https://github.com/yashveeeeeeer/india-geodata) |
| B4 | INDIAN-SHAPEFILES | Shapefiles & GeoJSON by category | M1 | Community | [github.com/datta07/INDIAN-SHAPEFILES](https://github.com/datta07/INDIAN-SHAPEFILES) |
| B5 | Survey of India | Authoritative boundaries | M1 (production) | Registration | [onlinemaps.surveyofindia.gov.in](https://onlinemaps.surveyofindia.gov.in/) |
| B6 | ISRO Bhuvan | Satellite imagery, LULC, WMS/WFS | M1, M4 | Free, registration | [bhuvan.nrsc.gov.in](https://bhuvan.nrsc.gov.in/) |
| B7 | Census of India 2011 | Ward/village population | M1 | Free | [censusindia.gov.in](https://censusindia.gov.in/) |
| B8 | WorldPop / GHSL | Gridded population, built-up area | M1 | Free | [worldpop.org](https://www.worldpop.org/) · [ghsl.jrc.ec.europa.eu](https://ghsl.jrc.ec.europa.eu/) |
| B9 | data.gov.in | National open data | M1 | Free | [data.gov.in](https://data.gov.in/) |
| B10 | IUDX | Smart-city data exchange (incl. Gujarat cities) | M1, M3 | Free, registration | [iudx.org.in](https://iudx.org.in/) |
| **ANPR / plates** ||||||
| B11 | Roboflow Universe — Indian number plates | Annotated detection | M2, M4 | Varies per dataset | [universe.roboflow.com](https://universe.roboflow.com/anpr-gfpt1/indian-number-plate-bkaj2) |
| B12 | DataCluster Labs — Indian Number Plates | Real-world Indian plates | M2, M4 | Check terms | [Roboflow](https://universe.roboflow.com/datacluster-labs-agryi/indian-number-plates-9oobq) · [Hugging Face](https://huggingface.co/datasets/Dataclusterlabspvtltd/indian-number-plates-dataset) |
| B13 | `sanchit2843/Indian_LPR` | Indian LPR dataset + weights | M2, M4 | Open source | [github.com/sanchit2843/Indian_LPR](https://github.com/sanchit2843/Indian_LPR) |
| B14 | `sid0312/ANPR` | Indian plate detection/recognition | M2, M4 | Open source | [github.com/sid0312/ANPR](https://github.com/sid0312/ANPR) |
| B15 | CCPD | 250k–300k Chinese plates — **pretraining** | M2, M4 | Academic | GitHub: `detectRecog/CCPD` |
| B16 | UFPR-ALPR | Brazilian ALPR benchmark | M2, M4 | Academic, request | UFPR |
| **Vehicles / traffic** ||||||
| B17 | India Driving Dataset (IDD) | Indian road scenes, Indian vehicle classes | M4 | Free, registration | [idd.insaan.iiit.ac.in](https://idd.insaan.iiit.ac.in/) |
| B18 | UA-DETRAC | Vehicle detection + tracking | M2, M4 | Academic | — |
| B19 | BDD100K | 100k driving videos, detection/segmentation | M2, M4 | Academic | [bdd-data.berkeley.edu](https://bdd-data.berkeley.edu/) |
| B20 | VeRi-776 | Vehicle re-ID, 776 vehicles / 20 cameras | M4 | Academic | [github.com/JDAI-CV/VeRidataset](https://github.com/JDAI-CV/VeRidataset) |
| B21 | VERI-Wild | Large-scale vehicle re-ID | M4 | Academic | — |
| B22 | AI City Challenge | Multi-camera vehicle tracking, ANPR | M4 | Free, registration | [aicitychallenge.org](https://www.aicitychallenge.org/) |
| **Crowd** ||||||
| B23 | ShanghaiTech Part A/B | Crowd counting benchmark | M4 | Academic | — |
| B24 | UCF-QNRF | 1,535 images, dense crowds | M4 | Academic | UCF CRCV |
| B25 | NWPU-Crowd / JHU-CROWD++ | Large-scale crowd counting | M4 | Academic | — |
| **Anomaly** ||||||
| B26 | UCF-Crime | 1,900 surveillance videos, 13 anomaly classes | M4 | Academic | UCF CRCV |
| B27 | ShanghaiTech Campus | Video anomaly detection | M4 | Academic | — |
| B28 | CUHK Avenue | Video anomaly detection | M4 | Academic | — |
| B29 | XD-Violence | Weakly-supervised violence detection | M4 | Academic | — |
| **Face** ⚠️ ||||||
| B30 | LFW / IJB-C | Face verification benchmarks | M4 | Academic | — |
| B31 | **Synthetic faces (StyleGAN) or consented images** | **Recommended for demonstration** | M4 | Self-generated | — |
| **Internally generated** ||||||
| B32 | Synthetic camera registry (25k–80k) | Camera inventory | M1–M4 | Own | §1.5 D-1 |
| B33 | Event simulator corpus | Federation/correlation testing | M3 | Own | §3.5 |
| B34 | Synthetic RTSP stream farm | Load testing | M2, M4 | Own | §4.8.4 |
| B35 | Government DB mock records | Integration testing | M4 | Own | §0.2.2 |
| B36 | Self-captured traffic footage | ANPR demo and validation | M2, M4 | Own | §2.5 D-3 |

> **Licence discipline:** for a government-facing submission, check and record the licence of every dataset and every pretrained weight you use, and keep the record as an artefact. Two specific traps: **Ultralytics YOLOv8/v11 is AGPL-3.0** (viral copyleft — a real problem for closed government deployments), and several face datasets have use restrictions or have been withdrawn. An Apache-2.0 or MIT alternative exists for almost every component; choosing one and documenting why is a mark of professionalism.

---

# Appendix C — Consolidated API and Integration Register

## C.1 Standards and protocols

| Standard | Purpose | Used by | Notes |
|---|---|---|---|
| **RTSP** (RFC 2326) + RTP/RTCP | Video transport | M2, M4 | Universal; the reliable fallback for every device |
| **ONVIF Profile S** | Streaming, PTZ, discovery | M2, M3, M4 | The interoperability baseline — **expect vendor non-conformance** |
| **ONVIF Profile G** | Recording and replay | M2, M4 | Playback from departmental storage |
| **ONVIF Profile T** | Advanced streaming, H.265, analytics metadata | M2, M4 | |
| **ONVIF Events** (WS-BaseNotification) | Device and analytics events | M3 | The push-event source for the ONVIF adapter |
| **WS-Discovery** | Camera auto-discovery | M2, M3 | UDP multicast; subnet-scoped |
| **WebRTC / WHEP** | Browser playback, sub-second | M2, M4 | The right choice for control-room live view |
| **LL-HLS / HLS** | Browser playback, scalable | M2, M4 | Fallback and high-fan-out viewing |
| **SRT / RTMP** | Contribution transport | M4 | Robust over lossy WAN links |
| **CloudEvents 1.0** (current v1.0.2) | Event envelope | M3, M4 | Gives you a standards-based canonical envelope for free |
| **MQTT** | Lightweight event transport | M3 | Frigate and many IoT-style sources |
| **OpenAPI 3.1 / AsyncAPI 2.6** | API documentation | All | AsyncAPI for event contracts — rarely done, always noticed |
| **OGC WMS / WFS / MVT** | Geospatial services | M1 | |
| **NTP / PTP (IEEE 1588)** | Time synchronisation | M2, M3, M4 | **Underrated** — correlation quality depends on it |
| **SAML / OIDC / OAuth2** | Identity federation | All | |
| **ISO 27001, ISO 22301, NIST SP 800-53, CERT-In directions** | Security and continuity frameworks | M4 | Reference these by name in the security document |

## C.2 Vendor interfaces

| Vendor | Interface | Access | Recommendation |
|---|---|---|---|
| Hikvision | **ISAPI** (HTTP + digest auth) | Free documentation, no SDK licence | **Best first vendor adapter** — accessible and well documented |
| Dahua | HTTP API / SDK | Free docs | Good second |
| CP Plus | ONVIF + HTTP | Widely deployed in India | Use ONVIF path |
| Axis | VAPIX | Free docs | Excellent ONVIF conformance |
| Bosch | RCP+ / ONVIF | Docs available | |
| Milestone XProtect | MIP SDK / MIP VMS API | **Licence required** | Document the contract, mock the implementation |
| Genetec Security Center | SDK / Web SDK | **Licence required** | Same |
| ZoneMinder | REST API | Open source | Ideal simulated source |
| Frigate | HTTP API + MQTT | Open source | Ideal *dissimilar* simulated source |
| Shinobi | REST API + WebSocket | Open source | Third simulated source |

## C.3 Government and third-party services

| Service | Purpose | Reality | Approach |
|---|---|---|---|
| **VAHAN** | Vehicle registration lookup | No public API; G2G via NIC, or commercial resellers (Surepass, Signzy, IDfy, Cashfree, Masters India) | **Contract-first adapter + mock** |
| **SARATHI** | Driving licence | Same | **Mock** |
| **DigiLocker** | Citizen-consented RC/DL documents | Public API with partner onboarding | Viable for consented flows only, not bulk lookup |
| **eGujCop** | Gujarat Police operations | Closed | **Mock** |
| **AFIS / NAFIS** | Fingerprint identification (NCRB) | Closed | **Mock** |
| **FASTag / NETC** | Toll transactions — a genuine vehicle-movement signal | NPCI-governed, restricted | Worth mentioning as a future correlation source |
| Nominatim / Mappls | Geocoding | Free (self-host) / commercial | Self-host Nominatim for bulk; Mappls for Indian address accuracy |
| OSRM / Valhalla | Road-network routing | Open source, self-hostable | Road-snapping for route reconstruction |
| SMS / email gateway | Notifications | State MSDG gateway or commercial | |

---

# Appendix D — Demonstration and Test Asset Sources

Common to Models 2, 3, and 4. The recurring problem is that no real departmental system will be available; every one of these is a way around that.

| Need | Solution |
|---|---|
| **A second (and third) "departmental VMS"** | Self-host **ZoneMinder** (PHP/MySQL, REST, pull) and **Frigate** (Python/MQTT, push) on separate hosts. They are architecturally dissimilar, which is what makes the integration claim honest. Add **Shinobi** for a third. |
| **Video to feed them** | Loop recorded footage with FFmpeg, published as RTSP by **MediaMTX**. One command per simulated camera. |
| **Realistic traffic footage** | Self-captured (best — unambiguously yours, and matches your demo camera angles), IDD, UA-DETRAC, AI City Challenge, permissively-licensed dashcam footage. |
| **A real camera** | One ONVIF-compliant IP camera (₹2,000–4,000). **Disproportionately valuable** — it exposes all the real-world ONVIF quirks that simulated sources hide, and it makes the demo unarguably real. |
| **Public test RTSP endpoints** | `rtsp.stream`, Wowza public test streams, standard sample streams. For connectivity smoke-testing only. |
| **Hundreds of streams for load testing** | FFmpeg + MediaMTX stream farm on 2–4 machines or spot cloud instances; low resolution, looped source. Several hundred streams per 16-core host. |
| **Millions of detection events** | Synthetic generator writing directly into ClickHouse/OpenSearch. You do not need real video to test index performance — decouple these. |
| **Realistic camera inventory** | Model 1's OSM-derived synthetic registry (§1.5). |
| **Government DB responses** | Mock services returning correctly-shaped synthetic records, with configurable latency and error injection so you can test your adapter's resilience. |
| **Correlation scenarios** | Scripted multi-source event sequences, including deliberate near-misses that must *not* correlate (§3.5). |

---

# Appendix E — Cross-Model Comparison and Selection Guidance

## E.1 Effort, risk and reward

| | Model 1 | Model 2 | Model 3 | Model 4 |
|---|---|---|---|---|
| **Complexity** | 2 / 5 | 4 / 5 | 3.5 / 5 | 5 / 5 |
| **Prototype effort (person-weeks)** | 8–12 | 16–24 | 14–20 | 24–36 |
| **Can be completed as specified?** | **Yes, fully** | Partially (subset of cameras) | Mostly | **No — by design** |
| **GPU required** | No | Yes (1–2) | **No** | Yes (many) |
| **ML expertise required** | No | **Essential** | No | **Essential** |
| **Distributed-systems expertise** | Low | Medium | **Essential** | **Essential** |
| **Infrastructure expertise** | Low | Medium | Medium | **Essential** |
| **Demo visual impact** | Medium-High (maps demo well) | **Very High** (live video + plate reads) | Medium (needs deliberate design effort) | **Very High** if the tracking demo lands |
| **Risk of not finishing** | **Low** | Medium-High | Medium | **High** |
| **Dependency on external cooperation** | Low | High | High | **Very High** |
| **Documentation weight in grading** | Low | Medium | Medium-High | **Very High** |

## E.2 Choosing by team strength

| Your team's strength | Choose | Why |
|---|---|---|
| Full-stack web, GIS, data modelling; no ML | **Model 1** | Completable to production quality; the gap-analysis weighting is a genuine differentiator |
| Computer vision and ML; comfortable with video | **Model 2** | ANPR and movement reconstruction are the most demonstrable capabilities in the whole programme |
| Backend architecture, distributed systems, integration; no ML | **Model 3** | No GPU, no models, no latency budget — pure architecture, and the extensibility proof is compelling |
| Infrastructure, Kubernetes, storage, security | **Model 4** | Three of five deliverables are architecture documents, which plays to exactly this strength |
| Small team (2–3), short timeline | **Model 1** | The only one reliably finishable |
| Large team (6+), long timeline, mixed skills | **Model 1 + Model 3**, or **Model 4** | Model 1+3 gives two complete, composable systems; Model 4 gives one ambitious one |

## E.3 The strongest combinations

**Model 1 + Model 3 — the best-architected answer.** The registry supplies the inventory; the middleware supplies interoperability; together they are a complete foundation on which any viewer or analytics service can be built. Neither needs a GPU. Both are finishable. The combination directly satisfies Model 1's own instruction that it "must be combined with one or more of the other proposed models."

**Model 1 + Model 2 — the most demonstrable answer.** The registry gives you a credible camera inventory to onboard from; the viewer gives you live video and plate search on screen. This is the combination that presents best in a live demo.

**Model 1 + Model 3 + Model 2's UI as a consumer of Model 3 — the most complete answer.** The viewer stops being a point-to-point integrator and becomes a client of the federation platform. This resolves the Model 2 / Model 3 tension cleanly and is the architecture most likely to be right in practice.

**Model 4 alone — the highest-ceiling, highest-risk answer.** Choose it only with a strong infrastructure team, real GPU access, and an appetite for writing serious architecture documents. Do not choose it hoping to build a working statewide system.

## E.4 The five things that most differentiate a submission

Applicable across all four models:

1. **Engage with the constraints rather than ignoring them.** Government API access is closed; departments will not cooperate; the scale is infeasible. Say so, and show the correct engineering response. Contract-first mocks, simulated source systems, and measured-then-projected scale are not compromises — they are the professional answer, and framing them that way is more persuasive than pretending the constraint does not exist.

2. **Measure, do not assert.** One benchmarked number with stated assumptions beats ten claimed capabilities. This is decisive in Model 4 and valuable everywhere.

3. **Build the boring things well.** Audit trails, RBAC enforced at the database layer, purpose-bound access, data-quality scoring, licence compliance. These are what separate a project that could be deployed by a state government from a demo.

4. **Make one thing genuinely excellent.** A route reconstruction that snaps to roads and renders beautifully; a gap-analysis report with a real insight; a correlation demo where two events visibly collapse into one incident. Depth on one capability beats breadth across six half-built ones.

5. **Show the seams honestly.** A limitations section that names what does not work, what was not tested, and what would need to change at scale reads as competence, not weakness. Every experienced evaluator has seen enough overclaiming to find honesty refreshing — and they will find the gaps anyway.

---

## Document Control

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 3 September 2026 |
| **Scope** | Models 1–4, statewide CCTV integration programme (Gujarat) |
| **Status** | Technical reference for solution design and build planning |

**Caveats.** Capacity, throughput, and cost figures marked *(planning estimate)* are order-of-magnitude and must be validated by measurement before procurement. Dataset and tool licences change — verify each before use. Government system access reflects publicly documented positions as of the document date and should be confirmed with the relevant department. Legal and regulatory statements are a technical summary, not legal advice; obtain qualified counsel before deployment, particularly regarding facial recognition and DPDP Act obligations.
