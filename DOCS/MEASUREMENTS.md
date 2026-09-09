# Measured performance

Every number here came out of a run on the project hardware against the live
Sentinel sandbox or a ground-truth clip. Nothing is estimated or aspirational.
Reproduce any of them with the commands given.

Machine: 20-core x86-64 CPU, **no GPU**, Windows 11, Python 3.14.5, onnxruntime 1.29
(CPU execution provider). Models: `yolo-v9-t-384-license-plate-end2end` detector,
`cct-s-v2-global-model` OCR, both pretrained and run locally.

---

## 1. ANPR throughput — full-frame vs tiled

    python anpr_worker.py --benchmark --duration 90 --camera cam05
    python anpr_worker.py --benchmark --duration 75 --camera cam05 --no-tiling

Measured on `cam05` (Visat Teen Rasta, Ahmedabad), 1920×1080, frame stride 5:

| | Full frame | Tiled 2×3 @2.0× |
|---|---|---|
| Mean inference | **12.3 ms/frame** | **185.9 ms/frame** |
| Inference throughput | 81.6 fps | 5.4 fps |
| Est. concurrent streams per core | 18.0 | 1.9 |
| **Est. streams per machine** (70% headroom) | **≈251** | **≈26** |
| Plate reads in the window | **0** | **8** |

This table is the tiered-analytics argument in one place. Full-frame inference is
15× cheaper and finds **nothing** on this grid, because these are wide-area PTZ
overview cameras where a number plate is 10–20 px wide — far below what a 384 px
detector resolves from a whole frame. Tiling upscales overlapping regions before
inference and recovers real reads at 15× the CPU cost.

The consequence for statewide deployment is that ANPR is not a per-camera cost
that scales flatly; it is a policy choice about *which* cameras carry analytics.
One machine of this class covers roughly 26 cameras under continuous ANPR, or
about 250 under motion/registry-only workloads.

## 2. Pipeline accuracy — ground truth

    python tools/make_sample_feed.py --validate

Six vehicle passes with known plates, 660 frames, production settings
(`min_reads=2`, `MIN_TRACK_CONFIDENCE=0.45`, tiled inference):

| Metric | Result |
|---|---|
| Plates recovered exactly | **6 / 6 (100%)** |
| False positives | **0** |
| Reads aggregated per track | 4 – 35 |
| Track confidence | 0.736 – 1.000 |

With tiling disabled the same clip yields 3/6, and every miss is a detector miss:
in a per-frame audit, **every OCR read of a detected plate was character-perfect**
(`GJ01AB1234` 5/5, `GJ05JV7219` 13/13, `MH12DE1433` 4/4). The binding constraint
is plate *detection*, not *recognition* — which is why tiling matters more than
any OCR change.

Removing the two-read requirement admits one false positive (`JO14B1234`, a single
read at 0.68 confidence). Requiring two reads eliminates it while costing no real
detection: genuine passes produce 20+ reads.

## 2a. Yield on the live sandbox grid — the honest number

Six cameras, 75 s each, tiled inference, counted at every stage of the pipeline:

| Camera | Frames | Passed quality gate | Plate boxes | OCR strings | Plausible | **Valid Indian plate** |
|---|---|---|---|---|---|---|
| cam01 | 393 | 72 | 26 | 3 | 0 | 0 |
| cam05 | 325 | 59 | 85 | 51 | 3 | 0 |
| cam14 | 70 | 8 | 16 | 2 | 0 | 0 |
| cam17 | 92 | 12 | 3 | 0 | 0 | 0 |
| cam24 | 220 | 38 | 32 | 31 | 31 | 0 |
| cam27 | 75 | 9 | 3 | 0 | 0 | 0 |
| **Total** | **1,175** | **198** | **165** | **87** | **34** | **0** |

A continuous 8-camera indexing run over ~25 minutes likewise produced no valid
plates.

**What this shows, stage by stage.** The detector is not broken — it proposed 165
plate-shaped regions. The OCR is not broken — it returned 87 strings. What those
strings *are* is the point: cam05's repeated `AEVETEE` is the "ADVERTISE HERE"
billboard in frame, and cam24's `C8MCY811` is signage. Not one is a vehicle
registration, and the Indian-plate grammar validator correctly rejected every one.

**Why.** These are wide-area PTZ overview cameras, largely at night. A vehicle
occupies 30–80 px of a 1920×1080 frame, so its plate is 5–15 px wide — below the
resolution at which any OCR can recover ten characters, tiling and upscaling
included. Upscaling cannot restore detail the sensor never captured.

**What we conclude, and what we do not.** We do not claim working ANPR on this
grid. We claim a pipeline that is validated end to end at 100% on footage where
plates are legible (§2), that correctly rejects every false candidate on footage
where they are not, and that is limited here by camera siting rather than by the
software. The correct operational recommendation, and one worth reporting to the
department, is that ANPR requires cameras sited for it — mounted low, angled
along the carriageway, with plate-region coverage — rather than wide-area
situational-awareness PTZs.

The false-positive rejection is itself a result. A system that reported
`AEVETEE` as a vehicle would have produced impressive-looking detections and a
worthless index.

