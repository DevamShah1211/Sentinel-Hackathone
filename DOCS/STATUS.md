# Status - what is done, what is left

**Screening submission: Tuesday 15 September 2026.** Live round: 23 September.

Screening is a gate, not the judging. Five of the seven evaluation areas are
scored on documents and videos rather than on running software, and the playbook
lists a hosted URL as *optional* for this stage. So the deployment work below is
deliberately parked: on the 23rd the platform is demonstrated live from a laptop,
where the relay, the WebSocket and the indexer all work already.

Repository: `main`, 91 commits, clean, pushed.

---

## Done

### The platform

| | Where | Verify |
|---|---|---|
| ANPR pipeline - tiled inference, track voting, Indian plate grammar | `backend/app/vision.py`, `plate_grammar.py` | `python tools/make_sample_feed.py --validate` → 6/6, 0 false positives |
| Partial-read guard - low-resolution reads indexed, never alertable | `MIN_ALERTABLE_PX_PER_CHAR = 12` | MEASUREMENTS §2g |
| Object detection tier - vehicles and people where plates cannot be read | `backend/app/object_detection.py` | `python tools/scene_analytics.py --camera cam14` |
| Camera registry, GIS map, 30 cameras located | `/map` | `GET /api/v1/ingest/status` |
| Video wall - own MJPEG relay, sandbox credential never reaches the browser | `/wall` | 2×2 and 1×1 layouts |
| Plate search, fuzzy matching, route reconstruction with flagged transitions | `/search` | Search `GJ03CJ6081` → 153 km/h leg flagged |
| Watchlist and live alerting over WebSocket | `/watchlist`, `/alerts` | 38 alerts in the index |
| Grid health and scene analytics | `/health` | Coverage gap, activity by hour, per-camera rate |
| Live detection feed, partial reads badged | `/live` | Added 11 September |
| Role enforcement, rate limiting, audit trail | `backend/app/security.py`, `middleware.py` | Viewer token: 403 on audit and export |
| Test suite | `backend/tests/` | `python -m pytest tests/ -q` → **187 passed** |

### Submission artefacts

| | File |
|---|---|
| Technical proposal / HLD | `submission/Sentinel-HLD.pdf` - 21 pages |
| Solution presentation | `submission/Sentinel-PRESENTATION.pdf` - 14 pages |
| Output report | `submission/sentinel_output_report.xlsx` · `.pdf` - regenerated 11 Sept from the live index |
| Evidence images for the video | `DOCS/evidence/Sentinel Video/` - three, plus `Video.mp4` |
| Repository | https://github.com/DevamShah1211/Sentinel-Hackathone |

### The finding the submission rests on

Thirty government cameras were swept; none produces a readable plate. The
constraint is optics - 4 to 14 pixels per character against the 20-30 a
recogniser needs - and it is a procurement conclusion for the department, not a
software failure. Confirmed twice more since:

- **Live, 9 September.** With the gateway restored the indexer produced its first
  two live reads, both at 6.5 px/char from the Adalaj toll plaza. Both were
  flagged partial and raised no alert. MEASUREMENTS §2h.
- **Independently, 11 September.** A 104-clip Kaggle dataset of Indian road
  footage: 31 clips produced any plate box, the median is 6.3 px/char, and
  exactly one reached the 14 px floor - where the "plate" turned out to be a
  truck weight placard. On a clip at 6.9 px/char the pipeline voted four
  different answers for one vehicle, none correct, all passing grammar.

---

## Left to do - screening, by 15 September

### 1. Government-feed video - recorded, not finished

`DOCS/evidence/Sentinel Video/Video.mp4`, 4m17s, 1376×776, **no audio**.

- [ ] Append the three images, ~20s each, in this order:
      `Number Plate detection Image 1.png` (the optics finding) →
      `Number Plate detection Image 2.png` (the confident-and-wrong read) →
      `Object Detection Image.jpg` (what the cameras can do instead)
- [ ] Record a voiceover over the whole thing
- [ ] Trim the mid-load frame near 3m59s - Grid Health shows `0/30` for a second
      and it reads as broken
- [ ] Export 1080p

Clipchamp ships with Windows and does all of this. Wording for the three images
is in `DEMO_SCRIPTS.md` and `RECORDING_CARD.md`.

