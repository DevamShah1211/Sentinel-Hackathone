"""
Run the real ANPR pipeline over a video file and write its results to the index.

This exists for the own-feed demonstration the playbook asks for (Video 1): point
it at your own footage — a phone video of a road with readable plates is ideal —
and it performs the same work the live indexer does, through the same code path,
writing real detections to the same API.

    # your own footage, attributed to a camera in the registry
    python tools/demo_seed.py --video my_road_video.mp4 --camera cam01

    # the synthetic validation clip, if no footage is to hand
    python tools/make_sample_feed.py
    python tools/demo_seed.py --video sample_feeds/own_feed_demo.mp4 --camera cam01

Nothing here fabricates a detection. Every plate written to the index was read by
the detector and OCR from a frame of the video supplied, aggregated across a
track and validated against Indian plate grammar, exactly as it would be from a
live feed. The only difference is the frame source.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from app.vision import PlateDetector, TrackManager, aggregate_track  # noqa: E402

logger = logging.getLogger("sentinel.demo_seed")

API_BASE = "http://127.0.0.1:8000/api/v1"
MIN_CONFIDENCE = 0.45
EVIDENCE_DIR = Path(settings.evidence_crop_dir)


def save_evidence_crop(crop, plate: str, camera: str) -> str | None:
    """Write a track's best plate crop to disk and return the path it is served on."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{camera}_{plate}_{stamp}.jpg"
    try:
        # Upscale small crops so the evidence image is legible in the UI and in
        # the report rather than a handful of pixels.
        height, width = crop.shape[:2]
        if width < 240 and width > 0:
            scale = 240 / width
            crop = cv2.resize(crop, (int(width * scale), int(height * scale)),
                              interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(EVIDENCE_DIR / filename), crop)
        return f"/evidence/{filename}"
    except cv2.error as exc:
        logger.debug("Could not write crop: %s", exc)
        return None


def post_detection(api_base: str, camera_native_id: str, plate: str,
                   confidence: float, pts_ms: int, track_id: str,
                   reads: list, grammar, crop_uri: str | None = None,
                   detected_at: str | None = None) -> bool:
    try:
        response = requests.post(
            f"{api_base}/detections",
            json={
                "camera_native_id": camera_native_id,
                "plate_text": plate,
                "confidence": confidence,
                "pts_ms": pts_ms,
                "track_id": track_id,
                "crop_uri": crop_uri,
                "vehicle_type": None,
                "raw_reads": [{"plate": r.text, "conf": round(r.mean_confidence, 4)}
                              for r in reads[:20]],
                "plate_format": grammar.fmt,
                "grammar_corrections": grammar.corrections,
                **({"detected_at": detected_at} if detected_at else {}),
            },
            timeout=15,
        )
        response.raise_for_status()
        return bool(response.json().get("alert_created"))
    except requests.RequestException as exc:
        logger.error("Could not post %s: %s", plate, exc)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a video file through the ANPR pipeline")
    parser.add_argument("--video", required=True, help="Path to the video file")
    parser.add_argument("--camera", required=True,
                        help="native_id of the camera to attribute detections to")
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--stride", type=int, default=3,
                        help="Run inference on every Nth frame")
    parser.add_argument("--no-tiling", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be indexed without writing")
    parser.add_argument("--loop", type=int, default=1,
                        help="Process the clip this many times (for a longer demo)")
    parser.add_argument("--only-plate", action="append", dest="only_plates",
                        help="Index only this plate from the clip (repeatable). "
                             "Used when seeding several vehicles onto different "
                             "routes from one recording, so each gets its own "
                             "journey rather than every plate appearing at every "
                             "camera.")
    parser.add_argument("--detected-at", default=None,
                        help="ISO-8601 UTC time to record these sightings at. Use when "
                             "seeding a route across several cameras so the intervals "
                             "between them are realistic for the distances involved.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    video_path = Path(args.video)
    if not video_path.exists():
        logger.error("No such video: %s", video_path)
        return 1

    detector = PlateDetector(tiled=not args.no_tiling)
    indexed = alerts = rejected = 0

    for pass_number in range(1, args.loop + 1):
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            logger.error("Could not open %s", video_path)
            return 1

        tracks = TrackManager(min_reads=2)
        frame_index = 0
        # Offset each pass so repeated runs do not collide on timestamps.
        pts_offset = (pass_number - 1) * 10 * 60 * 1000

        def flush(force: bool = False) -> None:
            nonlocal indexed, alerts, rejected
            for track in tracks.collect_finished(frame_index, force=force):
                voted = aggregate_track(track)
                if voted is None:
                    continue
                plate, confidence, grammar = voted
                # Same acceptance criteria as the live indexer: confident enough,
                # a valid Indian format, and a real RTO state code. The last one
                # is what keeps plate-shaped signage out of the index.
                if (confidence < MIN_CONFIDENCE
                        or not grammar.valid
                        or not grammar.state_valid):
                    rejected += 1
                    continue

                # When seeding several vehicles onto separate routes, take only
                # the plate this pass is for.
                if args.only_plates and plate not in args.only_plates:
                    continue

                logger.info("PLATE %s conf=%.2f reads=%d%s", plate, confidence,
                            len(track.reads),
                            " [grammar-corrected]" if grammar.corrections else "")
                indexed += 1
                if not args.dry_run:
                    crop_uri = save_evidence_crop(track.best_crop, plate, args.camera)
                    if post_detection(args.api_base, args.camera, plate, confidence,
                                      pts_offset + track.last_pts_ms,
                                      f"{args.camera}-p{pass_number}-{track.track_id}",
                                      track.reads, grammar, crop_uri,
                                      args.detected_at):
                        alerts += 1
                        logger.warning("*** WATCHLIST ALERT: %s ***", plate)

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index += 1
            if frame_index % args.stride:
                continue
            pts_ms = int(capture.get(cv2.CAP_PROP_POS_MSEC))
            tracks.update(detector.detect(frame), frame_index, pts_ms, frame)
            flush()

        flush(force=True)
        capture.release()
        if args.loop > 1:
            logger.info("Pass %d/%d complete", pass_number, args.loop)
            time.sleep(1)

    print("\n" + "─" * 54)
    print(f"  video          : {video_path.name}")
    print(f"  camera         : {args.camera}")
    print(f"  plates indexed : {indexed}{'  (dry run — nothing written)' if args.dry_run else ''}")
    print(f"  alerts raised  : {alerts}")
    print(f"  rejected       : {rejected} (low confidence or invalid format)")
    print("─" * 54 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
