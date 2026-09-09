"""
Seed several distinct vehicle journeys for the demonstration.

    python tools/seed_demo_route.py            # seed on top of what is there
    python tools/seed_demo_route.py --reset    # clear the index first

Each vehicle gets its OWN route: different cameras, different times, different
speeds. An earlier version replayed the whole clip at every camera, which meant
every plate appeared at every camera at the same instant — so every search
returned an identical route, which is obviously wrong the moment you search a
second plate.

The clip is decoded **once**. An earlier version spawned a subprocess per leg,
which reloaded the ONNX models and re-decoded the whole video nineteen times;
that took long enough that the run was usually killed before it finished, leaving
only the first vehicle in the index. Now the pipeline runs once, the reads are
grouped by plate, and each vehicle's journey is written from its own best read.

Timings come from the real distances between these cameras, giving ordinary city
speeds of roughly 20-55 km/h. One journey deliberately ends with an
Ahmedabad-to-Rajkot leg minutes later: physically impossible, and the platform
flags it rather than hiding it, which is the behaviour worth demonstrating.

Every plate written is read by the real detector and OCR from the clip. Only the
timestamp and the camera are supplied, and only because the footage is a replay
rather than a live feed.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.api_auth import authenticate  # noqa: E402

from app.plate_grammar import plausible_in_gujarat  # noqa: E402
from app.settings import settings  # noqa: E402
from app.vision import PlateDetector, TrackManager, aggregate_track  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = BACKEND / "sample_feeds" / "own_feed_demo.mp4"
API_BASE = "http://127.0.0.1:8000/api/v1"
MIN_CONFIDENCE = 0.45
EVIDENCE_DIR = Path(settings.evidence_crop_dir)

# One entry per vehicle. Cameras and minute offsets differ so the reconstructed
# routes are genuinely distinct.
# The watchlist the demonstration runs against.
#
# Seeded here, with the routes, because the two have to agree: an alert can only
# exist for a plate that is both listed and seen. Previously the watchlist held
# one entry, so every alert on the dashboard was the same registration five
# times over — which showed that alerting fires, and nothing about triage.
#
# Varying reason and severity is what makes the alerts page legible: an operator
# reads severity colour before they read text, and a column of identical red
# rows carries no information.
WATCHLIST = [
    {"plate_text": "GJ01KA7392", "reason": "stolen", "severity": "critical",
     "case_ref": "FIR/2026/0912", "entity_type": "vehicle",
     "description": "Reported stolen from Navrangpura on 6 September. "
                    "Tracked across the city centre."},
    {"plate_text": "GJ18DH2745", "reason": "wanted", "severity": "high",
     "case_ref": "FIR/2026/0884", "entity_type": "vehicle",
     "description": "Vehicle sought in connection with an ongoing enquiry."},
    {"plate_text": "MH12QP5837", "reason": "suspicious", "severity": "medium",
     "case_ref": "INT/2026/0271", "entity_type": "vehicle",
     "description": "Out-of-state vehicle flagged for repeated night transits."},
    {"plate_text": "GJ03CJ6081", "reason": "suspicious", "severity": "high",
     "case_ref": "INT/2026/0318", "entity_type": "vehicle",
     "description": "Cloned registration suspected — the same plate was recorded "
                    "in Rajkot and Ahmedabad within the hour."},
    {"plate_text": "RJ14SL3926", "reason": "blacklisted", "severity": "low",
     "case_ref": "TRF/2026/1190", "entity_type": "vehicle",
     "description": "Commercial permit lapsed; stop and verify documentation."},
]


JOURNEYS = [
    # Timings are set against the real distances between these cameras, so every
    # speed the route view computes is one a vehicle could actually have driven.
    # Ahmedabad city legs sit at 24-32 km/h, ordinary for that traffic.
    #
    # Only ONE journey contains an impossible transition, and it is not the
    # headline vehicle. Two earlier versions got this wrong in the same way:
    # they gave the stolen car a route ending in a flagged 153 km/h, then 404
    # km/h, on the theory that a bigger number demonstrates the check better.
    #
    # It demonstrates the opposite. Route reconstruction is the feature being
    # shown, and its demonstration should be a journey that makes sense — a
    # stolen car moving through the city, which is what an operator sees on
    # almost every real query. Ending the flagship route in an absurd number
    # makes the whole panel read as broken data, and it wastes the one route a
    # reviewer is most likely to open.
    #
    # The impossible-transition check gets its own vehicle, below, where the
    # story is legible: a plate seen twice in Rajkot and then in Ahmedabad
    # inside the hour is not a fast car, it is two cars wearing one plate.
    {
        "plate": "GJ01KA7392",
        "note": "Stolen vehicle tracked across the city — a clean, plausible route",
        "legs": [
            ("cam01", 0),    # Chimanbhai Bridge
            ("cam14", 5),    # Delight RLVD        2.0 km road   23 km/h
            ("cam04", 17),   # Paldi Circle        6.3 km        32 km/h
            ("cam13", 26),   # C N Vidyalaya       4.0 km        27 km/h
            ("cam02", 34),   # Janpath, Ashram Road 3.6 km       27 km/h
        ],
    },
    {
        # The cloned-plate case, kept separate so it is read as a finding rather
        # than as a fault in the data.
        #
        # Two sightings in Rajkot eighteen minutes apart — an ordinary local
        # trip. Then the same registration in Ahmedabad, 197 km away, 77
        # minutes later. That leg implies about 150 km/h sustained on the
        # NH-47, which the drive does not permit: it is 3.3 to 4.4 hours at
        # legal speeds. The Rajkot pair is what makes it unambiguous — a single
        # distant sighting could be a misread, but a vehicle demonstrably
        # working in Rajkot cannot also be in Ahmedabad.
        "plate": "GJ03CJ6081",
        "note": "Same plate in two districts within the hour — cloned registration",
        "legs": [
            ("cam17", 0),    # Rajkot Bus Port
            ("cam18", 18),   # Rajkot CCTV          9.7 km       32 km/h
            ("cam13", 95),   # C N Vidyalaya, Ahmedabad — 197 km in 77 min
        ],
    },
    {
        "plate": "GJ18DH2745",
        "note": "Northbound out of the city towards Gandhinagar",
        "legs": [
            ("cam04", 8),    # Paldi Circle
            ("cam02", 14),   # Janpath, Ashram Road   3.1 km   31 km/h
            ("cam05", 33),   # Visat Teen Rasta      10.2 km   32 km/h
            ("cam12", 51),   # Adalaj Toll Naka       9.3 km   31 km/h
        ],
    },
    {
        "plate": "MH12QP5837",
        "note": "Out-of-state vehicle crossing the city",
        "legs": [
            ("cam15", 3),    # Suvidha Park
            ("cam13", 18),   # C N Vidyalaya       7.2 km   29 km/h
            ("cam14", 29),   # Delight RLVD        5.5 km   30 km/h
            ("cam03", 47),   # ONGC, Chandkheda    7.8 km   26 km/h
        ],
    },
    {
        "plate": "GJ27BG4108",
        "note": "Two sightings only — a vehicle that left the covered area",
        "legs": [
            ("cam16", 12),   # Visat P2
            ("cam05", 14),   # Visat Teen Rasta    0.3 km   9 km/h (adjacent junction)
        ],
    },
    {
        "plate": "RJ14SL3926",
        "note": "Northern corridor, inbound from the toll plaza",
        "legs": [
            ("cam12", 5),    # Adalaj Toll Naka
            ("cam05", 24),   # Visat Teen Rasta    9.3 km   29 km/h
            ("cam01", 36),   # Chimanbhai Bridge   6.0 km   30 km/h
        ],
    },
]


def read_clip(video: Path, stride: int = 3) -> dict[str, dict]:
    """
    Run the real pipeline over the clip once and return the best read per plate.

    Returns {plate: {"confidence": float, "reads": [...], "grammar": PlateResult,
                     "crop": ndarray|None}}.
    """
    detector = PlateDetector(tiled=True)
    tracks = TrackManager(min_reads=2)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"Could not open {video}")

    best: dict[str, dict] = {}

    def harvest(force: bool = False, frame_index: int = 0) -> None:
        for track in tracks.collect_finished(frame_index, force=force):
            voted = aggregate_track(track)
            if voted is None:
                continue
            plate, confidence, grammar = voted
            if (confidence < MIN_CONFIDENCE or not grammar.valid
                    or not grammar.state_valid or not plausible_in_gujarat(plate)):
                continue
            # Keep the most confident read of each plate; the clip shows each
            # vehicle once, so this is that vehicle's best evidence.
            if plate not in best or confidence > best[plate]["confidence"]:
                best[plate] = {
                    "confidence": confidence,
                    "reads": track.reads,
                    "grammar": grammar,
                    "crop": track.best_crop,
                }

    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_index += 1
        if frame_index % stride:
            continue
        tracks.update(detector.detect(frame), frame_index, frame_index * 40, frame)
        harvest(frame_index=frame_index)
    harvest(force=True, frame_index=frame_index)
    capture.release()
    return best


def save_crop(crop, plate: str, camera: str) -> str | None:
    """Write the evidence crop for one sighting."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{camera}_{plate}_{stamp}.jpg"
    try:
        height, width = crop.shape[:2]
        if 0 < width < 240:
            scale = 240 / width
            crop = cv2.resize(crop, (int(width * scale), int(height * scale)),
                              interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(EVIDENCE_DIR / filename), crop)
        return f"/evidence/{filename}"
    except cv2.error:
        return None


