"""
Register a camera from a second, independent system.

Model 2 asks for "a unified viewer connected to sample feeds from at least two
different systems". The Sentinel sandbox is the first. This registers a second —
any ONVIF camera, NVR channel, vendor gateway or public RTSP endpoint — and
demonstrates the point that matters: **nothing above the connector layer knows
where a stream came from.**

No code changes to support it. A camera is a registry row with a stream URL; the
capture layer takes a URL and yields frames. Viewing, ANPR, search, watchlist
matching and reporting all operate on `Camera` and `Detection` rows, so a feed
from a different vendor is indistinguishable downstream.

    # An ONVIF camera on the local network
    python tools/add_external_camera.py \\
        --id DEPT-NVR-07 --name "Ward 3 NVR channel 7" \\
        --rtsp "rtsp://user:pass@10.0.2.40:554/Streaming/Channels/701" \\
        --department "Municipal Corporation" --system "Hikvision NVR (ONVIF)" \\
        --lat 23.0225 --lon 72.5714

    # A public test stream, when no second system is to hand for a demonstration
    python tools/add_external_camera.py --demo-public

The --verify flag opens the stream first and refuses to register a feed that does
not actually decode, so the registry never gains a camera that was never there.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import requests  # noqa: E402

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")

# A well-known public RTSP endpoint, used only when demonstrating that the
# platform ingests a feed from outside the sandbox. Not a government camera and
# not presented as one.
PUBLIC_DEMO = {
    "native_id": "EXT-DEMO-01",
    "name": "External demo feed (public RTSP)",
    "rtsp_url": "rtsp://rtspstream:demo@rtspstream.com/movie",
    "department": "External / Demonstration",
    "system": "Public RTSP test endpoint",
    "lat": None,
    "lon": None,
}


def verify_stream(url: str, timeout_s: float = 25.0) -> tuple[bool, str]:
    """Open the stream and read a frame, so we register only what really works."""
    import time

    started = time.time()
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not capture.isOpened():
        capture.release()
        return False, f"could not open the stream within {time.time() - started:.0f}s"

    frames = 0
    height = width = 0
    while frames < 5 and time.time() - started < timeout_s:
        ok, frame = capture.read()
        if not ok:
            break
        frames += 1
        height, width = frame.shape[:2]
    capture.release()

    if frames == 0:
        return False, "stream opened but delivered no frames"
    return True, f"{frames} frames at {width}x{height} in {time.time() - started:.0f}s"


def register(camera: dict, api_base: str) -> int:
    payload = {
        "native_id": camera["native_id"],
        "name": camera["name"],
        "department": camera.get("department") or "External",
        "lat": camera.get("lat"),
        "lon": camera.get("lon"),
        "address": camera.get("address"),
        "rtsp_url": camera["rtsp_url"],
        "camera_type": camera.get("camera_type") or "external",
        "make": camera.get("make"),
        "model": camera.get("model"),
    }
    try:
        response = requests.post(f"{api_base}/cameras", json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Registration failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nRegistered '{camera['name']}' as {camera['native_id']}")
    print(f"  source system : {camera.get('system', 'external')}")
    print(f"  live view     : {api_base}/cameras/live/{camera['native_id']}")
    print(f"  ANPR          : python anpr_worker.py --camera {camera['native_id']}")
    print("\nThe viewer, search, watchlist and reports treat this camera exactly")
    print("as they treat a sandbox one — no code path distinguishes them.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a camera from a second, independent system")
    parser.add_argument("--id", dest="native_id", help="Registry identifier")
    parser.add_argument("--name")
    parser.add_argument("--rtsp", dest="rtsp_url", help="Full RTSP URL")
    parser.add_argument("--department", default="External")
    parser.add_argument("--system", default="external",
                        help="Which system this feed comes from, for the record")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--address")
    parser.add_argument("--make")
    parser.add_argument("--model")
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--demo-public", action="store_true",
                        help="Register the public demonstration endpoint")
    parser.add_argument("--verify", action="store_true", default=True,
                        help="Open the stream before registering (default)")
    parser.add_argument("--no-verify", dest="verify", action="store_false")
    args = parser.parse_args()

    if args.demo_public:
        camera = dict(PUBLIC_DEMO)
    else:
        if not (args.native_id and args.name and args.rtsp_url):
            parser.error("--id, --name and --rtsp are required "
                         "(or use --demo-public)")
        camera = {
            "native_id": args.native_id, "name": args.name,
            "rtsp_url": args.rtsp_url, "department": args.department,
            "system": args.system, "lat": args.lat, "lon": args.lon,
            "address": args.address, "make": args.make, "model": args.model,
        }

    if args.verify:
        print(f"Verifying {camera['name']}…")
        ok, detail = verify_stream(camera["rtsp_url"])
        print(f"  {'OK' if ok else 'FAILED'}: {detail}")
        if not ok:
            print("\nNot registering a stream that does not decode. Check the URL,"
                  "\ncredentials and that the camera is reachable from this host.",
                  file=sys.stderr)
            return 1

    return register(camera, args.api_base)


if __name__ == "__main__":
    raise SystemExit(main())