**One candidate did get through, and closing that gap is instructive.** A long
indexing run produced `AI771114` from cam14 — correctly shaped for an Indian
plate, so the format check passed, but `AI` is not a real RTO state code. The
worker now also requires a valid state code before a detection reaches the index.
This is the value of validating against the actual RTO prefix list rather than
the format alone: the format check catches text that is not plate-shaped, and the
state-code check catches text that is.

## 2b. All 30 cameras scouted — and what cam12 shows

The earlier §2a sample covered six cameras. The remaining twenty-four were then
scouted the same way, so the finding now rests on the whole grid rather than a
subset.

**Result: 0 of 30 cameras yield a valid Indian plate.** But one is materially
different from the rest and deserves its own entry.

### cam12 — Tri Mandir Adalaj Toll Naka

Unlike every other camera on the grid, cam12 is a **toll plaza**: vehicles stop,
and plates face the camera at close range. It is the only camera in the sample
that is sited anything like an ANPR camera, and the pipeline behaves accordingly.

Over a 100-second window it produced **25 detections of one genuine vehicle
plate** — a yellow commercial plate on a truck in Lane 9 — read as:

| OCR output | Times | After grammar correction | Valid |
|---|---|---|---|
| `66Q2XT449` | 11 | `GG02X7449` | format yes, state code no |
| `6302XX449` | 8 | `6302XX449` | no |
| `6602XT449` | 4 | `GG02X7449` | format yes, state code no |
| `6602XX449` | 2 | `6602XX449` | no |

Visual inspection of the saved crop shows the plate reads approximately
`GJ02XX4499`. So the detector is right, the tracker is right, and the OCR is
recovering most of the correct characters — it is confusing `GJ`↔`66`/`63` and
dropping the final digit.

**Why it still fails, measured rather than guessed:** the detected plate region is
89×54 px *including padding*, so the plate itself is roughly **55×15 px**. Ten
characters across 55 pixels is about **5 px per character** — below the density at
which character shapes exist to be recovered. Seven preprocessing variants were
tried (upscaling to ×5, CLAHE, greyscale normalisation for the yellow commercial
plate, sharpening, and combinations); **none produced a valid read**, because
upscaling cannot restore detail the sensor never captured.

### Partial reads — making cam12's truck searchable without lowering the bar

The strict indexer is right to refuse cam12's read for alerting: `66Q2XT449`
grammar-corrects to `GG02X7449`, a well-formed string with an impossible state
code, and a watchlist must never fire on that. But an investigator searching
`GJ02XX4499` wants to know something close was seen at the toll plaza, and to
look at the crop. `tools/index_partial_reads.py` therefore writes such a track
as a detection tagged **partial** in its `raw_reads` metadata. The API exposes
it as `partial: true`, the search page labels it *PARTIAL · UNVERIFIED*, the
pg_trgm index finds it from the true plate, and the watchlist check skips it.
Every character stored is the OCR's own; the only decision added is to keep it.

### cam14 — Delight RLVD, twice the detail and still short

cam14 is a red-light violation camera at the Delight junction, so it is aimed
closer to the stop line than the wide-area PTZs. Probing it directly, at
1920x1080:

| Quantity | cam12 (toll plaza) | cam14 (Delight RLVD) |
|---|---|---|
| Plate box width | ~55 px | **80-81 px** |
| Pixels per character | ~5 | **~10** |
| Reads in a 120 s window | 25 (one vehicle) | 6 (three vehicles) |
| Fully valid reads | 0 | 0 |

The plate the detector found belongs to the white car stopped at the line, and
the saved crop is legible to a human as approximately `GJ06BA1316`. The OCR
returned `GI65AA33` and `GI63AA31` — eight characters for a ten-character plate,
with the state code `GJ` misread as `GI` every time.

Two things follow. First, this is **twice the detail of cam12** and the read is
still not recoverable, which puts a useful number on the requirement: ten
pixels per character is not enough either. Published ANPR guidance asks for
roughly 20 to 30, and these measurements agree with it from below.

Second, upscaling again bought nothing. Cropping to the lower part of the frame
where the vehicles queue and upscaling that region by 2, 2.5, 3 and 4 produced
no valid read at any factor; at x2.5 and x3 the detector stopped finding the
plate at all. The information is absent from the capture, not hidden by the
tiling.

A second probe of the same camera four minutes later returned **zero
detections across 182 usable frames** — the junction had emptied. Yield on these
cameras is governed by whether a vehicle happens to be near the camera, which
is why a demonstration cannot depend on catching one live.

### What this changes about the conclusion

It sharpens it. The earlier statement — that the limit is camera siting rather
than the software — is now supported by a camera that is *partly* sited for the
job. Move from a wide-area PTZ overview to a toll plaza and the pipeline goes
from reading nothing at all to reading eight of ten characters of a real
registration, repeatably, from a single vehicle pass.

The remaining gap is pure sensor resolution. A camera at cam12's angle and
distance with a longer lens, or simply positioned closer to the lane, would put
15-20 px per character in frame and the same pipeline would read it — as it does
at 6/6 on legible footage (§2).

