"""
Seed several distinct vehicle journeys for the demonstration.

    python tools/seed_demo_route.py            # seed on top of what is there
    python tools/seed_demo_route.py --reset    # clear the index first

Each vehicle gets its OWN route: different cameras, different times, different
speeds. An earlier version replayed the whole clip at every camera, which meant
every plate appeared at every camera at the same instant — so every search
returned an identical route, which is obviously wrong the moment you search a
second plate.

Timings come from the real distances between these cameras, giving ordinary city
speeds of roughly 20-55 km/h. One journey deliberately ends with an
Ahmedabad-to-Rajkot leg minutes later: physically impossible, and the platform
flags it rather than hiding it, which is the behaviour worth demonstrating.

Every plate written is read by the real detector and OCR from the clip. Only the
timestamp is supplied, and only because the footage is a replay.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = BACKEND / "sample_feeds" / "own_feed_demo.mp4"

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


def run(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(command, cwd=BACKEND, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed distinct demonstration journeys")
    parser.add_argument("--video", default=str(DEFAULT_VIDEO))
    parser.add_argument("--reset", action="store_true",
                        help="Clear the detection index before seeding")
    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"No such video: {args.video}\n"
              f"Generate one with: python tools/make_sample_feed.py", file=sys.stderr)
        return 1

    if args.reset:
        print("Clearing the detection index…")
        code, output = run([sys.executable, "tools/reset_index.py", "--yes"])
        for line in output.splitlines():
            if "Cleared" in line or "already empty" in line:
                print(f"  {line.strip()}")

    start = datetime.now(timezone.utc) - timedelta(hours=2)
    total_indexed = 0

    for journey in JOURNEYS:
        print(f"\n{journey['plate']} — {journey['note']}")
        for camera, minutes in journey["legs"]:
            stamp = (start + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
            code, output = run([
                sys.executable, "tools/demo_seed.py",
                "--video", args.video,
                "--camera", camera,
                "--detected-at", stamp,
                "--only-plate", journey["plate"],
            ])
            indexed = 0
            for line in output.splitlines():
                if "plates indexed" in line:
                    try:
                        indexed = int(line.split(":")[1].split()[0])
                    except (IndexError, ValueError):
                        pass
            total_indexed += indexed
            status = f"{indexed} indexed" if code == 0 else f"FAILED (exit {code})"
            print(f"  {camera} at +{minutes:>2} min — {status}")
            if code != 0:
                print(output[-500:], file=sys.stderr)

    print(f"\n{len(JOURNEYS)} journeys seeded, {total_indexed} detections written.")
    print("Search any plate and choose 'Show Route on Map' — each returns its own")
    print("route. GJ01AB1234 ends with a flagged impossible transition to Rajkot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
