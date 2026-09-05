# Demo video scripts

Two videos are required. Both must show real software doing real work — the rules
state that mock-ups, animations and simulated interfaces without an operational
backend will not be considered.

**Before recording, both times:**

```bash
# 1 · Backend
cd backend && python run_server.py

# 2 · Frontend
cd frontend && npm run dev

# 3 · Seed the demonstration route (real inference, realistic timestamps)
cd backend && powershell -File tools/seed_demo_route.ps1
```

Then: browser to 125% zoom, 1080p/30fps in OBS, every unrelated tab and
notification closed, desktop icons hidden. Rehearse twice before recording.
Record clean footage first and lay the voiceover over it afterwards — narrating
live is much harder to get right.

---

## Video 1 — Own feed (2–3 minutes, hard limit)

**Best option: use your own footage.** A phone video of a road with a readable
plate, run through the real pipeline:

```bash
cd backend
python tools/demo_seed.py --video my_road_video.mp4 --camera cam01
```

That is genuinely stronger than the synthetic clip, because the plates are real.
If no footage is to hand, `tools/make_sample_feed.py` produces a labelled
synthetic clip and the pipeline is identical — but say on camera that it is
synthetic. Never imply it is real footage.

### Shot list

| # | Duration | Screen | What to show | What to say |
|---|---|---|---|---|
| 1 | 0:00–0:15 | Search, results already on screen | **Open on the result.** A plate, its evidence crop, confidence, camera and timestamp. | "This vehicle was detected by our platform on live video. Everything you are about to see is running software — no mock-ups." |
| 2 | 0:15–0:40 | Terminal running `demo_seed.py` | Plate lines appearing with confidence and read counts | "The pipeline reads the plate on every frame of the vehicle's track — twenty to thirty-five reads here — then votes per character, weighted by the OCR's own confidence." |
| 3 | 0:40–1:00 | Terminal, point at a corrected read | A `[grammar-corrected]` line | "Indian plates have a fixed format, so we know which positions must be letters and which digits. Our OCR returned GJO-one; position two must be a digit, so that O is unambiguously a zero. Deterministic, not guesswork." |
| 4 | 1:00–1:20 | Watchlist | Add `GJ01AB1234`, reason "stolen", severity critical | "The watchlist is checked on every detection, exact first then fuzzy." |
| 5 | 1:20–1:45 | Terminal + UI side by side | `*** WATCHLIST ALERT ***` in the terminal, toast appearing in the UI | "The match fires an alert over a WebSocket the instant it is written. Nobody is watching a screen." |
| 6 | 1:45–2:10 | Alerts | The alert with severity and match type; acknowledge it | "Alerts carry the reason and severity from the watchlist entry, so prioritisation is a property of the record, not a UI decision." |
| 7 | 2:10–2:40 | Search → Show Route on Map | The polyline, the speed labels, one flagged transition | "Sightings ordered by time, with the implied speed between each. This leg is flagged as physically impossible — we show it rather than hiding it, because it tells the investigator either a plate was misread or two vehicles share a registration." |
| 8 | 2:40–2:55 | — | Closing frame | "Pretrained models running locally on CPU. No frame leaves the deployment; no external API is in the alerting path." |

**Cut ruthlessly to stay under three minutes.** If something must go, cut shot 6.

---

## Video 2 — Government feed (no hard limit; aim for 4–5 minutes)

This one is evaluated first and carries the mandatory government-feed
demonstration. Submit the output report alongside it.

### Shot list

