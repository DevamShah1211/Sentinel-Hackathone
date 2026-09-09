"""
Seed scene-analytics buckets so the Grid Health page has something to show.

    python tools/seed_scene_analytics.py                 # 24 hours
    python tools/seed_scene_analytics.py --hours 48
    python tools/seed_scene_analytics.py --clear         # remove seeded rows only

WHY THIS EXISTS, AND WHAT IT IS NOT
-----------------------------------
`tools/scene_analytics.py` runs the real detector against a real feed and is the
only thing that produces evidentiary counts. It needs the sandbox gateway up and
roughly a minute of wall clock per minute of footage, so a page opened on a
laptop with no gateway shows an empty state and demonstrates nothing.

This fills that gap, and every row it writes says so: `source = "seed"`, as
opposed to the `"worker"` a detector writes. That single column is what lets
the Grid Health page label demonstration data in place, offer a real-data-only
view, and lets `--clear` remove these rows without touching a real one. An
earlier version wrote rows indistinguishable from a worker's and claimed a
banner the page did not have; both were wrong, and the column is the fix.

Nothing here is passed off as a measurement. The measured numbers live in
MEASUREMENTS section 3 and came from the real detector on real frames.

The shape is not arbitrary. Counts follow a diurnal curve with twin peaks around
10:00 and 19:00 IST and a trough before dawn, and the per-camera scale comes
from what each camera actually watches: a highway bypass sees more vehicles and
almost no pedestrians, a bus port inverts that, a toll plaza sees trucks a
residential street never does. A reviewer who knows Indian roads should not be
able to point at the curve and say it is wrong.

Three groups matter for the page:
  - busy cameras, so the ranking has something to rank
  - two cameras watching an empty street (analysed, saw nothing)
  - eleven cameras with no rows at all (never looked)
The last two are different states and the page distinguishes them. A grid where
every camera reports cannot demonstrate finding the one that does not.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.api_auth import authenticated_session  # noqa: E402

API_BASE = "http://127.0.0.1:8000/api/v1"

# Deterministic: two runs produce the same grid, so a screenshot taken today
# still matches the page tomorrow.
SEED = 20260909

# Vehicle class mix per site type. Weights are relative frequencies.
HIGHWAY = {"car": 0.44, "truck": 0.28, "motorcycle": 0.18, "bus": 0.10}
CITY = {"car": 0.34, "motorcycle": 0.42, "truck": 0.14, "bus": 0.06, "bicycle": 0.04}
MARKET = {"motorcycle": 0.52, "car": 0.24, "bicycle": 0.14, "truck": 0.10}
TOLL = {"truck": 0.38, "car": 0.36, "bus": 0.14, "motorcycle": 0.12}

# native_id -> (peak vehicles in frame, peak people in frame, class mix)
PROFILES: dict[str, tuple[float, float, dict[str, float]]] = {
    # Ahmedabad, the busy core.
    "cam01": (9.0, 4.0, CITY),      # Chiman bhai Bridge
    "cam02": (7.0, 6.0, MARKET),    # Janpath
    "cam04": (8.0, 5.0, CITY),      # Paldi Circle
    "cam05": (10.0, 3.0, HIGHWAY),  # Visat teen Rasta
    "cam12": (11.0, 2.0, TOLL),     # Tri Mandir Adalaj Tollnaka
    "cam16": (8.0, 3.0, HIGHWAY),   # Visat P2
    # Junagadh cluster.
    "cam06": (5.0, 1.0, HIGHWAY),   # Timbavadi gate
    "cam08": (6.0, 3.0, HIGHWAY),   # majewadi-gate
    "cam09": (7.0, 2.0, HIGHWAY),   # new-bypass
    "cam10": (5.0, 5.0, MARKET),    # char-chowk-road
    "cam11": (4.0, 3.0, CITY),      # dolatpara
    # Rajkot.
    "cam17": (6.0, 8.0, MARKET),    # Bus Port, footfall over traffic
    "cam18": (7.0, 4.0, CITY),      # Rajkot CCTV
    # District towns, quieter.
    "cam19": (2.0, 2.0, CITY),      # Khaparia gram panchayat
    "cam21": (3.0, 2.0, CITY),      # Patan Dethali
    "cam27": (3.0, 2.0, MARKET),    # bilimora
    "cam30": (4.0, 2.0, HIGHWAY),   # Gandhidham Rambaugh
    # Watching an empty street. Not a fault: the worker looked and saw nothing,
    # which frames_sampled records and a count of zero alone cannot.
    "cam24": (0.3, 0.2, CITY),      # dehgam
    "cam25": (0.4, 0.3, CITY),      # dhanori
}

# cam03 cam07 cam13 cam14 cam15 cam20 cam22 cam23 cam26 cam28 cam29 get nothing.
NOT_SEEDED = ("cam03 cam07 cam13 cam14 cam15 cam20 "
              "cam22 cam23 cam26 cam28 cam29")

FRAMES_PER_BUCKET = 60          # one inference per second
COVERAGE = 0.70                 # share of minutes a real worker actually gets
BATCH_SIZE = 250                # buckets per request to /analytics/scene/batch

# Buckets are stored in UTC, but the traffic curve is a fact about Gujarat, so
# the peaks have to be placed in IST and converted. Skipping this puts the
# morning rush at 04:00 local, which anyone reading the page would catch.
IST = timezone(timedelta(hours=5, minutes=30))


def diurnal(hour: float) -> float:
    """
    Traffic multiplier for an hour of the day: about 0.05 before dawn, 1.0 at peak.

    Twin Gaussian peaks at 10:00 and 19:00 over a low afternoon plateau. That is
    the shape of an Indian urban arterial; a sine wave is not.
    """
    morning = math.exp(-((hour - 10.0) ** 2) / 8.0)
    evening = math.exp(-((hour - 19.0) ** 2) / 9.0)
    plateau = 0.42 * math.exp(-((hour - 14.5) ** 2) / 40.0)
    return max(0.05, min(1.0, morning + 0.95 * evening + plateau))


def draw_counts(peak: float, factor: float, mix: dict[str, float],
                rng: random.Random) -> dict[str, int]:
    """
    Peak simultaneous count per class for one bucket.

    Drawn around a mean rather than uniformly: real per-minute peaks cluster,
    with the occasional convoy. A uniform draw makes every camera look
    identically jittery, which reads as noise rather than as traffic.
    """
    expected = peak * factor
    if expected <= 0:
        return {}
    total = max(0, int(rng.gauss(expected, max(0.6, expected * 0.35)) + 0.5))
    if total == 0:
        return {}

    counts: dict[str, int] = {}
    labels, weights = list(mix), list(mix.values())
    for _ in range(total):
        label = rng.choices(labels, weights=weights)[0]
        counts[label] = counts.get(label, 0) + 1
    return counts


def build_buckets(native_id: str, hours: int, now: datetime,
                  rng: random.Random) -> list[dict]:
    """One bucket per sampled minute over the window."""
    veh_peak, per_peak, mix = PROFILES[native_id]
    buckets: list[dict] = []

    start = (now - timedelta(hours=hours)).replace(second=0, microsecond=0)

    for m in range(hours * 60):
        # Streams drop and the scheduler round-robins cameras, so a worker does
        # not get every minute. Modelling that is more honest than a full grid.
        if rng.random() > COVERAGE:
            continue

        at = start + timedelta(minutes=m)
        local = at.astimezone(IST)
        factor = diurnal(local.hour + local.minute / 60.0)

        by_label = draw_counts(veh_peak, factor, mix, rng)
        people = max(0, int(rng.gauss(per_peak * factor,
                                      max(0.5, per_peak * factor * 0.4)) + 0.5))
        if people:
            by_label["person"] = people

        by_category: dict[str, int] = {}
        for label, n in by_label.items():
            key = "person" if label == "person" else "vehicle"
            by_category[key] = by_category.get(key, 0) + n

        buckets.append({
            "camera_native_id": native_id,
            "bucket_start": at.astimezone(timezone.utc).isoformat(),
            "bucket_seconds": 60,
            "frames_sampled": FRAMES_PER_BUCKET,
            "counts_by_label": by_label,
            "counts_by_category": by_category,
            # The detector scored genuine objects 0.5-0.85 on real frames; a
            # bucket keeps the highest seen, so it sits in the upper half.
            "max_confidence": round(rng.uniform(0.68, 0.94), 4),
            "source": "seed",
        })
    return buckets


async def clear_seeded() -> int:
    """Delete seeded rows and only seeded rows. Returns how many went."""
    from sqlalchemy import text
    from app.database import engine

    async with engine.begin() as conn:
        before = (await conn.execute(text(
            "SELECT count(*) FROM scene_observations WHERE source = 'seed'"
        ))).scalar() or 0
        await conn.execute(text(
            "DELETE FROM scene_observations WHERE source = 'seed'"))
    return int(before)


def seed(hours: int, api_base: str) -> int:
    api = authenticated_session(api_base)
    if api is None:
        print("Could not authenticate against the API.", file=sys.stderr)
        return 1

    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)

    total = failed = 0
    print(f"Seeding {hours}h of scene analytics across {len(PROFILES)} cameras, "
          f"every row marked source=seed\n")

    for native_id in PROFILES:
        buckets = build_buckets(native_id, hours, now, rng)
        ok = 0
        # Batched. Posting each bucket individually is 1,440 requests per camera
        # per day, which the API rate-limits for good reason — the fix is the
        # bulk endpoint a real worker fleet would use, not a sleep in here.
        for start in range(0, len(buckets), BATCH_SIZE):
            chunk = buckets[start:start + BATCH_SIZE]
            try:
                response = api.post(f"{api_base}/analytics/scene/batch",
                                    json={"observations": chunk}, timeout=90)
                if response.ok:
                    ok += len(chunk)
                elif response.status_code == 404:
                    print(f"  {native_id}  not in the registry, skipped")
                    break
                else:
                    failed += len(chunk)
                    if failed <= len(chunk):
                        print(f"  {native_id}  HTTP {response.status_code}: "
                              f"{response.text[:160]}")
            except Exception as exc:
                failed += len(chunk)
                if failed <= len(chunk):
                    print(f"  {native_id}  {exc}")

        total += ok
        veh = sum(b["counts_by_category"].get("vehicle", 0) for b in buckets)
        ppl = sum(b["counts_by_category"].get("person", 0) for b in buckets)
        print(f"  {native_id}  {ok:4d} buckets   vehicles {veh:5d}   "
              f"people {ppl:5d}")

    print(f"\n{total} buckets written" + (f", {failed} failed" if failed else ""))
    print("\nLeft with no data on purpose, so the page can show a gap:")
    print(f"  {NOT_SEEDED}")
    print("\nRemove with: python tools/seed_scene_analytics.py --clear")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed scene-analytics buckets for the Grid Health page")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--api", default=API_BASE)
    parser.add_argument("--clear", action="store_true",
                        help="Delete rows with source=seed. Worker rows are untouched.")
    args = parser.parse_args()

    if args.clear:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        removed = asyncio.run(clear_seeded())
        print(f"Removed {removed} seeded bucket(s). Worker rows untouched.")
        return 0

    return seed(args.hours, args.api)


if __name__ == "__main__":
    raise SystemExit(main())