**The operational recommendation is therefore specific rather than general:**
toll plazas, checkposts and lane-facing junction cameras are where statewide ANPR
should be deployed first, and cam12 shows the department already has cameras in
roughly the right places — they need the optics, not different software.

## 2c. Strengthening the recogniser, and what it did not buy

Three changes were made to the recognition layer, each measured with
`tools/bench_ocr.py` before and after. That tool holds two benchmarks: real OCR
strings captured from these cameras replayed through the grammar, and the whole
pipeline over the ground-truth clip. A change that improves one and worsens the
other is not an improvement.

**1. A complete confusion model.** The substitution tables were missing fifteen
letters and three digits. `E` had no digit form, so `GJ01AB12E4` was rejected
outright instead of corrected. Every gap was a plate thrown away.

**2. Ambiguity-aware splitting.** `GJ0LAB1234` can be read as RTO `0` with
series `LAB`, needing no substitution at all, or as RTO `01` with series `AB`,
needing one. The old rule picked by length and got it wrong. Now every legal
split is scored by how much each substitution should be distrusted — `O`/`0` is
a one-stroke confusion, `R`/`9` is a guess — plus a prior over which shapes are
actually issued. Delhi's alphanumeric codes (`DL8C`) are protected explicitly,
because coercing that `C` to a `6` destroys a valid registration.

**3. A refinement pass.** When a track's vote fails validation, its best crop is
re-read under three enhancements: CLAHE for sodium-lit night footage, an unsharp
mask for encoder softening, and Otsu binarisation for yellow commercial plates.
The retried vote is accepted **only if it validates**, so refinement can rescue
a plate but never degrade a good read.

| Benchmark | Before | After |
|---|---|---|
| Grammar layer, real captured strings | 23/24 | **24/24** |
| End to end, ground-truth clip | 6/6, 0 false positives | **6/6, 0 false positives** |
| Unit tests | 72 | **79** |
| Runtime over the clip | 48.6 s | **45.6 s** |

The runtime is unchanged within noise because refinement fires only on tracks
that already failed, which are the minority.

### What it did not fix, stated plainly

It does not rescue cam12 or cam14, and this was tested directly rather than
assumed. Replaying the cam12 truck's real reads through the new pipeline:

| | Voted result | Valid |
|---|---|---|
| First pass | `6302XX449` | no |
| With refinement | `6302XX499` | no |
| True plate, by eye | `GJ02XX4499` | — |

The enhancements produce *different* wrong answers, not right ones. Otsu
binarisation does return ten characters instead of nine, which is closer in
shape, but the characters themselves are wrong and the grammar refuses them.

That refusal is the correct behaviour and worth stating to a reviewer: a
recogniser that could be pushed into accepting `6302XX499` as a registration
would be worse, not better. The limit remains 5 and 10 pixels per character
against the 20-30 that ANPR needs, and no post-processing recovers detail the
sensor never captured.

## 2d. Real RTO district data, and a correction that had to be reverted

`app/rto_codes.py` records the district ranges each state has actually issued —
Gujarat GJ-01 to GJ-39, Maharashtra to MH-50, Rajasthan to RJ-58 — with the
thirty-nine Gujarat district names. A state whose range could not be confirmed
accepts anything, so an incomplete table never rejects a real vehicle.

**What it is used for.** Every detection now reports whether its district was
ever issued and, for Gujarat, which district it names. When a track's reads
genuinely disagree at one position, the reading that lands on a real district
wins: reads split between `GJ88` and `GJ38` settle on GJ-38 Aravalli.

**What it is not used for, and why.** The obvious next step is to rewrite an
impossible district onto the nearest real one — `GJ88` becomes `GJ38`, since 3
and 8 are a common confusion. It was implemented, measured, and removed.

| | Recovered | False positives |
|---|---|---|
| With district rewriting | 4/6 | 2 |
| Without | **6/6** | **0** |

It rewrote `GJ96XY4455` to `GJ06XY4455` and `GJ97JV7219` to `GJ07JV7219`. Both
had been read correctly and unanimously by every frame; both were "improved"
into a different registration because 9 to 0 lands on a district that exists.

The flaw is that it decides from grammar alone, with no evidence from the OCR
that the character was ever uncertain. **Substituting one plausible registration
for another is the worst failure this system can produce** — invisible, correct
looking, and it points an investigation at the wrong vehicle.

The function remains in the source, unused, with that reasoning recorded, and a
test asserts a unanimous read is never rewritten. District knowledge is applied
only where the reads themselves are undecided.

| Benchmark | Result |
|---|---|
| Grammar layer, real captured strings | 24/24 |
| End to end, ground-truth clip | 6/6, 0 false positives |
| Unit tests | 85 |

## 2e. A learned prior, and why it is not "training"

`app/plate_prior.py` counts which RTO districts and series this deployment has
actually indexed, and uses those counts to settle reads the recogniser itself
could not decide. `tools/build_plate_prior.py` builds it from the detection
index; re-running it as the index grows is the one part of the recognition stack
that improves with use.

