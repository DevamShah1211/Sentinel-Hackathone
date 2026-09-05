# Submission checklist

Evaluation area 7 is submission completeness, and it is the easiest one to lose
for no reason at all. Run this on Sunday morning with two people, out loud.

**Deadline: Sunday 7 September, 14:00.** Portal load on deadline day is real —
aim to submit by noon.

---

## Still to do — owner and status

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Record own-feed video (2–3 min) | | ☐ |
| 2 | Record government-feed video | | ☐ |
| 3 | Export `DOCS/PRESENTATION.md` to PDF | | ☐ |
| 4 | Export `DOCS/HLD.md` to PDF | | ☐ |
| 5 | Deploy a reachable instance | | ☐ |
| 6 | Upload videos, set sharing, test in incognito | | ☐ |
| 7 | Paste all links into `README.md` | | ☐ |
| 8 | Submit the portal form; screenshot the confirmation | | ☐ |

Scripts for 1 and 2 are in [`DEMO_SCRIPTS.md`](DEMO_SCRIPTS.md), shot by shot.

---

## Done and verifiable

Every line here can be re-checked with the command beside it.

| Artefact | Where | Verify |
|---|---|---|
| Working platform | `backend/`, `frontend/` | `docker compose up -d --build` |
| Output report, XLSX + PDF | `submission/` | Open them; 62 detections, 6 plates, 8 cameras |
| Camera registry, 30 cameras located | Live | `GET /api/v1/ingest/status` |
| Raw sandbox catalogue | `catalogue.json` | Committed |
| Technical proposal / HLD | `DOCS/HLD.md` | Every required section present |
| Presentation content | `DOCS/PRESENTATION.md` | 12 slides with speaker notes |
| Measured performance | `DOCS/MEASUREMENTS.md` | Each figure has its command |
| Test suite | `backend/tests/` | `python -m pytest tests/ -q` → 57 passed |
| Pipeline accuracy | — | `python tools/make_sample_feed.py --validate` → 6/6, 0 false positives |
| Throughput | — | `python anpr_worker.py --benchmark` |
| Role enforcement | — | Viewer token: 403 on audit and search, 200 on cameras |
| Rate limiting | — | 11th login attempt in a minute → 429 |
| Audit trail | Live | `GET /api/v1/analytics/audit` as state admin |
| Test credentials | `README.md` | Three seeded accounts |

---

## Exporting the two documents to PDF

The markdown is written to convert cleanly. Any of these works:

```bash
# Pandoc (best results)
pandoc DOCS/HLD.md -o Sentinel-HLD.pdf --pdf-engine=xelatex -V geometry:margin=2cm
pandoc DOCS/PRESENTATION.md -o Sentinel-Presentation.pdf

# Or: VS Code "Markdown PDF" extension, or paste into Google Docs and export
```

For the deck specifically, `PRESENTATION.md` is written as slide content rather
than as a document — one `##` heading per slide. Paste each section into Google
Slides on a dark background, or run it through Marp. **Check every diagram is
legible at 100% zoom** before exporting.

---

## Deploying a reachable instance

```bash
cp backend/.env.example .env
# Set: SECRET_KEY (a long random string), AUTH_ENABLED=true,
#      SENTINEL_USER_EMAIL, SENTINEL_USER_PASSWORD, DEMO_ADMIN_PASSWORD
docker compose up -d --build
```

Console on `:8080`, API on `:8000`. Any host with Docker and a public address
works — a small cloud VM, or a tunnel (`cloudflared tunnel --url
http://localhost:8080`) if you are demonstrating from a laptop.

**Before handing out the URL:**

- [ ] `AUTH_ENABLED=true`
- [ ] `SECRET_KEY` changed from the default
- [ ] `DEMO_ADMIN_PASSWORD` changed, and the new password written in the
      submission form
- [ ] `CORS_ORIGINS` set to the real origin
- [ ] Open the URL in an incognito window and sign in

---

## Sunday morning, out loud, two people

- [ ] Solution presentation exported to PDF, all required sections present
- [ ] HLD exported to PDF, architecture diagrams legible at 100%
- [ ] Own-feed video, 2–3 minutes, real working software end to end
- [ ] Government-feed video shows onboarding, viewing, analytics, search, route
- [ ] Output report attached, with plates and timestamps
- [ ] Videos **Unlisted** on YouTube (not Private — evaluators cannot open Private)
      or Drive/OneDrive set to **Anyone with the link — Viewer**
- [ ] **Every link opened and verified in an incognito window**
- [ ] Hosted URL live, test credentials written in the submission
- [ ] Repository accessible; README explains how to run it
- [ ] Final read of both documents by someone who did not write them
- [ ] All links pasted into the portal form, and the form actually submitted
- [ ] Confirmation screenshot saved

---

## If something goes wrong on the day

| Problem | What to do |
|---|---|
| Sandbox unreachable | The registry, search, route, reports and audit all work from the index — demonstrate those and say the gateway is down. The video wall degrades to an explanatory tile rather than a black screen. |
| Live viewing slow | The sandbox throttles HTTP under load. Playlists are cached for 4 s; use the 2×2 layout instead of 3×3 in the video. |
| A judge asks why ANPR finds nothing on the grid | Go to `MEASUREMENTS.md` §2a. 165 plate-shaped regions, 87 OCR strings, 0 valid plates, every candidate roadside signage, all correctly rejected. Plates are 5–15 px. The same pipeline is 6/6 on legible footage. **Answer this before they ask it.** |
| **A judge asks "if it struggles at 9 cameras, how do you reach 80,000?"** | `MEASUREMENTS.md` §5a. **Our machine sits at 4% CPU of 20 cores while the gateway takes 73 s to accept the eighth connection.** The limit is the shared ingress, not our compute. 2/2, 4/4 and 6/6 succeed; 8 degrades — a queue, not a load curve. No deployment routes 80,000 cameras through one gateway; ~400 district edge nodes at 200 cameras each is ordinary server load. **This is the 80,000-camera bottleneck reproduced at a scale of eight, and it is the evidence for edge-first.** |
| Tiles are slow to come up during the recording | Expected — the gateway accepts connections nearly serially. Open the wall a minute before recording, use 2×2 or 1×1, and let it settle. |
| Deployment fails on the day | The repository runs locally in three commands, and the videos are already recorded. Say the hosted instance is unavailable and offer the repository. |
