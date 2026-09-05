# Sentinel — Status and Roadmap

**Gujarat CCTV Integration Hackathon 2026 · Category 1 · Model 1 + Model 2**
Snapshot taken Saturday 5 September 2026, 19:50 IST. Submission closes **Sunday 7 September, 14:00**.

This is the one page to read if you have not followed the build. Part A is what
exists and has been verified. Part B is what still has to happen before the
form is submitted, in order, with who can do it. Part C is how the platform
grows from the thirty-camera prototype to the statewide estate, and what to
build next if the project continues after the hackathon.

Every number here was measured on this machine or on the organisers' sandbox.
Nothing is projected unless it says so.

---

## Part A — What is done

### A.1 Model 1: Central CCTV Registry and GIS Mapping

| Capability | State | Where |
|---|---|---|
| Camera registry, 30 sandbox cameras ingested | Done | `backend/app/routers/cameras.py` |
| Coordinates with provenance (`geo_source`, `geo_confidence`) | Done | `backend/app/geocoding.py` |
| Interactive statewide map, clustering, department filter | Done | `frontend/src/pages/MapPage.tsx` |
| Bulk import (CSV/XLSX) with downloadable template | Done | `/api/v1/cameras/bulk-import` |
| Camera health status (reachable / degraded / down) | Done | `/api/v1/cameras/health-status` |
| Coverage gap analysis across 33 districts | Done | `backend/app/gap_analysis.py` |
| Department-wise data requirements and integration contract | Done | `DOCS/HLD.md` §3 |

The gap analysis currently reports **18.2 % nominal coverage, 27 districts with
no camera, worst gap Chhota Udaipur at 156 km**. That is a statement about the
sandbox catalogue, not the state, and the document says so.

No coordinate was invented. Each camera carries the source it came from:
a hand-verified fix, Nominatim within the Gujarat bounding box, a district
centroid, or `None` when nothing could be justified.

### A.2 Model 2: Unified Viewing Platform, ANPR and Watchlist

| Capability | State | Where |
|---|---|---|
| Live video wall, 1×1 / 2×2 / 3×3, quality profiles | Done | `frontend/src/pages/VideoWallPage.tsx`, `LiveTile.tsx` |
| RTSP → MJPEG relay, one upstream per camera shared by all viewers | Done | `backend/app/live_relay.py` |
| HLS proxy that rewrites segment and AES key URIs | Done | `backend/app/routers/cameras.py` |
| ANPR pipeline: detection, tiling, tracking, voting, grammar | Done | `backend/app/vision.py`, `plate_grammar.py` |
| Plate search: exact, partial, fuzzy (`pg_trgm`) | Done | `backend/app/routers/detections.py` |
| Route reconstruction with OSRM snapping and impossible-transition flags | Done | `/api/v1/detections/route/{plate}` |
| Watchlist with alert workflow (new → acknowledged → closed) | Done | `backend/app/routers/watchlist.py`, `alerts.py` |
| **Partial reads** — searchable, badged, never alertable | Done 5 Sept 19:45 | `backend/tools/index_partial_reads.py` |
| VAHAN adapter: contract, mock implementation, credential notes | Done | `backend/app/adapters/vahan.py`, HLD §10 |
| XLSX and PDF output report | Done | `/api/v1/analytics/report/xlsx`, `/report/pdf` |
| Audit trail: every search recorded with purpose and actor | Done | `audit_log` table |

### A.3 Security and operations

- Three roles, dependency-injected on every route: `state_admin` > `dept_operator` > `viewer`.
- JWT bearer tokens; audit actor comes from the verified token, never from a query parameter.
- Security headers (CSP, frame-deny, HSTS), rate limiting (10/min auth, 300/min otherwise, video exempt), request IDs.
- **No credential ever reaches the browser.** Camera serialisation strips `rtsp_url` and `whep_url`; video goes through the relay or proxy.
- `docker-compose.yml`, Dockerfiles and nginx config for one-command deployment.
- 72 automated tests, all passing, 0.25 s.

### A.4 What was measured

| Measurement | Result | Consequence |
|---|---|---|
| Full-frame inference | 12.3 ms/frame, ~251 streams/machine, **finds zero plates** on the sandbox | Full-frame is a false economy on wide-area cameras |
| Tiled inference (2×3, 2× upscale) | 185.9 ms/frame, ~26 streams/machine, **finds plates** | Tiling is mandatory; capacity is planned around it |
| Synthetic ground-truth clip | **6/6 plates, 0 false positives** | The pipeline is correct where the optics allow |
| Sandbox concurrency | 2/2, 4/4, 6/6 open cleanly; 7/8 at 8, all at 4 % CPU | The ceiling is the shared gateway, not this machine |
| Scout of all 30 cameras | 29 wide-area PTZ yield only signage, correctly rejected | The limit is optics, not software |
| **cam12, Adalaj toll plaza** | Real truck plate detected 25 times, 8 of 10 characters recovered at ~5 px/char | Toll plazas and checkposts are where ANPR goes first |
| Live partial read, 5 Sept 19:44 | 11 OCR reads on one vehicle, voted, indexed, searchable | The honest demo on government video |