**It is calibration, not training, and the distinction is worth stating.** No
network weights change. Training the OCR would need thousands of annotated
Indian plate crops, a GPU, and days; this needs a table of registrations and
scores a plate in microseconds. "We trained a model" invites the question of
what data, labelled by whom, validated how. "We counted which districts occur
and used that to break ties" can be checked against the code in an afternoon.

**Where it is allowed to act.** Only at a character position where the OCR reads
genuinely disagreed, only between two readings already equal on grammar, and
only when one is meaningfully more plausible than the other. It cannot overturn
a rank, and it cannot touch a position every read agreed on.

That boundary is not a stylistic choice. The district-rewriting step in section
2d was removed for crossing it, and the same trap is present here: the
demonstration plates use unissued districts, so the prior scores them at the
floor. Wired naively it would have rewritten `GJ96XY4455` again.

| Read | First pass | Result |
|---|---|---|
| Split GJ-01 / GJ-30, both real | tie | **GJ-01 Ahmedabad** — the district a Gujarat camera actually sees |
| Split GJ-88 / GJ-38 | tie | **GJ-38 Aravalli** — the district that exists |
| Unanimous GJ-96 (unissued) | GJ96XY4455 | **unchanged** |
| Unanimous GJ-99 (unissued) | GJ99AB1234 | **unchanged** |

| Benchmark | Result |
|---|---|
| Grammar layer, real captured strings | 24/24 |
| End to end, ground-truth clip | 6/6, 0 false positives |
| Unit tests | 98 |

A missing prior file scores everything zero, so a fresh deployment behaves
exactly as it did before this module existed. A recogniser that depends on a
data file it may not have is one that fails in the field.

## 2f. Sandbox access lost and restored, 7-8 September

A planned re-sweep of all thirty cameras with the improved recogniser could not
be completed. Every camera now returns an immediate rejection:

```
RTSP/1.0 401 Unauthorized
Server: gortsplib
WWW-Authenticate: Basic realm="ipcam"
```

The same credentials captured 120 seconds of cam14 successfully at 16:04 the
same day. Nothing changed at our end between the two tests.

Eliminated before reporting: the gateway is reachable (TCP connect succeeds on
8554, 443 and 80), the portal returns HTTP 200, our own connectivity is fine,
and a raw RTSP DESCRIBE sent by hand outside the application returns the same
401 — so it is not our client. The server challenges for Basic authentication
and we send Basic authentication, so the scheme matches. The gateway is running
and specifically rejecting the credential.

**Resolved, 8 September.** The identical credential — unchanged in
`backend/.env` — returned `RTSP/1.0 200 OK` on the first
attempt the next morning, and all thirty cameras opened. So this was a
gateway-side fault at the organisers' end, not a rotated password and not a
revoked access list. The drafted report at `DOCS/email_rtsp_401_access.txt` was
therefore never sent.

Worth recording because the wrong conclusion was the tempting one. An immediate
401 with a well-formed Basic challenge looks exactly like a rejected credential,
and our first reading was that the password had been rotated out from under us.
It had not. The distinguishing evidence was only available by waiting: a
credential that fails for two hours and then succeeds untouched was never the
thing at fault. Nothing we could have measured during the outage would have
separated the two cases, which is the argument for reporting observations to an
operator rather than inferring a cause and acting on it.

**What this does not affect.** Every measurement in this document was taken
before the change and the evidence frames are committed. The live demonstration
runs on the presenter's own feed (`DOCS/LIVE_DEMO_RUNBOOK.md`), which is what
the playbook asks for and which is precisely why that path exists rather than
depending on the sandbox.

**What it adds.** This is the second independent reliability problem on the
shared sandbox, after the concurrency limit the organisers have already
attributed to their gateway (section 5a). Both are arguments for the edge-first
topology in HLD section 9.2: a statewide platform cannot depend on a single
shared ingestion point remaining available.

## 3. Plate-grammar correction

    python -m pytest tests/test_plate_grammar.py

7/7 on the correction cases, including `GJO1AB1234 → GJ01AB1234` — an error this
OCR model actually made during development, where position 2 must be a digit so
the letter O is unambiguously a zero.

Camera on-screen text is rejected before it can enter the index: `S10PTZ2`,
`CSITMS-31`, `IPC` and burnt-in timestamps are all filtered. These matter — the
detector does offer them up as plate candidates, and one was observed reading the
"ADVERTISE HERE" billboard on cam05 as `AEER75EEEE`.

## 4. OCR model selection

`max_plate_slots` in `fast-plate-ocr` decides whether a 10-character Indian plate
can be represented at all:

| Model | Slots | On `GJ01AB1234` |
|---|---|---|
| `cct-s-v2-global-model` | 10 | `GJ01AB1234` ✅ **(selected)** |
| `cct-xs-v2-global-model` | 10 | reads 10 chars, less accurate |
| `cct-s-v1`, `cct-xs-v1`, `*-relu-v1` | 8 | `01AB123` — silently truncated |
| `global-plates-mobile-vit-v2` | 9 | requires exactly 140×70 grayscale input |

