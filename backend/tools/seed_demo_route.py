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
JOURNEYS = [
    {
        "plate": "GJ01AB1234",
        "note": "City centre, then an impossible jump to Rajkot",
        "legs": [
            ("cam01", 0),    # Chimanbhai Bridge
            ("cam14", 6),    # Delight RLVD       ~2.6 km
            ("cam04", 14),   # Paldi Circle       ~4.5 km
            ("cam13", 21),   # C N Vidyalaya      ~3.0 km
            ("cam17", 25),   # Rajkot — 215 km away. Impossible, and flagged.
        ],
    },
    {
        "plate": "GJ18CD5678",
        "note": "Northbound towards Gandhinagar",
        "legs": [
            ("cam04", 8),    # Paldi Circle
            ("cam02", 17),   # Janpath, Ashram Road
            ("cam05", 29),   # Visat Teen Rasta
            ("cam12", 44),   # Adalaj Toll Naka
        ],
    },
    {
        "plate": "MH12DE1433",
        "note": "Out-of-state vehicle crossing the city",
        "legs": [
            ("cam15", 3),    # Suvidha Park
            ("cam13", 15),   # C N Vidyalaya
            ("cam14", 26),   # Delight RLVD
            ("cam03", 40),   # ONGC, Chandkheda
        ],
    },
    {
        "plate": "GJ05JV7219",
        "note": "Short hop, two sightings only",
        "legs": [
            ("cam16", 12),   # Visat P2
            ("cam05", 19),   # Visat Teen Rasta
        ],
    },
    {
        "plate": "RJ14GH9012",
        "note": "Northern corridor",
        "legs": [
            ("cam12", 5),    # Adalaj Toll Naka
            ("cam05", 22),   # Visat Teen Rasta
            ("cam01", 34),   # Chimanbhai Bridge
        ],
    },
    {
        "plate": "GJ27XY4455",
        "note": "Single sighting — a vehicle seen once",
        "legs": [
            ("cam13", 30),   # C N Vidyalaya
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
    print("route. GJ01AB1234 ends with a flagged impossible transition to Rajkot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