### 2. Own-feed video - not started

Two options, in order of preference:

**Film 30-60 seconds on a phone.** Real plates, and the strongest version of this
video. Check it before relying on it:

```powershell
cd backend
python tools/live_demo.py --source sample_feeds/my_road.mp4 --check   # want >= 14 px/char
python tools/demo_seed.py --video sample_feeds/my_road.mp4 --camera cam01
```

**Or use the synthetic clip.** `sample_feeds/own_feed_demo.mp4` passes at 16.6
px/char with 85 of 90 reads validated. Every frame is labelled
`SENTINEL SYNTHETIC TEST FEED - NOT REAL FOOTAGE`, so say once on camera that it
is synthetic with known ground truth - which is what lets accuracy be stated
exactly: 6/6, zero false positives.

**Not the Kaggle footage.** Nothing in it is readable; using it would put
confidently wrong plates in a submission video and contradict the finding above.

Shot list, 8 shots, 2-3 minutes hard limit: `DEMO_SCRIPTS.md` §Video 1.

- [x] Both videos uploaded to Google Drive: [Google Drive Folder](https://drive.google.com/drive/folders/1dfKs9nYNW_KThp3rWlwQcQxe7_c-eQca?usp=drive_link)
- [x] Link verified and set to *Anyone with the link - Viewer*

### 4. Fill the last README links

- [x] README submission table updated with Google Drive folder link.

### 5. Submit the portal form

- [ ] Paste every link
- [ ] Test credentials if a hosted URL is given: `admin@sentinel.gujarat.gov.in`
      and the `DEMO_ADMIN_PASSWORD` from the root `.env`
- [ ] Screenshot the confirmation

---

## Left to do - before the live round on 23 September

### 6. Rotate the sandbox password, then rewrite history

**This is the one item worth doing before the 15th anyway.** The sandbox password
is still present in **7 commits** of the git history. The repository is private,
which closes the practical exposure, but it is the kind of thing an NFSU reviewer
notices and it colours how the rest is read.

Order matters: rotate on the sandbox portal first, then rewrite. Scrubbing
history while the credential still works achieves nothing.

A tested `git filter-repo` rewrite is prepared - 56 commits preserved, working
tree byte-identical, mirror backup taken. That backup lives in session-scoped
temporary storage and will not survive indefinitely; take a fresh clone as a
backup before running it.

### 7. Deploy, if wanted

Configuration is ready and correct. `docker-compose.yml`, both Dockerfiles, and a
root `.env` with fresh secrets and `AUTH_ENABLED=true` are in place. Docker is
not installed on the development machine, so nothing has been brought up.

**Not Vercel.** The relay holds a `multipart/x-mixed-replace` connection open for
as long as an operator watches, `/ws/alerts` holds a WebSocket, and the indexer
is a daemon holding six RTSP connections. None of the three survives a serverless
function. Render or Railway fit; the Supabase database is already cloud-hosted
and stays where it is.

For the live round a laptop with a Cloudflare tunnel is sufficient and simpler:

```powershell
cloudflared tunnel --url http://localhost:8080
```

### 8. Open items in the code

- `/live` and `/proxy-hls` are unauthenticated. Everything else enforces roles;
  these two need a signed stream token.
- The plate grammar accepts an eight-character string as `standard` format. The
  partial flag makes it harmless today, but a length check belongs there - and it
  must be tested against the §2 ground truth first, since it changes evidentiary
  behaviour.

---

## If something breaks on the day

| Problem | Answer |
|---|---|
| Sandbox unreachable | Registry, search, route, reports and audit all run from the index. The video wall degrades to an explanatory tile, not a black screen. |
| RTSP returns 401 | Happened twice; both times the organisers restored access within hours. The draft mail is `DOCS/email_gateway_down.txt`. |
| "Why does ANPR find nothing on the grid?" | MEASUREMENTS §2g and §2h, plus the Kaggle crops in `DOCS/evidence/kaggle_reads/`. Answer it before they ask - it is the strongest thing in the submission. |
| "If it struggles at 9 cameras, how do you reach 80,000?" | MEASUREMENTS §5a. Our machine sits at 4% CPU while the gateway takes 73 s to accept the eighth connection. The limit is the shared ingress, not our compute. |