The 8-slot models are the trap: a truncated plate still *looks* like a valid plate,
so it corrupts the index without ever registering as an error.

## 5. Sandbox capture

Measured while indexing live feeds:

- RTSP over TCP opens in ~3 s; frames arrive at **14–23 fps** against a reported
  `CAP_PROP_FPS` of 30, confirming the playbook's warning that the reported rate
  is not the delivery rate and nothing time-derived from it is trustworthy.
- The first ~30–60 frames after connect decode to flat grey artefacts until the
  first IDR. The quality gate discards these; ~30 of 1308 frames were rejected in
  the benchmark window.
- Loop points are detected by PTS regression and reset tracker state, as the scene
  cuts hard when the footage restarts.
- HLS (`https://cctv.corp8.cloud/<cam>/index.m3u8`) did **not** open through
  OpenCV's FFmpeg backend; RTSP on port 8554 is the working ingest path from this
  network.

## 5a. Where the concurrency limit actually is

The question a scalability reviewer will ask is whether a wall that struggles at
nine cameras can possibly be a path to eighty thousand. The answer depends
entirely on *which side* the limit sits on, so we measured it rather than
asserting it.

N concurrent RTSP connections opened simultaneously from one machine, recording
how long the gateway took to accept each and deliver a first frame:

Measured after the organisers' 5 September fix, which restored the feeds and
added an authentication layer to both the portal and RTSP:

| Concurrent connections | Succeeded | Wall time | Our CPU (mean / peak of 20 cores) |
|---|---|---|---|
| 2 | **2 / 2** | 12 s | 4% / 6% |
| 4 | **4 / 4** | 26 s | 4% / 8% |
| 6 | **6 / 6** | 41 s | 5% / 10% |
| 8 | 7 / 8 | 88 s | 4% / 8% |

Per-connection accept times at N=8: 3.8 s, 7.8 s, 26.7 s, 33.3 s, 56.4 s, 60.0 s,
63.0 s, 73.3 s — a queue, not a load curve.

**Six concurrent streams is the dependable ceiling on this gateway**, and the
platform's defaults are set to it: the wall opens at 2×2 and the indexer runs six
streams. Authentication is confirmed working — an unauthenticated RTSP request
returns `401 Unauthorized`, and the registered credentials connect in 3.6 s.

**Our machine is idle at 4% CPU while the eighth connection takes 73 s to be
accepted.** Nothing on this side is saturated: not CPU, not memory, not the
decoder, not the network. The gateway accepts connections roughly serially, and
the accept time grows linearly with how many are waiting.

The organisers' fix improved the HTTP tier markedly — a portal request went from
9–30 s or timing out, to 0.5–7 s — and raised the eight-connection result from
6/8 to 7/8. The serial-accept behaviour is unchanged, which is consistent with it
being a property of a single shared gateway rather than a fault.

This matters for the scale argument in two ways.

**First, the demonstrated limit is not ours to fix and not the one that scales.**
A shared sandbox serving every competing team from one endpoint is a
demonstration environment, not a deployment topology. Its concurrency ceiling
says nothing about a statewide design, because no statewide design routes 80,000
cameras through one gateway — which is precisely the argument of §9 in the HLD,
and the reason edge-first is the only viable topology.

**Second, it is a live illustration of that argument.** We are watching, at a
scale of eight cameras, exactly the failure mode the arithmetic predicts at
80,000: a single aggregation point becomes the constraint long before compute
does. Our own numbers show the compute side has enormous headroom — 26 concurrent
ANPR streams per machine (§1), 4% CPU while accepting eight connections — and the thing that
breaks first is the shared ingress. That is the case for district edge nodes,
made with evidence rather than a diagram.

The platform responds to this the way a deployed system should: connections are
staggered rather than opened in a burst, one upstream connection per camera is
shared by all viewers, idle relays release their connection, and a tile that
cannot be served says so plainly instead of hanging.

**Confirmed by the organisers, 7 September.** In reply to our report
(`DOCS/email_to_sentinel_support.txt`) the Sentinel support team wrote that
there is "no specific officially prescribed concurrent RTSP connection limit
per registered team", that the connection-establishment behaviour "may be
related to the sandbox gateway", and that a capped connection count with
graceful degradation "is appropriate". The full reply is at
`DOCS/reply_from_sentinel_support.txt`. The measurement above is therefore not
our interpretation alone; the infrastructure owner has attributed it to the
gateway.

## 6. Camera registry

The sandbox catalogue (`/cameras.json`, behind a form login) publishes **only
`id` and `name`** for 30 cameras — no coordinates, no department, no codec. All
30 are located by hand-verification against the place named in each entry, and
every camera records `geo_source` and `geo_confidence` so provenance travels with
the record. Coordinates are approximate site locations, not a surveyed register,
and the reports say so.

## 2g. Full 30-camera sweep, 8 September 2026, ~10:45-11:35 IST

Access returned on the morning of 8 September (see 2f), so the sweep deferred
from the previous evening was run: all thirty cameras, 45 seconds each, with the
completed recogniser — confusion model, refinement pass, RTO data and prior.

**Result: not one correct plate was read anywhere on the grid.**