| # | Screen | What to show | What to say |
|---|---|---|---|
| 1 | Terminal: `curl /api/v1/ingest/catalogue` | The live catalogue coming back from `cctv.corp8.cloud` | "Onboarding starts from the sandbox catalogue itself. We never hardcode camera ids — the catalogue is the contract." |
| 2 | Map, click **Sync Catalogue** | Cameras refreshing; 30 live | "Thirty cameras onboarded from the live grid." |
| 3 | Map, zoomed to state | Pins across Ahmedabad, Junagadh, Rajkot, Navsari, Kutch | "The catalogue publishes only an id and a name — no coordinates at all. Every location here is derived from the real site name in the entry." |
| 4 | Map, click a pin | The popup's **Location:** provenance line | "And each camera records how its position was arrived at — hand-verified, geocoded, or a district approximation. We do not invent coordinates; a camera we cannot place is reported as unlocated." |
| 5 | Map filters | Department and status layers | "Layers by department and status." |
| 6 | Video wall, **2×2** (open it a minute early so tiles are up) | Live tiles from the sandbox | "Live viewing through our own relay. The sandbox's HTTP tier is too slow to play — we measured nine to thirty seconds for a playlist — so we take its RTSP, which is reliable, and re-serve it. The sandbox credential never reaches the browser." |
| 7 | Video wall, **1×1** | One tile full screen, visibly sharper | "One camera at full quality. Quality follows the layout: fewer tiles, more resolution and frames each." |
| 8 | Terminal: `anpr_worker.py` running | Status lines, streams alive | "The ANPR indexer runs continuously against the live feeds. It has been running since Thursday, so the index is already built when a registration number arrives." |
| 9 | Search | Type a plate, results with crops | "Every sighting: camera, department, location, timestamp, confidence, and the evidence crop." |
| 10 | Search, misspell one character | Fuzzy match still returns the sightings | "ANPR will misread a character. Trigram search recovers it — exact-match-only would fail in front of you on a plate we genuinely detected." |
| 11 | Show Route on Map | Polyline with speeds, one flagged leg | "The route across cameras, with speed between each sighting and implausible transitions flagged rather than dropped." |
| 12 | Dashboard → Export | XLSX and PDF downloading, then open the PDF | "The output report, generated from the index — plates, timestamps, cameras, locations, and a header stating how the numbers were produced." |
| 13 | Terminal: `analytics/audit` | Audit rows with actor, purpose, case reference | "Every search, route and export is recorded with who ran it and why. Surveillance capability with accountability attached." |
| 14 | Slide or terminal | The yield table from `DOCS/MEASUREMENTS.md` §2a | **Say this plainly:** "One honest finding. On this grid our pipeline reads no valid plates. The detector proposed 165 plate-shaped regions and the OCR returned 87 strings — every one was roadside signage, and our Indian-plate validator rejected all of them. These are wide-area night PTZ overviews where a plate is five to fifteen pixels. The same pipeline recovers six of six on footage where plates are legible. The limit is camera siting, not the software — and that is a finding worth reporting to the department." |

### Optional shot 15 — the scalability question, answered before it is asked

If the video has room, this is worth thirty seconds. Show the concurrency table
from `MEASUREMENTS.md` §5a and say:

> "One more honest measurement. When we open eight camera connections at once,
> the sandbox gateway takes seventy seconds to accept the eighth — while our
> machine sits at four percent CPU. The limit is the shared gateway, not our
> software. That is the eighty-thousand-camera problem at a scale of eight, and
> it is exactly why our architecture is edge-first: a camera in Junagadh streams
> to a Junagadh edge node, not across the state. Four hundred nodes at two
> hundred cameras each is ordinary server load."

Getting there first turns the obvious objection into a demonstration that you
understand the real constraint.

### Why shot 14 matters

An evaluator will test ANPR on the sandbox and see nothing. Getting there first,
with the stage-by-stage measurement and a correct explanation, converts what
looks like a failure into evidence of rigour. Teams that quietly claim working
ANPR on this grid will be caught in one question.

---

## After recording

- Upload as **Unlisted** on YouTube — not Private, which evaluators cannot open —
  or Drive/OneDrive set to **Anyone with the link — Viewer**
- **Open every link in an incognito window and check it plays**
- Paste the links into `README.md` under "Submission links"
- Attach `submission/sentinel_output_report.xlsx` and `.pdf` alongside video 2
