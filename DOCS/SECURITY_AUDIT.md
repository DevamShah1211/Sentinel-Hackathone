# Security audit - 9 September 2026

An audit of the backend was run against the code as submitted, and the findings
were verified by exploiting them against a running instance rather than by
reading alone. Every issue below was reproduced, then fixed, then covered by a
regression test in `backend/tests/test_security.py` (33 tests).

This document exists because a fixed vulnerability that nobody records is
indistinguishable from one that was never found. The reasoning matters more than
the patch: several of these were not coding mistakes but decisions that were
defensible in a prototype and stopped being defensible the moment the platform
held government camera credentials and police case data.

---

## 1. What was wrong, and why it mattered

### C1 - Sandbox credentials disclosed to anyone, unauthenticated

`GET /api/v1/cameras/internal/streams` returned `Camera.rtsp_url` verbatim, and
that column carries the sandbox password in its userinfo component. An
unauthenticated request returned live credentials for the Gujarat Police camera
grid, in JSON, for up to a thousand cameras. The route was published in the
OpenAPI schema, so it did not even have to be guessed.

Verified by requesting it and receiving the password in full.

The route's own docstring said it "sits behind service-to-service authentication"
in a real deployment. That was true, and it was not enforced. **A comment is not
an access control** - this is the single most useful lesson in the audit, and it
is why every fix below is accompanied by a test rather than a note.

**Fixed** by requiring state-admin authority, withholding the route from the
schema, and stripping the credential from the response. The worker reconstructs
it from its own configuration, which it already held - so the password never
needed to travel over HTTP at all, and sending it was gratuitous as well as
dangerous. A leak of this response now discloses hostnames.

### C2 - Authentication defaulted to off, and off meant "everyone is admin"

`auth_enabled` defaulted to `False`, and the fallback principal returned in that
mode carries `state_admin`. `AUTH_ENABLED` was not set in the environment, so the
default was live: **every anonymous request was a state administrator**, and
every RBAC guard in the codebase was a no-op - including the audit trail, plate
search, and route reconstruction of citizen movement.

The failure was silent. The server logged a warning at startup and served
normally.

**Fixed** by defaulting to `True`. Local demonstration now opts out explicitly
with `AUTH_ENABLED=false`, which is visible and deliberate and cannot happen by
omission. A surveillance platform must not have a default whose failure mode is
universal administrative access.

### C3 - Watchlist and alerts had no access control at all

Neither module imported anything from `app.security`. In consequence:

- Anyone could read the full list of wanted and stolen vehicles, with case
  references and reasons - active police case data.
- Anyone could **deactivate a watchlist entry**, silently stopping a stolen
  vehicle from ever raising an alert again.
- Anyone could acknowledge or resolve an alert.

The acknowledgement path was the sharpest: the acknowledging officer came from
`operator: str = Query("operator")`, so the caller chose the name recorded
against the action. **An audit record that its own subject can author is not an
audit record.**

**Fixed** with role guards on every route - state admin for deactivation, since
that silences an alert - and attribution taken from the authenticated principal.

### H1 - Anyone could forge evidence

`POST /api/v1/detections` was unguarded, and the request model accepts both
`detected_at` and `crop_uri`. Anyone could place any registration at any camera
at any past timestamp, which propagates directly into route reconstruction and
the exported evidence report, and can fire a real alert against a real
watchlisted plate.

Verified by writing a fabricated detection into the index, then removing it.

In a submission reviewed by a forensic sciences university, the detection index
is the evidentiary record. It was writable by anyone.

**Fixed** with an operator guard; the worker authenticates with a token.

### H2 / H3 - A guessable signing key and published account passwords

The JWT secret was a low-entropy human-chosen string, and `role` is read from the
token's claims - so forging a token with `"role": "state_admin"` was total
compromise, with an eight-hour window. Three demonstration accounts had passwords
hardcoded in source, one of them state admin.

The two combined into something worse than either: enabling authentication - the
fix for C2 - would have handed an attacker three known-password accounts. **The
step that makes the system safer must not be the step that opens the door.**

**Fixed.** The key is rotated to 64 random bytes and the application now refuses
to start with a default or short key while authentication is on. Demonstration
accounts are seeded only on explicit request, with generated passwords logged
once at creation.

### H4 - Mass assignment, giving stream hijack and SSRF

`PATCH /cameras/{id}` took an untyped `dict` and assigned any attribute the model
happened to have. Every column was writable, including `rtsp_url`.

