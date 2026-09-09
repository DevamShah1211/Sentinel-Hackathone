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