Three reads validated or nearly validated. All three were wrong, and each failed
in a different way. That is the finding, and it is worth more than a pass rate.

| Camera | px/char | Pipeline read | Ground truth from the evidence crop | Failure |
|---|---|---|---|---|
| cam10 | 6.5 | `GJ038988` @ 0.83 | `GJ03HR4879` | Right state and RTO, **wrong serial** |
| cam18 | 6.1 | `GJ121181` @ 0.47 | two-line yellow commercial plate | Two rows flattened into one string |
| cam24 | 14.2 | `C4MPC871` ×26 | the caption "Camera 01" | Burnt-in overlay read as a plate |

Evidence crops: `DOCS/evidence/sweep_20260908/`.

### Why cam10 is the one that matters

`GJ038988` is a legitimate Indian registration format — two letters, two digits,
no series letters, four digits — so the grammar layer passes it, correctly. The
state code is real. The RTO code is real. The confidence is 0.83. Every check
the pipeline had said yes, and the four digits that actually identify the
vehicle were wrong: `8988` against a true `4879`.

This is the failure mode that matters in a policing system. A read that is
obviously garbage is harmless because nobody acts on it. A read that is
well-formed, confident and wrong is one that puts an officer in front of the
wrong vehicle, and no amount of grammar or confidence tuning detects it, because
at 6.5 px per character the recogniser is not reading glyphs at all — it is
producing a plausible shape. It was confident about a hallucination.

**Fix:** `MIN_ALERTABLE_PX_PER_CHAR = 12.0` in `app/vision.py`. A track whose
plate never exceeded that resolution is indexed as a *partial* — searchable,
badged, with its evidence crop available for a human to judge — and can never
raise an alert. The threshold sits above every false positive observed here
(max 6.9) and below the 15-20 at which reads measured correct 6/6, so it
separates the two populations actually observed rather than asserting where
correctness begins. Published guidance asks 20-30; this is deliberately the
weaker, evidence-backed claim.

### Why cam24 was the most misleading

cam24 measured 14.2 px per character, the **highest on the entire grid** —
double cam14 and above the alertable threshold. On the ranking it was the
best-sited camera we had. It watches an empty residential street at 02:27, and
the "plate" was the caption `Camera 01` burnt into the corner of the frame.
Rendered text is sharper than any real plate at distance, so overlay furniture
does not merely produce false reads: it produces the *highest-quality* false
reads and rises straight to the top of a quality ranking.

**Fix:** static-region suppression in `PlateDetector`. A box recurring at the
same coordinates beyond `STATIC_REGION_HITS` is furniture, because a caption
occupies identical pixels in every frame and a vehicle never does. Keyed per
camera, since one detector instance serves every stream. Verified against the
live feed: caption detections fell from 26 to 6 in 45 seconds, the remainder
being the pre-threshold reads before the region is established — deliberate, so
a genuine plate is never lost to a cold start. Those reads were already rejected
downstream by the state-code check, so this is defence in depth; its real value
is that a caption can no longer disguise an empty street as a good ANPR site.

### What the sweep says about the grid

Twenty-six of thirty cameras produced no plate-shaped box at all in 45 seconds.
The footage is also a loop of recorded video — cam24's burnt-in timestamp reads
`08-08-2026`, a month before the sweep — so traffic density is whatever was
recorded, not what is on the road now.

Combined with sections 2b and 2c, the conclusion is unchanged and now measured
across the whole grid rather than two cameras: **these are wide-area overview
cameras, and no recogniser reads plates from them.** The constraint is optics
and siting, which is a procurement decision. It is the single most useful thing
this project can tell the department, and it is worth more than a demonstration
tuned to hide it.

## 2h. Gateway restored, 9 September 2026 — first live plate reads, and what the platform did with them

The gateway came back around 16:30 IST. A single-attempt liveness sweep with an
8 s timeout found **25 of 30 cameras delivering frames**; cam08, cam10, cam11,
cam21 and cam25 did not answer within the window. cam10 had delivered 35 frames
to the detection worker twenty minutes earlier between 30 s stalls, so "dead" on
one attempt means flaky, not offline. Resolutions across the live set: fifteen
at 1920×1080, five at 1280×720, three at 1280×960, one at 960×576, one at
2560×1440.

The ANPR worker then ran for ten minutes on cam01, cam12 and cam14. It indexed
two plates — the first live reads this grid has produced — both from cam12, the
Adalaj toll plaza, 27 seconds apart:

| Read | Vote | Plate box | px/char | Per-frame reads inside the track | Flagged | Alerts |
|---|---|---|---|---|---|---|
| `RJ3E4555` | 0.81 | 53 px wide | 6.6 | `RJEEA555` `RJAEA555` `RJEEA555` | partial | 0 |
| `RJ4E4555` | 0.79 | 51 px wide | 6.4 | `J4TEA555` `WJAEA555` | partial | 0 |

Two things to read off that table. First, the per-frame reads inside each
track disagree with each other and with the vote, and the two tracks — almost
certainly the same vehicle — disagree on the third character. Both are eight
characters, one short of any valid Indian format. These are the confidently
wrong reads §2g predicted, now observed on live footage with a vote confidence
of 0.8.