Full detail, with reproduction commands, is in `DOCS/MEASUREMENTS.md`.

### A.5 Documentation delivered

`HLD.md` (high-level design, 14 sections), `PRESENTATION.md` (slide content),
`MEASUREMENTS.md`, `DEMO_SCRIPTS.md` (shot lists for both videos),
`SUBMISSION_CHECKLIST.md`, `evidence/` (annotated frames and crops),
`email_to_sentinel_support.txt` (gateway concurrency report, ready to send).

---

## Part B — What is left

Ordered by what unblocks what. Items marked **person** cannot be done by the
assistant; they need a human with the accounts.

### B.1 Before submission — required

| # | Task | Who | Notes |
|---|---|---|---|
| 1 | **Push to GitHub** | person | `git push origin main` from your own terminal, signed in as `DevamShah1211`. **10 commits are waiting.** The credential cache was cleared, so the sign-in popup will appear. |
| 2 | **Rotate the sandbox password** | person | `GAQA-H7HN-P2GE` is public in commit `851b572`. Call +91 95370 89982 or write to sentinel.hackathon@gujarat.gov.in. Do this before the repository is reviewed. |
| 3 | **Record Video 1** (own feed, 2–3 min) | person | Follow `DEMO_SCRIPTS.md`. Seed first with `python tools/seed_demo_route.py --reset`. Six distinct routes; GJ99AB1234 ends with the flagged Rajkot jump. |
| 4 | **Record Video 2** (government feed) | person | Shot 14 is cam12. Run `python tools/index_partial_reads.py --live 100 --camera cam12` while a truck is in the lane, then search the voted plate with fuzzy on. |
| 5 | **Export HLD and presentation to PDF** | person | Any Markdown-to-PDF tool; keep the tables. |
| 6 | **Deploy a reachable instance** | person | `docker compose up`. Set `AUTH_ENABLED=true`, change `SECRET_KEY` and `DEMO_ADMIN_PASSWORD`. |
| 7 | **Fill links into README.md** and submit the portal form | person | Repository, deployed URL, both videos, PDFs. |
| 8 | **Send the gateway email** | person | `DOCS/email_to_sentinel_support.txt`; add your name and team. It is a courteous, measured bug report and reflects well on the team. |

### B.2 Engineering that would strengthen the submission, if time allows

None of these is required. Each is a few hours and is listed with its payoff.

- **Two-row plate handling.** The cam12 partial read is a yellow commercial plate laid out in two rows. The OCR reads it as one line, which is why the voted text is only partly right. Splitting a tall crop into two rows and concatenating would likely lift real-feed reads from "partial" to "valid". This is the single highest-value ANPR change left.
- **Live indexer runs the partial path automatically.** Today `index_partial_reads.py` is a tool run by hand. Moving the same logic into the worker so any consistently detected but unvalidated track is stored partial makes the feature permanent.
- **Server-side map clustering.** Client-side clustering is fine at 30 cameras and becomes mandatory server-side above ~10,000 (HLD §9.3). A single endpoint returning grid-cell counts at low zoom is a small change.
- **Alert delivery beyond the browser.** SMS or email on watchlist hit; the hook exists in `alerts.py`.
- **Camera health history.** Health is sampled on request. A background sampler with a 24-hour rolling table gives the dashboard uptime figures.

### B.3 Known limitations that stay in the document

These are stated in the HLD and should not be hidden in the demo:

- ANPR on the sandbox grid is limited by optics; 29 of 30 cameras never show a readable plate.
- The demo plates in Video 1 are synthetic and use unissuable RTO codes (GJ-96 to 99, MH-99, RJ-99), so they can never belong to a real person.
- VAHAN is mocked. The adapter contract is real; the credentials are not available to a hackathon team.
- The shared sandbox gateway degrades above six concurrent streams. That is their infrastructure, measured and reported.

---

## Part C — How to scale further

The HLD §9 makes the architectural argument. This section is the engineering
sequence: what to change, in what order, and at what camera count each change
becomes necessary. It is written so a team picking the project up can start on
Monday.

### C.1 The number that shapes everything

| Quantity at 80,000 cameras, H.265 mix | Value |
|---|---|
| Aggregate ingest bandwidth | ≈192 Gbps |
| Central write rate | ≈24 GB/s |
| Raw video, 30 days | ≈62 PB |

Flat ingestion into one data centre is not a bigger version of the prototype.
It is a different problem. Every scaling step below exists to keep raw video
**at the district edge** and send only metadata, crops and on-demand streams to
the core. We reproduced the failure at small scale: the shared sandbox gateway
fell over at eight streams while our machine sat at 4 % CPU. The bottleneck is
always the shared path, never the compute.

### C.2 Stage 1 — one district, up to ~500 cameras

