# Integrating with Sentinel

The platform's whole surface is an HTTP API — the operator console is one client
of it, not a privileged path. A department that wants to push its cameras into
the registry, pull its own detections into an existing system, or run its own
front end can do all three against the same endpoints the console uses.

**The contract is `openapi.json` / `openapi.yaml` in this directory.** It is
generated from the running application's route definitions by
`backend/tools/export_openapi.py`, so it cannot drift from the implementation: if
an endpoint changes, re-running that script is the entire update. Import either
file into Postman, Insomnia, Swagger UI, or a client generator.

- **42 paths · 46 operations · 18 schemas**
- Interactive docs on a running instance: `/api/docs` (Swagger) and `/api/redoc`

---

## 1. Authenticating

Every route except `/api/health` requires a bearer token.

```bash
TOKEN=$(curl -s -X POST http://<host>/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@dept.gujarat.gov.in","password":"..."}' \
  | jq -r .access_token)

curl -s http://<host>/api/v1/cameras -H "Authorization: Bearer $TOKEN"
```

Tokens are JWTs valid for 8 hours. Role and identity are read from the database
on every request rather than from the token's claims, so revoking or
deactivating an account takes effect immediately rather than at expiry.

### Roles

| Role | Can |
|---|---|
| `viewer` | Read cameras, the map, live streams, alerts |
| `dept_operator` | The above, plus plate search, route reconstruction, watchlist, report export |
| `state_admin` | Everything, including the registry, catalogue sync and the audit trail |

Anything that reads or correlates vehicle movement requires at least
`dept_operator`, and is written to the audit trail with the caller's identity,
stated purpose and case reference. That is a deliberate constraint rather than an
oversight: see HLD §11.

---

## 2. The four integrations a department actually needs

### 2.1 Onboard cameras

One at a time, or a CSV for a whole department.

```bash
# Template describing every column, with an example row
curl -s http://<host>/api/v1/cameras/bulk-import/template -H "Authorization: Bearer $TOKEN"

# Validate without writing — always do this first
curl -s -X POST 'http://<host>/api/v1/cameras/bulk-import?dry_run=true' \
  -H "Authorization: Bearer $TOKEN" -F file=@cameras.csv
```

The dry run reports what would be created and what would be rejected, per row.
`POST /api/v1/cameras` takes a single record for smaller integrations.

### 2.2 Pull detections into an existing system

```bash
# Everything a camera saw in a window
curl -s 'http://<host>/api/v1/detections?camera_id=<uuid>&since=2026-09-09T00:00:00Z&limit=500' \
  -H "Authorization: Bearer $TOKEN"

# One vehicle's movement, in time order, with per-leg speeds
curl -s 'http://<host>/api/v1/detections/route/GJ01KA7392?purpose=investigation&case_ref=FIR/2026/0912' \
  -H "Authorization: Bearer $TOKEN"
```

The route response carries each sighting's camera, coordinates, timestamp,
confidence and evidence crop, plus the speed implied by the previous leg and an
`impossible` flag where that speed is not physically achievable. A department
correlating with its own data should read that flag rather than recomputing it —
the threshold and its reasoning live in one place.

### 2.3 Push detections from your own analytics

If a department already runs ANPR and wants Sentinel as the correlation layer,
post detections directly:

```bash
curl -s -X POST http://<host>/api/v1/detections \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "camera_native_id": "cam01",
        "plate_text": "GJ01KA7392",
        "confidence": 0.97,
        "detected_at": "2026-09-09T10:56:21Z",
        "crop_uri": "/evidence/cam01_GJ01KA7392.jpg"
      }'
```

Watchlist matching and alerting run on ingest, so a pushed detection raises an
alert exactly as an internally generated one does.

**A read below the platform's resolution threshold should be marked partial**
(`raw_reads` metadata, see `backend/anpr_worker.py`). Partial reads are indexed
and searchable but never alertable, because a well-formed, confident, wrong plate
is the failure that puts an officer in front of the wrong vehicle. MEASUREMENTS
§2g documents the case that produced this rule.

### 2.4 Subscribe to alerts

```javascript
// The token goes in the query string: the browser WebSocket API cannot set an
// Authorization header. An invalid or missing token closes the socket with
// code 1008.
const ws = new WebSocket('wss://<host>/ws/alerts?token=' + token)
ws.onmessage = e => {
  const alert = JSON.parse(e.data)
  // alert_id, plate_text, camera_name, severity, reason, case_ref, detected_at
}
```

Alerts are pushed as they are raised. For systems that cannot hold a socket open,
`GET /api/v1/alerts?status=new` polls the same data.

### 2.5 Push scene counts (vehicle / person / object detection)