Second, the platform handled them correctly. Both were written with
`partial: true` and the reason `below readable resolution; 6.4 px per
character, need 12`, stored as searchable, and **raised no alert** — the
`MIN_ALERTABLE_PX_PER_CHAR = 12` rule from §2g doing on live data exactly what
it was added to do. A system without that rule would have put two wrong
Rajasthan registrations in front of an operator with 80% confidence attached.

One thing it did not catch: the plate-grammar stage labelled both eight-character
strings `standard` format with zero corrections. The partial flag made this
harmless here, but a length check belongs in the grammar as well, so a
malformed read is rejected for being malformed rather than only for being small.
Noted rather than fixed, because it changes evidentiary behaviour and should be
tested against the ground-truth set in §2 first.

**The sandbox feeds are recorded footage, not live cameras.** Frames captured
from cam14 at 16:55 IST on 9 September carry a burnt-in timestamp of
`13-06-2026 21:27:51` and show a night scene; sunset in Ahmedabad in September
is after 18:30. The gateway is replaying stored video. This changes nothing
about resolution, plate legibility or detector behaviour — the pixels are what
the cameras produced — but it means "live" throughout this document means
*streamed live from the gateway*, and any time-of-day analysis run against the
sandbox measures the recording, not the road. The diurnal shape on the Grid
Health page therefore comes from the seeding tool and is labelled as such; the
real-data view shows what the loop contains.

**Corrupted frames lose detections quietly.** The same cam14 frames show heavy
macroblocking on the near lanes from RTSP packet loss — the `bytestream` errors
the decoder logs — and the detector found three clean cars on the far side and
none of the eight artefacted autos in front. That is not a wrong count but a
silently low one. The scene tool now applies the same `frame_is_decodable` and
`frame_is_smeared` gates the ANPR pipeline uses, skips such frames, and reports
how many it skipped; a skipped frame is not a sampled one.

Reproduce: `python anpr_worker.py --camera cam12` with `SENTINEL_WORKER_TOKEN` set.

## 3. Object detection — the analytics tier that works on these cameras

Section 2g reports that no camera on the government grid produced a correct
plate: the limit is 4 to 14 pixels per character against the 20-30 ANPR needs,
and that is optics rather than software. The obvious question follows — if the
plates cannot be read, is there anything useful in these frames at all?

There is. The same frames contain vehicles and people that a general detector
resolves comfortably.

### 3a. Measured on real sandbox frames

`rf-detr-nano-384-coco` through ONNX Runtime on CPU, no GPU, on the evidence
frames captured during the 8 September sweep:

| Frame | Resolution | Inference | Objects found |
|---|---|---|---|
| cam10 Char Chowk, Junagadh | 1920×1080 | 79 ms | 2 car, 4 motorcycle, 5 person, 1 truck |
| cam12 Adalaj toll plaza | 1280×720 | 70 ms | 1 person, 1 truck |
| cam18 Rajkot | 1920×1080 | 67 ms | 3 person, 1 boat |
| cam24 residential, 02:27 | 960×576 | 67 ms | **none** |

cam24 is the useful negative. It watches an empty street at night, and the
detector correctly returns nothing — the same camera whose burnt-in caption the
plate recogniser read as `C4MPC871` twenty-six times. A detector that finds
objects in an empty frame would be worse than no detector.

Reproduce: `python tools/scene_analytics.py --camera cam10 --seconds 90`

### 3b. Model choice, measured rather than assumed

On cam10's frame, same machine:

| Model | Inference | Objects |
|---|---|---|
| `rf-detr-nano-384-coco` | 66 ms | 12 |
| `rf-detr-small-512-coco` | 126 ms | 15 |

Nano is 1.9× cheaper and finds 12 of the 15. The three it misses are small and
distant — objects an operator could not act on anyway. Since the entire argument
for this tier is that it runs on cameras the ANPR tier cannot serve, cost per
frame is the property being optimised, and nano is the right default on CPU.
Small is one argument away for a deployment with GPUs.

### 3c. Why this changes the scaling arithmetic

| Tier | Mean inference | Streams per 20-core machine |
|---|---|---|
| Tiled ANPR (§1) | 185.9 ms | ≈26 (measured) |
| Object detection | 70 ms | ≈69 (projected) |

The ANPR figure is a measured throughput from §1. The detection figure is a
projection from it, scaled by the ratio of inference cost — 185.9 / 70 = 2.66 —
and nothing else: same machine, same runtime, same sampling assumption, so the
only variable is time per frame. It is labelled projected rather than measured
because a 30-stream detection benchmark has not been run; the honest claim is
the ratio, not the absolute.

The gap widens further in practice, because the two tiers need different
sampling. ANPR must see most frames a vehicle is in view or the track breaks and
the vote has too few reads. Counting how busy a junction is does not: two frames
a second is generous, which is a further 7× on the sampling side.