What the current code does with configuration changes, not rewrites.

1. **Run the relay and the ANPR worker on a district node**, not the core. Both already take a camera list and speak only HTTP to the core. Point them at the local NVRs.
2. **Tier the cameras.** Tag each camera `anpr_continuous`, `anpr_on_event` or `view_only`. The worker already selects by list; add the tag as the selector. With tiled inference at ~26 streams per 20-core machine, one node runs continuous ANPR on the ~5–10 % of cameras that are toll plazas, checkposts and highway gantries. That is exactly the cam12 finding turned into policy.
3. **Partition the detections table by month.** PostgreSQL native partitioning; the `pg_trgm` GIN index is created per partition. Search code is unchanged.
4. **Store crops in object storage** (MinIO on the node, S3-compatible), not local disk. `crop_uri` is already a URI.
5. **Replace the in-process WebSocket alert fan-out with NATS.** One subject per department. The alert router publishes; the frontend gateway subscribes. This is the first change that needs a new component.

Expected outcome: one node, ~500 registered cameras, ~25 under continuous ANPR, all searchable from the state console, no raw video leaving the district.

### C.3 Stage 2 — one region, ~5,000 to 10,000 cameras

1. **Regional PostgreSQL shard per commissionerate**, each holding its own detections and cameras. The core holds the registry and the watchlist only.
2. **Scatter-gather search.** A federation service fans a plate query out to every shard, merges by `similarity()` and time. Route reconstruction runs on the merged set; the existing route code takes a list of sightings and does not care where they came from.
3. **Watchlist push, not pull.** The core publishes watchlist changes on NATS; every edge node keeps a local copy and matches locally, so an alert fires within the district in milliseconds even if the backhaul is down.
4. **Server-side map clustering.** Return grid-cell counts below a zoom threshold and individual cameras above it. Mandatory here; the browser cannot hold 10,000 markers.
5. **Health sampling as a job**, one per node, writing to a rolling table. The dashboard reads the table, never probes cameras.

### C.4 Stage 3 — statewide, ~80,000 cameras

1. **Thirty-three district nodes** (one per district, sized to their tier-1 count) reporting to a small number of regional shards.
2. **Storage tiering.** Hot NVMe for the last 7 days of crops and metadata on the node, warm object storage for 90 days at the region, cold archive beyond. Video itself stays on departmental NVRs under existing retention rules; the platform fetches clips on demand through the same proxy path the prototype uses today.
3. **Kafka or NATS JetStream between region and core** for detections and alerts, so a core outage loses nothing.
4. **On-demand live view only.** No stream is pulled unless an operator opens it. The relay already does this: one upstream per camera, torn down when the last viewer leaves.
5. **Analytics scheduling by policy.** Tier-2 cameras run ANPR only on motion or on an operator's request; tier-3 cameras never run analytics. Capacity is then proportional to tier-1 plus a burst allowance, not to the estate.

| Tier | Share of estate | Workload |
|---|---|---|
| Tier 1 — ANPR continuous | ~5–10 % | Tiled ANPR, always on: highways, border posts, toll plazas |
| Tier 2 — event-triggered | ~20–30 % | Analytics on motion or on demand: urban junctions |
| Tier 3 — registry and view | ~60–75 % | Recording and live view only |

At 80,000 cameras, tier 1 is 4,000 to 8,000 streams. At ~26 tiled streams per
machine that is roughly 150 to 300 analytics machines statewide, spread across
district nodes. That is a procurement line, not a research problem.

### C.5 Where ANPR itself goes next

The prototype's accuracy comes from voting and grammar, not from the model, and
that is where the remaining gains are:

1. **Two-row plate splitting** (B.2 above). Most commercial vehicles in Gujarat carry two-row plates. This is the difference between "partial" and "valid" on cam12.
2. **Camera-specific tiling.** Tile geometry is fixed at 2×3 today. A per-camera region of interest, drawn once on the map page, cuts inference cost by 3–5× on cameras where the road occupies a strip of the frame.
3. **Bharat series and older formats** are already in the grammar; add state-specific RTO code tables so `state_valid` becomes `rto_valid`.
4. **A better model, if one is wanted later**, plugs into `PlateDetector` behind the same interface. The constraint stays: CPU, on-premise, nothing leaves the deployment.

### C.6 What must not change while scaling

- **No raw video to the core.** Metadata, crops and on-demand streams only.
- **No credentials to the browser.** The relay and proxy pattern is the reason.
- **No third-party ANPR API.** Government CCTV frames stay on government servers.
- **Every search is audited** with purpose, actor and case reference. The table partitions; the rule does not.
- **Partial reads never alert.** A watchlist fires on validated reads only; investigators see the rest.

---

## One-line summary for a reviewer

Both models are built, measured and honest about their limits; the remaining
work before submission is entirely a person's (push, rotate the password, record
two videos, deploy, submit); and the path to 80,000 cameras is an edge-first
sequence in three stages whose first stage needs configuration, not rewrites.
