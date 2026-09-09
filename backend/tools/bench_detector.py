"""
Steady-state inference cost of the object detector on real sandbox frames.

    python tools/bench_detector.py                       # sandbox_frames.mp4
    python tools/bench_detector.py --source path.mp4 --frames 30

Exists because the number was measured wrongly twice. A first pass timed a
random-noise frame at ~300 ms and nearly rewrote the documentation with it;
noise floods the detector's candidate stage with boxes that a real scene never
produces. A second pass ran while three tiled ANPR streams held the CPU at 95%.
Neither is what a deployment sees.

Rules this enforces so the figure means something:
  - real frames, from the sandbox footage, at the sandbox's own resolution
  - the first call is reported separately, since it loads a 114 MB session
  - refuses to run when the machine is already busy, because a benchmark taken
    under load measures the other process
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import onnxruntime as ort  # noqa: E402

ort.set_default_logger_severity(4)

from app.object_detection import ObjectDetector, summarise  # noqa: E402

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "sample_feeds" / "sandbox_frames.mp4"
BUSY_THRESHOLD = 35.0     # percent; above this the number is not ours to report


def cpu_percent(sample_seconds: float = 1.5) -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.cpu_percent(interval=sample_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--frames", type=int, default=25)
    parser.add_argument("--stride", type=int, default=20,
                        help="Take every Nth frame so the sample spans the clip")
    parser.add_argument("--force", action="store_true",
                        help="Run even if the CPU is already busy")
    args = parser.parse_args()

    load = cpu_percent()
    if load is None:
        print("psutil not installed; cannot check load. Proceeding blind.")
    elif load > BUSY_THRESHOLD and not args.force:
        print(f"CPU is at {load:.0f}% before we start. A benchmark under load "
              f"measures the other process. Wait, or pass --force.")
        return 2
    else:
        print(f"CPU at {load:.0f}% before start")

    capture = cv2.VideoCapture(str(args.source), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        print(f"Could not open {args.source}", file=sys.stderr)
        return 1

    frames = []
    index = 0
    while len(frames) < args.frames:
        ok, frame = capture.read()
        if not ok:
            break
        if index % args.stride == 0:
            frames.append(frame)
        index += 1
    capture.release()

    if not frames:
        print("No frames read.", file=sys.stderr)
        return 1

    h, w = frames[0].shape[:2]
    print(f"{len(frames)} frames at {w}x{h} from {args.source.name}\n")

    detector = ObjectDetector()

    t = time.perf_counter()
    first = detector.detect(frames[0])
    warmup_ms = (time.perf_counter() - t) * 1000

    timings_ms = []
    objects = []
    for frame in frames[1:]:
        t = time.perf_counter()
        dets = detector.detect(frame)
        timings_ms.append((time.perf_counter() - t) * 1000)
        objects.append(len(dets))

    if not timings_ms:
        print(f"single frame: {warmup_ms:.0f} ms including model load")
        return 0

    print(f"model load + first frame : {warmup_ms:6.0f} ms   "
          f"({summarise(first)['total']} objects)")
    print(f"steady state, {len(timings_ms):2d} frames  : "
          f"mean {statistics.mean(timings_ms):5.0f} ms   "
          f"median {statistics.median(timings_ms):5.0f} ms   "
          f"min {min(timings_ms):5.0f}   max {max(timings_ms):5.0f}")
    print(f"objects per frame          : "
          f"mean {statistics.mean(objects):.1f}   max {max(objects)}")

    after = cpu_percent(0.5)
    if after is not None:
        print(f"\nCPU after: {after:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
