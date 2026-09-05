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

| Concurrent connections | Succeeded | Wall time | Our CPU (mean / peak of 20 cores) |
|---|---|---|---|
| 2 | **2 / 2** | 12 s | 4% / 6% |
| 4 | **4 / 4** | 36 s | 4% / 12% |
| 8 | 6 / 8 | 102 s | 4% / 11% |

Per-connection accept times at N=8: 4.3 s, 8.2 s, 20.6 s, 28.4 s, 57.4 s, 61.3 s,
65.2 s, 71.7 s — a queue, not a load curve.

**Our machine is idle at 4% CPU while connections take over a minute to be
accepted.** Nothing on this side is saturated: not CPU, not memory, not the
decoder, not the network. The sandbox gateway accepts connections roughly
serially, and the accept time grows linearly with how many are waiting.

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
ANPR streams per machine (§1), 4% CPU while relaying video — and the thing that
breaks first is the shared ingress. That is the case for district edge nodes,
made with evidence rather than a diagram.

The platform responds to this the way a deployed system should: connections are
staggered rather than opened in a burst, one upstream connection per camera is
shared by all viewers, idle relays release their connection, and a tile that
cannot be served says so plainly instead of hanging.

## 6. Camera registry

The sandbox catalogue (`/cameras.json`, behind a form login) publishes **only
`id` and `name`** for 30 cameras — no coordinates, no department, no codec. All
30 are located by hand-verification against the place named in each entry, and
every camera records `geo_source` and `geo_confidence` so provenance travels with
the record. Coordinates are approximate site locations, not a surveyed register,
and the reports say so.