The analytics tier that works where ANPR cannot. MEASUREMENTS §2g records the
finding that no camera on the sandbox grid produces a readable plate — 4 to 14
pixels per character against the 20-30 OCR needs — while the same frames contain
vehicles and pedestrians a detector resolves comfortably. A department running
its own detector can push counts here.

Counts are aggregated into **one bucket per camera per minute** before they are
posted. The peak simultaneous count per class is kept, not the sum across
frames: summing counts a parked car once per sampled frame, producing a number
that grows with sampling rate rather than with traffic.

```bash
curl -s -X POST http://<host>/api/v1/analytics/scene \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "camera_native_id": "cam10",
        "bucket_start": "2026-09-09T10:56:00Z",
        "bucket_seconds": 60,
        "frames_sampled": 60,
        "counts_by_label": {"car": 3, "motorcycle": 4, "person": 5},
        "counts_by_category": {"vehicle": 7, "person": 5},
        "max_confidence": 0.87
      }'
```

`frames_sampled` is required and load-bearing: without it a count of zero cannot
be distinguished from a camera nobody analysed, which are different operational
states and are shown differently on the Grid Health page.

Use the batch endpoint for anything more than a few buckets — one request per
minute per camera is 1,440 requests/camera/day and is rate-limited:

```bash
curl -s -X POST http://<host>/api/v1/analytics/scene/batch \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"observations": [ /* up to a few hundred bucket objects */ ]}'
```

Both writes are idempotent on `(camera, bucket_start)`: a worker that restarts
mid-minute re-sends the bucket it was building, and re-analysing recorded
footage corrects the row rather than duplicating it.

Reading back:

```bash
# Grid totals and class mix over a window
curl -s "http://<host>/api/v1/analytics/scene/summary?hours=24" -H "$AUTH"

# Busiest cameras first
curl -s "http://<host>/api/v1/analytics/scene/by-camera?hours=24" -H "$AUTH"

# Activity by hour of day, returned in IST
curl -s "http://<host>/api/v1/analytics/scene/hourly?hours=24" -H "$AUTH"

# Real worker rows only, dropping anything the seeding tool wrote
curl -s "http://<host>/api/v1/analytics/scene/summary?hours=24&include_seeded=false" -H "$AUTH"
```

Every bucket carries a `source`: `"worker"` (the default — a detector over a
real feed) or `"seed"` (`tools/seed_scene_analytics.py`, for demonstrations).
The summary reports `buckets_by_source` so a client can say what its numbers
are made of, and all three reads accept `include_seeded=false`. Provenance is a
column rather than a convention because the two are otherwise byte-identical,
and a demonstration row that cannot be told from a measurement is a
measurement that cannot be trusted.

**These counts are a throughput estimate, not a vehicle census.** Peak-per-minute
summed over a window counts a vehicle standing at a junction for three minutes
three times. Every response carries that caveat in a `note` field and the UI
prints it; anything reported onward should keep it.

---

## 3. Conventions

| | |
|---|---|
| **Time** | All timestamps are UTC, ISO 8601 with a `Z` suffix. The UI converts to IST for display; the API never does |
| **Identifiers** | `id` is a platform UUID; `native_id` is the department's own camera identifier, and is what you should send |
| **Paging** | `limit` and `offset`; every list endpoint caps `limit`, and the cap is in the spec |
| **Errors** | Standard HTTP status codes with `{"detail": "..."}`. Error bodies never contain stack traces or internal state |
| **Rate limits** | 300 requests/minute per client, 10/minute on `/auth/`. Exceeding either returns 429 with `Retry-After` |

---

## 4. What is deliberately not exposed

Worth stating, because their absence is a design decision rather than an
omission:

- **Stream credentials.** `GET /api/v1/cameras` never returns `rtsp_url`. The
  credential-bearing form is state-admin only, and even there the password is
  stripped and reconstructed by the worker from its own configuration. A
  credential that does not travel over HTTP cannot leak from an HTTP log.
- **Bulk plate export without a purpose.** Report generation requires a stated
  purpose and writes an audit record. There is no endpoint that dumps the
  detection index, because a surveillance database with a convenient export is a
  surveillance database that will be exported.
- **Vehicle owner details without a case reference.** `GET /api/v1/analytics/vehicle/{plate}`
  requires both, and both are recorded.

---

## 5. Verifying the contract

```bash
cd backend
python tools/export_openapi.py          # regenerate from the routes
python -m pytest tests/test_security.py # 33 tests over the access rules above
```

The security tests assert the guarantees in §1 and §4 — that privileged routes
resolve an authenticated principal, that stream credentials are stripped, and
that audit attribution comes from the token rather than from a request
parameter. If an integration depends on one of those properties, the test naming
it is the thing to read.
