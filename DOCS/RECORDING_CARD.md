# Recording card - government-feed video

One page, for a second screen while recording. The full script with every
sentence is in [DEMO_SCRIPTS.md](DEMO_SCRIPTS.md) §Video 2; this is the version
you can actually glance at mid-take.

## Before you press record

**These are PowerShell commands** - this project is developed on Windows, and
the bash forms (`export VAR=…`, `$(cmd)`) fail with `CommandNotFoundException`.

```powershell
cd backend;  python run_server_noreload.py        # NOT run_server.py
cd frontend; npm run dev
```

Then, in a third terminal, start the indexer **and leave it running** - shot 8
shows it alive, and an indexer started on camera looks staged:

```powershell
cd backend
$r = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/auth/login -Method Post `
     -ContentType 'application/json' `
     -Body '{"email":"admin@sentinel.gujarat.gov.in","password":"<DEMO_ADMIN_PASSWORD>"}'
$env:SENTINEL_WORKER_TOKEN = $r.access_token
python anpr_worker.py --camera cam12 --camera cam14 --max-streams 2
```

A 401 from the worker means the token is missing or expired - re-run the two
lines above. Note the login body is JSON, not form-encoded.

- [ ] **Open the video wall a full minute early.** The gateway accepts
      connections nearly serially; tiles that are already up look instant, tiles
      coming up on camera look broken.
- [ ] Use **2×2**, not 3×3.
- [ ] Browser at 1920×1080, zoom 100%, bookmarks bar hidden.
- [ ] Close Slack/WhatsApp/mail. A notification toast in the final cut is a reshoot.
- [ ] Have `DOCS/evidence/cam12_toll_plaza_detection.jpg` and
      `cam12_plate_crop.jpg` open in an image viewer, ready to alt-tab to.

## Plates that are actually in the index

Verified live before recording. Do not improvise a plate - an empty result on
camera costs you the shot.

| Plate | Sightings | Use it for |
|---|---|---|
| `GJ01KA7392` | 5, speeds 18-24 km/h | Shot 9-11. The clean, believable journey |
| `GJ03CJ6081` | 3, one leg at **153 km/h, flagged** | Shot 11. The clone case - `flagged_transitions: 1` |
| `GJ18DH2745` | 4, 24-25 km/h | Shot 11a, the second route |
| `MH12QP5837` | 4, 22-23 km/h | Spare |

For shot 10 (fuzzy search), type `GJ01KA7892` - one character off `GJ01KA7392`.

## The 15 shots, in order

| # | Screen | One-line reminder |
|---|---|---|
| 1 | Terminal | `curl /api/v1/ingest/catalogue` - "the catalogue is the contract" |
| 2 | Map → Sync Catalogue | 30 cameras onboarded from the live grid |
| 3 | Map, state view | "The catalogue gives only id and name - every location is derived" |
| 4 | Map, click a pin | The **Location:** provenance line. "We do not invent coordinates" |
| 5 | Map filters | Department and status layers |
| 6 | Video wall 2×2 | "Sandbox credential never reaches the browser" |
| 7 | Video wall 1×1 | Visibly sharper. "Quality follows the layout" |
| 8 | Terminal, indexer | Status lines, streams alive |
| 9 | Search `GJ01KA7392` | Sightings with evidence crops |
| 10 | Search `GJ01KA7892` | Fuzzy recovers it. "Exact-match-only would fail here" |
| 11 | Route on map - `GJ03CJ6081` | The 153 km/h leg, **flagged not dropped** |
| 11a | Route - `GJ18DH2745` | A different journey. Proves it is not a fixed animation |
| 12 | Dashboard → Export | XLSX + PDF, then open the PDF |
| 13 | Terminal, audit | Actor, purpose, case reference |
| **14** | **Evidence images** | **The strongest 30 seconds - see below** |
| 15 | MEASUREMENTS §5a table | Optional. The 80,000-camera answer |

## Shot 14 - say this slowly

The full wording is in DEMO_SCRIPTS.md. The shape of it:

> We scouted all thirty cameras. Twenty-nine are wide-area overviews where a
> plate is five to fifteen pixels, and on those our pipeline reads nothing -
> every candidate is roadside signage, and our Indian-plate validator correctly
> rejects all of them. But camera twelve is a toll plaza. Vehicles stop, plates
> face the camera. There the same pipeline found a real truck plate twenty-five
> times in a hundred seconds and recovered eight of its ten characters. It still
> fails validation, because the plate is five pixels per character and upscaling
> cannot restore detail the sensor never captured.
>
> **That is the finding: the limit is optics, not software.** The department
> already has cameras in the right places. Toll plazas and checkposts are where
> statewide ANPR should go first.

If you have 20 more seconds, add the live confirmation (MEASUREMENTS §2h):

> On the ninth, with the gateway restored, the indexer produced its first two
> live reads from that toll plaza. Both at six and a half pixels per character.
> They disagreed with each other on the third character, and both were eight
> characters - not a valid Indian format. The platform flagged both as partial
> and raised no alert on either. That guard is the difference between a system
> that is honest about what it cannot see and one that puts a wrong registration
> in front of an officer.

## Recording

- **Win + G** → Xbox Game Bar → record. Or OBS if you want a webcam corner.
- One take. Small stumbles are fine; judges are scoring the software.
- Aim 4-5 minutes. No hard limit on this one.

## After

- [ ] Upload **Unlisted** on YouTube - *not* Private, evaluators cannot open Private
- [ ] Or Drive/OneDrive → **Anyone with the link - Viewer**
- [ ] **Open the link in an incognito window** before pasting it anywhere
- [ ] Paste into `README.md` and the portal form
