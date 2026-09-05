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

## 6. Camera registry

The sandbox catalogue (`/cameras.json`, behind a form login) publishes **only
`id` and `name`** for 30 cameras — no coordinates, no department, no codec. All
30 are located by hand-verification against the place named in each entry, and
every camera records `geo_source` and `geo_confidence` so provenance travels with
the record. Coordinates are approximate site locations, not a surveyed register,
and the reports say so.