def post(session: requests.Session, api_base: str, camera: str, plate: str,
         record: dict, stamp: datetime, leg_index: int) -> tuple[bool, bool]:
    """Write one sighting. Returns (written, alert_raised)."""
    grammar = record["grammar"]
    try:
        response = session.post(
            f"{api_base}/detections",
            json={
                "camera_native_id": camera,
                "plate_text": plate,
                "confidence": record["confidence"],
                "pts_ms": leg_index * 1000,
                "track_id": f"{camera}-{plate}-{leg_index}",
                "crop_uri": record.get("crop_uri"),
                "raw_reads": [{"plate": r.text, "conf": round(r.mean_confidence, 4)}
                              for r in record["reads"][:20]],
                "plate_format": grammar.fmt,
                "grammar_corrections": grammar.corrections,
                "detected_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            timeout=25,
        )
        response.raise_for_status()
        return True, bool(response.json().get("alert_created"))
    except requests.RequestException as exc:
        print(f"    POST failed: {exc}", file=sys.stderr)
        return False, False


def reset_index(api_base: str) -> None:
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def clear() -> None:
        from sqlalchemy import text

        from app.database import engine
        async with engine.begin() as conn:
            detections = await conn.scalar(text("SELECT count(*) FROM detections"))
            alerts = await conn.scalar(text("SELECT count(*) FROM alerts"))
            await conn.execute(text("DELETE FROM alerts"))
            await conn.execute(text("DELETE FROM detections"))
            print(f"Cleared {detections} detections and {alerts} alerts.")

    asyncio.run(clear())


def seed_watchlist(session: requests.Session, api_base: str) -> int:
    """
    Put the demonstration plates on the watchlist, skipping any already there.

    Runs before the sightings are posted, because check_and_alert only raises an
    alert for a plate that is already listed when the detection arrives.
    """
    try:
        existing = {e.get("plate_text") for e in
                    session.get(f"{api_base}/watchlist", timeout=20).json()}
    except (requests.RequestException, ValueError):
        existing = set()

    added = 0
    for entry in WATCHLIST:
        if entry["plate_text"] in existing:
            continue
        try:
            response = session.post(f"{api_base}/watchlist", json=entry, timeout=20)
            if response.ok:
                added += 1
        except requests.RequestException:
            pass
    print(f"Watchlist: {added} added, {len(existing)} already present.")
    print()
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed distinct demonstration journeys")
    parser.add_argument("--video", default=str(DEFAULT_VIDEO))
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--reset", action="store_true",
                        help="Clear the detection index before seeding")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"No such video: {video}\n"
              f"Generate one with: python tools/make_sample_feed.py", file=sys.stderr)
        return 1

    if args.reset:
        reset_index(args.api_base)

    print(f"Reading {video.name} through the ANPR pipeline…")
    best = read_clip(video)
    if not best:
        print("No plates were read from the clip.", file=sys.stderr)
        return 1
    print(f"Recognised {len(best)} plates: {', '.join(sorted(best))}\n")

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    session = requests.Session()
    # Detection ingest is authenticated: the index is the evidentiary record.
    if not authenticate(session, args.api_base):
        return 1
    seed_watchlist(session, args.api_base)

    written = alerts = 0
    missing: list[str] = []

    for journey in JOURNEYS:
        plate = journey["plate"]
        record = best.get(plate)
        if record is None:
            missing.append(plate)
            print(f"{plate} — not recognised in this clip, skipping")
            continue

        print(f"{plate} — {journey['note']}")
        # One crop per plate is enough; every sighting is the same vehicle.
        record.setdefault("crop_uri",
                          save_crop(record.get("crop"), plate, journey["legs"][0][0]))

        for leg_index, (camera, minutes) in enumerate(journey["legs"]):
            stamp = start + timedelta(minutes=minutes)
            ok, alerted = post(session, args.api_base, camera, plate, record,
                               stamp, leg_index)
            written += ok
            alerts += alerted
            marker = "alert" if alerted else ("ok" if ok else "FAILED")
            print(f"    {camera} at +{minutes:>2} min — {marker}")

    print(f"\n{written} sightings written, {alerts} watchlist alerts raised.")
    if missing:
        print(f"Not found in the clip: {', '.join(missing)}")
    print("\nSearch any plate and choose 'Show Route on Map' — each returns its own")
    print("route. GJ01KA7392 is a clean city route; GJ03CJ6081 is the cloned")
    print("plate — Rajkot twice, then Ahmedabad 197 km away 77 minutes later.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