Two attacks followed. The registry could be falsified by moving a camera's
coordinates, corrupting the map and every route reconstruction. More seriously,
an attacker could repoint a camera at a host of their choosing; the relay then
fetched it and served attacker-controlled video to operators as a live
government feed. The same primitive makes the server fetch arbitrary internal
addresses.

**Fixed** with an explicit `CameraUpdate` model that forbids unknown fields,
omits the stream URLs entirely, and range-checks coordinates.

### H5 / M3 - Unbounded work from unauthenticated callers

`POST /ingest/sync` was open and spawned a background task per call, each logging
into the sandbox and issuing rate-limited geocoder lookups per camera. Repeated
calls stacked without limit. Both CSV import paths read the entire upload into
memory with no size check.

**Fixed** with a state-admin guard and a single-flight lock on sync, and byte and
row caps on import.

### M4 - The rate limiter could be bypassed by asking it to be

The limiter keyed on `X-Forwarded-For` with no trusted-proxy check. Since that is
a request header, a client could present a different address on every request and
receive a fresh bucket each time - making the ten-per-minute limit on `/auth/`
unlimited in practice, against endpoints whose passwords were the published
constants from H3. The bucket dictionary also grew without bound.

**Fixed.** Forwarded headers are honoured only from configured proxies, the
default trusts nothing, and stale buckets are evicted.

### M5 - Deleted accounts kept working

A token whose subject no longer existed fell through and built the principal from
the token's own claims, so a deleted account retained its original privilege
until expiry.

**Fixed.** A missing user is rejected, and identity and role now come from the
database row rather than the claim. A claim says what the holder was granted when
the token was minted; the row says what they are entitled to now, and
authorisation should turn on the latter.

---

## 2. What was already right

Worth recording, because these were deliberate and correct, and because an audit
that lists only faults gives a false picture of the codebase.

- **No SQL injection anywhere.** Every `text()` construct is parameterised,
  including the trigram fuzzy plate search, which was the most likely place to
  find one. The `ilike(f"%{p}%")` pattern builds a *value*, not SQL.
- **CORS is an explicit origin list**, never a wildcard, with methods and headers
  enumerated.
- **Path traversal is blocked** in the HLS proxy, checking both separators and
  dot-dot before use.
- **The proxy cannot be steered.** Upstream URLs are built from configuration,
  so the SSRF that existed came in through the unguarded PATCH, not through the
  proxy itself.
- **Login does not leak account existence** - one message for unknown email and
  wrong password alike.
- **Security headers are thorough**: `frame-ancestors 'none'`, a strict CSP,
  nosniff, HSTS, Referrer-Policy, Permissions-Policy.
- **No stack traces reach clients.**
- **The audit trail is real** - actor, action, object, stated purpose, case
  reference and address, wired into plate search, route reconstruction and
  export, with DPDP purpose-limitation reasoning behind it.
- **`serialise_camera` deliberately withholds stream URLs** from browser
  responses. The control was correct; C1 and H4 went around it.
- **Partial ANPR reads cannot fire watchlist alerts**, matching the measured
  finding that the government grid cannot support reliable plate reading.

---

## 3. The pattern worth taking away

Three of the four most serious findings were not bugs. They were prototype
conveniences that were reasonable when written and became dangerous when the
system's contents changed:

| Convenience | Reasonable when | Dangerous once |
|---|---|---|
| Auth off by default | Nothing to protect | It holds police case data |
| Credentials in the stream URL | Only the worker read them | A route returned them |
| `body: dict` on PATCH | Editing a demo registry | The registry drives a relay |

None would have been caught by a linter or a type checker, and all three were
introduced by someone who understood the risk - the docstrings say so. What
closed them was checking the running system rather than reading the source.

**Everything here is enforced by tests**, so the guards cannot quietly regress:
`python -m pytest tests/test_security.py` (33 tests), within a suite of 140.

---

## 4. Still outstanding

- **`/live/{native_id}` and `/proxy-hls/` remain unauthenticated.** Guarding them
  needs a signed short-lived stream token, because the browser fetches these from
  `<img>` and `<video>` elements that cannot carry an `Authorization` header.
  Documented rather than half-fixed; the deployment note is that this instance
  should not be exposed beyond the operator network until it is done.
- **The sandbox password remains in six commits of git history.** The repository
  is now private, which closes the practical exposure, and a tested history
  rewrite is prepared. It should be run once the organisers confirm the
  credential has been rotated.