That difference — **2.66× on inference cost alone**, and far more once the
sampling difference is counted — is what makes the tiering in HLD §9.4 a
strategy rather than a hedge: run object detection everywhere, and reserve ANPR for cameras sited
well enough to support it. On this grid that would be no cameras at all today,
which is a procurement finding the department can act on.

### 3d. What is stored, and why it is not per frame

Counts are aggregated into one row per camera per minute before they reach the
database. At one inference per second across 80,000 cameras, per-frame rows
would be **6.9 billion a day**; minute buckets are **115 million**, and the write
rate stops depending on frame rate at all.

Within a bucket the figure kept per class is the **peak in any single frame**,
not the sum across frames. Summing counts a parked car once per frame — sixty
times a minute — producing a number that grows with sampling rate rather than
with traffic. Peak answers the question a junction count is actually asking.

### 3e. The 66 ms figure re-measured, two ways it was measured wrongly, and what the video relay costs

The figures in §3a–3b were re-measured on 9 September with `tools/bench_detector.py`,
which exists because the number was got wrong twice in one afternoon:

| Condition | Steady-state inference | Note |
|---|---|---|
| Quiet machine, real 720p sandbox frames | **66 ms** (n=2, 66–67) | agrees with §3a/3b |
| Same, but the video wall relaying through the API host | median 188 ms, mean 987 ms, max 2.6 s (n=23) | contention |
| cam14 worker run, wall relaying + seeder posting | 432 ms mean (n=53) | contention |
| Random-noise frame, machine at 95% from tiled ANPR | 262–329 ms | **wrong**: noise floods the candidate stage; and the load |
| cam10 live run, 35 frames, mean including model load | 1,356 ms | **wrong**: 861–1,193 ms of one-off model load spread over 35 frames |

The first wrong number nearly rewrote §3a. It was taken on a synthetic frame —
which produces boxes a real scene never does — while three tiled ANPR streams
held the CPU, and neither condition is one a deployment sees. The second was
the tool's own mean folding the ONNX session load into a short run; the tool
now reports warm-up separately, and the benchmark refuses to start on a busy
machine rather than measuring some other process.

**The relay is not free.** With the video wall open and no detector running, the
API host sat at **26% of 20 cores** (one core at 72%) doing nothing but decoding
H.264 and re-encoding MJPEG for the tiles. §5a's 4% was measured while
*accepting* eight RTSP connections, not while transcoding them, and the two
claims have been separated in the text. The operational consequence is the
one HLD §9 already draws for other reasons: viewing and inference must not
share a host. A detector that runs at 66 ms alone and 188–432 ms beside a wall
has lost most of its per-machine capacity to somebody watching video.

## 4. Bandwidth — what edge processing actually saves

The scale-out design in HLD §9.2 keeps inference at the district edge and
backhauls only metadata. That is a common claim; this section puts a measured
number on it, because the difference decides whether a statewide deployment is a
networking problem or not.

### 4a. Measured inputs

| Quantity | Value | How |
|---|---|---|
| Captured sandbox video | 1280×720, 25 fps, **2.82 Mbps** | Measured on the 26.4 s clip in `sample_feeds/` |
| Typical 1080p CCTV | ~4.5 Mbps | Standard H.264 constant-quality figure for this class of camera |
| One detection payload | **277 bytes** | The exact JSON body `anpr_worker.py` posts |
| One scene bucket | **260 bytes** | The exact JSON body `tools/scene_analytics.py` posts |

### 4b. Per camera, per hour

| | Raw video | Metadata |
|---|---|---|
| 720p @ 2.82 Mbps | 1.27 GB/h | — |
| 1080p @ 4.5 Mbps | **2.02 GB/h** | — |
| Busy junction — 120 plates/h + 60 buckets | — | **47.7 KB/h** |
| Quiet street — 20 plates/h + 60 buckets | — | **20.6 KB/h** |

**A busy camera backhauls about 42,000× less than its own video.** A quiet one,
96,000× less. The ratio improves as the scene gets quieter, which is the right
direction: the cameras that cost the most to backhaul raw are the ones with
least to say.

### 4c. At 80,000 cameras

| Approach | Sustained backhaul |
|---|---|
| Centralised — every stream to the core | **360 Gbps** (162 TB/hour) |
| Edge-first — metadata only | **8.7 Mbps** (3.9 GB/hour) |

360 Gbps of sustained inbound is a core-network build, not a software
deployment. 8.7 Mbps is a single office connection. That is the entire argument
for edge-first in one comparison, and it is why HLD §9.2 puts inference in the
district rather than the state data centre.

### 4d. What this does not include

Stated so the figures are not read as more than they are:

- **Live viewing is separate.** An operator watching nine tiles pulls those nine
  streams, and that traffic is real. It is bounded by how many operators are
  watching, not by camera count — which is precisely why it scales differently
  from analytics and is planned separately.
- **Evidence crops are not counted above.** A crop is ~15 KB and is written to
  district storage, not backhauled. Only its URI travels, and that URI is in the
  277 bytes.
- **Recorded retention is a storage problem, not a bandwidth one.** Footage kept
  for evidentiary purposes stays where it was recorded until something asks for
  it; §9.3 covers the tiering.
