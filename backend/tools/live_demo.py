"""
Recognise a real plate, live, in front of a jury.

    # 1. Check the feed is readable BEFORE you present (do this at the venue)
    python tools/live_demo.py --source "rtsp://192.168.1.42:8554/live" --check

    # 2. Arm the watchlist with the plate you are about to show
    python tools/live_demo.py --source "..." --arm GJ01AB1234

    # 3. Run it. Plates appear in the platform as they are recognised.
    python tools/live_demo.py --source "rtsp://192.168.1.42:8554/live"

Why this exists, and why it does not use the government feed.

Measured on the sandbox: cam12 (a toll plaza) gives about 5 pixels per plate
character and cam14 (a red-light camera) about 10. Neither is enough — the
pipeline reads eight of ten characters and the grammar correctly refuses them.
The synthetic clip, at 15-20 px per character, reads 6/6. The limitation is the
optics of cameras sited for wide-area observation, not the recogniser, and no
amount of preparation on the day changes what those sensors captured.

The playbook anticipates exactly this and asks for **your own feed** for the
demonstration: "a phone video of a road with a readable plate is fine,
restreamed as RTSP". A phone held at the roadside puts 40+ pixels per character
in frame, which is comfortably above what the pipeline needs.

So this runs the *identical* production pipeline — same detector, same tiled
inference, same track-level voting, same Indian plate grammar, same watchlist
matching — against a feed you control. Nothing is faked and nothing is
special-cased: the only difference from the sandbox is the camera.

`--check` is the important one. Run it at the venue, on the venue's network,
before you are standing in front of anyone. It reports pixels per character,
which is the number that decides whether the demonstration will work.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import requests  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import onnxruntime as ort  # noqa: E402

ort.set_default_logger_severity(4)

from app.plate_grammar import correct_plate, plausible_plate  # noqa: E402
from app.settings import settings  # noqa: E402
from app.vision import (  # noqa: E402
    PlateDetector, TrackManager, aggregate_track, frame_is_decodable,
)

API_BASE = "http://127.0.0.1:8000/api/v1"
CAMERA_ID = "demo-live"

# Below this, the read will not be reliable. Measured: 5 px/char (cam12) and
# 10 px/char (cam14) both fail; 15-20 px/char reads 6/6.
MIN_PX_PER_CHAR = 14.0


def open_source(source: str) -> cv2.VideoCapture:
    """A device index, a file path, or any URL OpenCV can open."""
    if source.isdigit():
        return cv2.VideoCapture(int(source), cv2.CAP_DSHOW)
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG)


def check(source: str, seconds: int) -> int:
    """
    Report whether this feed can actually support recognition.

    Run this at the venue before presenting. It answers the only question that
    matters: are there enough pixels on the plate?
    """
    capture = open_source(source)
    if not capture.isOpened():
        print(f"FAIL: could not open {source}", file=sys.stderr)
        print("  If this is a phone stream, check the phone and laptop are on the",
              file=sys.stderr)
        print("  same network and that the URL matches the app exactly.", file=sys.stderr)
        return 1

    detector = PlateDetector(tiled=True)
    frames = usable = 0
    widths: list[float] = []
    reads: list[tuple[str, str, bool]] = []
    started = time.time()

    print(f"Reading {source} for {seconds}s…")
    while time.time() - started < seconds:
        ok, frame = capture.read()
        if not ok:
            break
        frames += 1
        if frames == 1:
            print(f"  frame size: {frame.shape[1]}x{frame.shape[0]}")
        if frames % 3:
            continue
        if not frame_is_decodable(frame):
            continue
        usable += 1
        for det in detector.detect(frame):
            if not det.text:
                continue
            x1, _, x2, _ = det.bbox
            per_char = (x2 - x1) / max(len(det.text), 1)
            widths.append(per_char)
            result = correct_plate(det.text)
            reads.append((det.text, result.text, result.valid and result.state_valid))
    capture.release()

    print(f"\nframes={frames} usable={usable} detections={len(widths)}")
    if not widths:
        print("\nNo plate was detected at all.")
        print("Move closer, or point the camera where vehicles slow down or stop.")
        return 1

    widths.sort()
    median = widths[len(widths) // 2]
    valid = sum(1 for _, _, ok in reads if ok)
    print(f"pixels per character: min={min(widths):.1f} "
          f"median={median:.1f} max={max(widths):.1f}")
    print(f"reads passing full validation: {valid}/{len(reads)}")
    for raw, corrected, ok in reads[:8]:
        print(f"  {raw:14} -> {corrected:14} {'VALID' if ok else ''}")

    print()
    if valid:
        print("READY. This feed produces validated plates. Use it.")
        return 0
    if median >= MIN_PX_PER_CHAR:
        print(f"MARGINAL. {median:.0f} px per character is enough in principle, but no")
        print("read passed validation in this window. Try steadier framing, better")
        print("light, or a more front-on angle.")
        return 1
    print(f"TOO FAR. {median:.0f} px per character; about {MIN_PX_PER_CHAR:.0f} is needed.")
    print("Get closer to the vehicle, or zoom in so the plate fills more of the frame.")
    return 1


def register(api_base: str, source: str) -> bool:
    """Register the demo feed as a camera so sightings have somewhere to land."""
    try:
        existing = requests.get(f"{api_base}/cameras",
                                params={"limit": 200}, timeout=15).json()
        if any(c.get("native_id") == CAMERA_ID for c in existing):
            return True
    except requests.RequestException:
        pass

    try:
        response = requests.post(
            f"{api_base}/cameras",
            json={
                "native_id": CAMERA_ID,
                "name": "Live demonstration feed",
                "department": "Demonstration",
                "source_system": "Own feed (presenter device)",
                "rtsp_url": source,
                "status": "live",
                # Gandhinagar, so the sighting lands somewhere sensible on the map.
                "latitude": 23.2156,
                "longitude": 72.6369,
                "address": "Live demonstration feed",
            },
            timeout=20,
        )
        if response.status_code in (200, 201):
            print(f"Registered camera '{CAMERA_ID}'.")
            return True
        print(f"Could not register the camera: {response.status_code} {response.text[:200]}",
              file=sys.stderr)
    except requests.RequestException as exc:
        print(f"Could not register the camera: {exc}", file=sys.stderr)
    return False


def arm(api_base: str, plate: str) -> None:
    """Put a plate on the watchlist so recognising it raises a visible alert."""
    try:
        response = requests.post(
            f"{api_base}/watchlist",
            json={
                "plate_text": plate.upper().strip(),
                "entity_type": "vehicle",
                "reason": "wanted",
                "severity": "high",
                "case_ref": "DEMO/2026/LIVE",
                "description": "Armed for the live demonstration",
                "added_by": "presenter",
            },
            timeout=20,
        )
        if response.status_code in (200, 201):
            print(f"Watchlist armed for {plate.upper()}. Recognising it will raise an alert.")
        else:
            print(f"Could not arm the watchlist: {response.status_code} {response.text[:200]}",
                  file=sys.stderr)
    except requests.RequestException as exc:
        print(f"Could not arm the watchlist: {exc}", file=sys.stderr)


def publish(api_base: str, plate: str, confidence: float, grammar, reads, crop) -> bool:
    """Write one recognised plate into the platform."""
    crop_uri = None
    if crop is not None and getattr(crop, "size", 0):
        evidence = Path(settings.evidence_crop_dir)
        evidence.mkdir(parents=True, exist_ok=True)
        name = f"{CAMERA_ID}_{plate}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}.jpg"
        try:
            cv2.imwrite(str(evidence / name), crop)
            crop_uri = f"/evidence/{name}"
        except cv2.error:
            pass

    try:
        response = requests.post(
            f"{api_base}/detections",
            json={
                "camera_native_id": CAMERA_ID,
                "plate_text": plate,
                "confidence": round(confidence, 4),
                "track_id": f"{CAMERA_ID}-{plate}-{int(time.time())}",
                "crop_uri": crop_uri,
                "raw_reads": [{"plate": r.text, "conf": round(r.mean_confidence, 4)}
                              for r in reads[:20]],
                "plate_format": grammar.fmt,
                "grammar_corrections": grammar.corrections,
            },
            timeout=25,
        )
        response.raise_for_status()
        return bool(response.json().get("alert_created"))
    except requests.RequestException as exc:
        print(f"  could not publish: {exc}", file=sys.stderr)
        return False


def run(source: str, api_base: str, seconds: int, min_confidence: float) -> int:
    if not register(api_base, source):
        print("Continuing anyway; sightings may fail to publish.", file=sys.stderr)

    capture = open_source(source)
    if not capture.isOpened():
        print(f"Could not open {source}", file=sys.stderr)
        return 1

    detector = PlateDetector(tiled=True)
    tracks = TrackManager(min_reads=2)
    seen: set[str] = set()
    frames = 0
    started = time.time()

    print("\nRunning. Recognised plates appear in the platform as they are read.")
    print("Ctrl-C to stop.\n")

    def harvest(index: int, force: bool = False) -> None:
        for track in tracks.collect_finished(index, force=force):
            voted = aggregate_track(track)
            if voted is None:
                continue
            plate, confidence, grammar = voted
            if (confidence < min_confidence or not grammar.valid
                    or not grammar.state_valid or not plausible_plate(plate)):
                continue
            if plate in seen:
                continue
            seen.add(plate)
            alerted = publish(api_base, plate, confidence, grammar, track.reads,
                              track.best_crop)
            stamp = datetime.now().strftime("%H:%M:%S")
            flag = "  *** WATCHLIST ALERT ***" if alerted else ""
            print(f"[{stamp}]  {plate}   {confidence * 100:.0f}%   "
                  f"{len(track.reads)} reads{flag}")

    try:
        while seconds <= 0 or time.time() - started < seconds:
            ok, frame = capture.read()
            if not ok:
                break
            frames += 1
            if frames % 3:
                continue
            if not frame_is_decodable(frame):
                continue
            tracks.update(detector.detect(frame), frames, frames * 40, frame)
            harvest(frames)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        harvest(frames + 10_000, force=True)
        capture.release()

    print(f"\n{len(seen)} distinct plate(s) recognised: {', '.join(sorted(seen)) or 'none'}")
    print("Open Plate Search and search any of them to show the sighting and route.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recognise real plates live from your own feed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument("--source", required=True,
                        help="RTSP/HTTP URL, a video file, or a webcam index such as 0")
    parser.add_argument("--check", action="store_true",
                        help="Assess the feed and exit. Run this at the venue first.")
    parser.add_argument("--arm", metavar="PLATE",
                        help="Put this plate on the watchlist, then exit")
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--seconds", type=int, default=0,
                        help="Stop after N seconds (0 = run until Ctrl-C)")
    parser.add_argument("--min-confidence", type=float, default=0.45)
    args = parser.parse_args()

    if args.arm:
        arm(args.api_base, args.arm)
        return 0
    if args.check:
        return check(args.source, args.seconds or 25)
    return run(args.source, args.api_base, args.seconds, args.min_confidence)


if __name__ == "__main__":
    raise SystemExit(main())
