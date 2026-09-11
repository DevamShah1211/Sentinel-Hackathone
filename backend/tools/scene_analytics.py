"""
Run vehicle / person / object detection over camera feeds and index the counts.

    # One camera from the sandbox, two minutes
    python tools/scene_analytics.py --camera cam10 --seconds 120

    # A local file — the own-feed demonstration
    python tools/scene_analytics.py --source sample_feeds/own_feed_demo.mp4

    # Annotated frames for the demo video
    python tools/scene_analytics.py --camera cam10 --seconds 60 --save-frames out/

This is the analytics tier that works where ANPR does not. The sweep in
MEASUREMENTS section 2g found no camera on the government grid produces a
readable plate — the plates are 4 to 14 pixels per character against the 20-30
ANPR needs — while the same frames contain cars, motorcycles, auto-rickshaws and
pedestrians that a detector resolves comfortably at 66 ms per frame on CPU.

A deployment that reported only plate reads would report nothing at all from
these cameras. That is the argument for this tier, and it is measured rather
than asserted.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import onnxruntime as ort  # noqa: E402

ort.set_default_logger_severity(4)

from app.object_detection import (  # noqa: E402
    ObjectDetector, SceneAggregator, summarise,
)
from app.settings import settings  # noqa: E402
from app.vision import frame_is_decodable, frame_is_smeared  # noqa: E402
from tools.api_auth import authenticated_session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("scene")

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")

# Colours per category, matching the map legend so a reviewer sees one scheme
# across the platform rather than two.
BOX_COLOURS = {
    "vehicle": (229, 135, 57),    # blue  (BGR)
    "person":  (129, 81, 213),    # magenta
}


def stream_url(camera: str) -> str:
    """The sandbox RTSP URL for a camera, with credentials from local settings."""
    from urllib.parse import quote
    auth = ""
    if settings.sentinel_user_email and settings.sentinel_user_password:
        auth = (f"{quote(settings.sentinel_user_email, safe='')}:"
                f"{quote(settings.sentinel_user_password, safe='')}@")
    return (f"rtsp://{auth}{settings.sentinel_ip}:{settings.sentinel_rtsp_port}"
            f"/stream/{camera}")


def annotate(frame, detections) -> None:
    """Draw boxes in place, for the demonstration video."""
    for d in detections:
        x1, y1, x2, y2 = d.bbox
        colour = BOX_COLOURS.get(d.category, (200, 200, 200))
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
        label = f"{d.label} {d.confidence:.2f}"
        cv2.putText(frame, label, (x1, max(18, y1 - 7)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2)


def run(source: str, camera_native_id: str | None, seconds: int, stride: int,
        save_frames: Path | None, publish: bool) -> int:
    # Load the detector BEFORE opening the stream. The ONNX session is 114 MB
    # and takes about a second cold; opening the capture first left an RTSP
    # connection idle across that window, and the sandbox gateway drops idle
    # connections — the tool then read zero frames from a stream a direct probe
    # showed delivering 15 of 15. The symptom looked like a dead camera and was
    # really a self-inflicted stall.
    detector = ObjectDetector()

    capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    if not capture.isOpened():
        print(f"Could not open {source}", file=sys.stderr)
        return 1

    aggregator = SceneAggregator(bucket_seconds=60)
    api = authenticated_session(API_BASE) if publish else None
    if publish and api is None:
        print("Continuing without publishing — counts will be printed only.\n")

    buckets: list[dict] = []
    frames = analysed = corrupted = 0
    started = time.time()
    inference_seconds = 0.0
    warmup_seconds = 0.0
    if save_frames:
        save_frames.mkdir(parents=True, exist_ok=True)

    print(f"Analysing {camera_native_id or source} for {seconds}s "
          f"(every {stride} frames)\n")

    try:
        while time.time() - started < seconds:
            ok, frame = capture.read()
            if not ok:
                break
            frames += 1
            if frames % stride:
                continue

            # RTSP packet loss leaves frames that decoded into artefacts rather
            # than picture: flat pre-IDR output, or the vertical streaking a lost
            # macroblock row drags down the image. On cam14 the detector found
            # three cars on the clean right of a frame and none of the eight
            # autos macroblocked on the left. Running on such a frame does not
            # produce a wrong count so much as a quietly low one, so the frame
            # is skipped and the skip is counted — it is not a sampled frame.
            if not frame_is_decodable(frame) or frame_is_smeared(frame):
                corrupted += 1
                continue

            t0 = time.time()
            detections = detector.detect(frame)
            elapsed = time.time() - t0
            analysed += 1
            # The first call loads a 114 MB ONNX session — about 1.3 s on this
            # machine — and folding that into the mean makes a short run look
            # four times slower than the steady state it will actually run at.
            # Counted separately rather than hidden, because on a run of thirty
            # frames the load is a real cost and worth seeing.
            if analysed == 1:
                warmup_seconds = elapsed
            else:
                inference_seconds += elapsed

            closed = aggregator.add(detections, time.time())
            if closed:
                buckets.append(closed)

            if detections:
                counts = summarise(detections)["category"]
                shown = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                print(f"  frame {frames:5d}  {shown}")
                if save_frames:
                    annotate(frame, detections)
                    cv2.imwrite(str(save_frames / f"frame_{frames:06d}.jpg"), frame)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        capture.release()

    final = aggregator.flush()
    if final:
        buckets.append(final)

    print(f"\n{analysed} frames analysed from {frames} read"
          + (f", {corrupted} skipped as undecodable" if corrupted else ""))
    if analysed > 1:
        print(f"mean inference: {inference_seconds / (analysed - 1) * 1000:.0f} "
              f"ms/frame steady state "
              f"(model load: {warmup_seconds * 1000:.0f} ms, once)")
    elif analysed:
        print(f"one frame in {warmup_seconds * 1000:.0f} ms, "
              f"including the model load")
    print(f"{len(buckets)} minute bucket(s)")

    for bucket in buckets:
        stamp = datetime.fromtimestamp(bucket["bucket_start"], timezone.utc)
        by_category = bucket["counts_by_category"] or {"nothing": 0}
        shown = ", ".join(f"{k}: {v}" for k, v in sorted(by_category.items()))
        print(f"  {stamp:%H:%M} UTC  {bucket['frames_sampled']:3d} frames  "
              f"peak {shown}")

    if api and camera_native_id and buckets:
        published = 0
        for bucket in buckets:
            payload = dict(bucket)
            payload["camera_native_id"] = camera_native_id
            payload["bucket_start"] = datetime.fromtimestamp(
                bucket["bucket_start"], timezone.utc).isoformat()
            try:
                response = api.post(f"{API_BASE}/analytics/scene", json=payload,
                                    timeout=20)
                if response.ok:
                    published += 1
            except Exception as exc:
                logger.debug("publish failed: %s", exc)
        print(f"\npublished {published}/{len(buckets)} bucket(s) to the index")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vehicle, person and object detection over a camera feed")
    parser.add_argument("--camera", help="Sandbox camera id, e.g. cam10")
    parser.add_argument("--source", help="RTSP URL or a local video file")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--stride", type=int, default=15,
                        help="Analyse every Nth frame; 15 is ~2/s at 30fps")
    parser.add_argument("--save-frames", type=Path,
                        help="Write annotated frames here, for the demo video")
    parser.add_argument("--no-publish", action="store_true",
                        help="Print counts without writing them to the index")
    args = parser.parse_args()

    if not args.camera and not args.source:
        parser.error("give --camera or --source")

    source = args.source or stream_url(args.camera)
    return run(source, args.camera, args.seconds, args.stride,
               args.save_frames, publish=not args.no_publish)


if __name__ == "__main__":
    raise SystemExit(main())
