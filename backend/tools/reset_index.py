"""
Clear the detection index and its alerts.

Used before re-seeding a demonstration so old journeys do not blend into new
ones. The camera registry, watchlist, users and audit trail are deliberately left
alone: the watchlist is what makes alerts fire on the next seed, and an audit
trail that can be wiped by a convenience script is not an audit trail.

    python tools/reset_index.py
    python tools/reset_index.py --yes     # skip the confirmation
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def reset(confirm: bool) -> int:
    from sqlalchemy import text

    from app.database import engine

    async with engine.begin() as conn:
        detections = await conn.scalar(text("SELECT count(*) FROM detections"))
        alerts = await conn.scalar(text("SELECT count(*) FROM alerts"))

        if not detections and not alerts:
            print("Index is already empty.")
            return 0

        print(f"This will delete {detections} detections and {alerts} alerts.")
        print("The camera registry, watchlist, users and audit trail are kept.")
        if not confirm:
            answer = input("Proceed? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("Cancelled.")
                return 1

        # Alerts reference detections, so they go first.
        await conn.execute(text("DELETE FROM alerts"))
        await conn.execute(text("DELETE FROM detections"))
        print(f"Cleared {detections} detections and {alerts} alerts.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear the detection index")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the confirmation prompt")
    args = parser.parse_args()
    return asyncio.run(reset(args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
