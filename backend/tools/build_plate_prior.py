"""
Build the plate prior from registrations this deployment has actually indexed.

    python tools/build_plate_prior.py            # learn from the detection index
    python tools/build_plate_prior.py --seed     # add district structure only
    python tools/build_plate_prior.py --report   # show what has been learned

This is the "training" step, and it is worth being precise about what it does.
No model weights change. It counts which districts and series this deployment
has seen, writes those counts to data/plate_prior.json, and the recogniser uses
them to settle reads that are otherwise tied. Running it on an empty index
produces a prior that scores everything zero, which is exactly the behaviour
before the prior existed.

Re-run it whenever the index has grown. It is cheap, and it is the one part of
the recognition stack that improves with use rather than staying fixed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.plate_prior import DEFAULT_PRIOR_PATH, PlatePrior  # noqa: E402
from app.rto_codes import GUJARAT_RTO  # noqa: E402


def load_indexed_plates() -> list[str]:
    """Every confirmed registration in the detection index."""
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def fetch() -> list[str]:
        from sqlalchemy import text

        from app.database import engine
        async with engine.begin() as conn:
            rows = await conn.execute(text("SELECT plate_text FROM detections"))
            return [r[0] for r in rows if r[0]]

    return asyncio.run(fetch())


def seed_structure(prior: PlatePrior, weight: int = 3) -> int:
    """
    Give a fresh deployment some structure before it has seen anything.

    Every Gujarat district is recorded a few times so the prior knows they
    exist, with the four multi-office cities weighted higher because a camera in
    Gujarat genuinely sees Ahmedabad and Surat plates far more often than
    Chhota Udaipur ones. This is a statement about the deployment's geography,
    not about any individual vehicle.
    """
    from app.rto_codes import CITY_RTO_GROUPS

    busy = {c for codes in CITY_RTO_GROUPS.get("GJ", {}).values() for c in codes}
    added = 0
    for number in GUJARAT_RTO:
        times = weight * (4 if number in busy else 1)
        for _ in range(times):
            prior.observe(f"GJ{number:02d}AA0001")
            added += 1
    return added


def report(prior: PlatePrior) -> None:
    print(f"observations: {prior.total}")
    if not prior.total:
        print("\nThe prior is empty, so it scores every plate zero and changes")
        print("nothing. Index some detections and run this again.")
        return

    print(f"\ntop districts ({len(prior.districts)} seen)")
    for key, count in prior.districts.most_common(12):
        from app.rto_codes import district_name
        name = district_name(key[:2], int(key[2:])) or ""
        print(f"  {key:6} {count:6}  {name}")

    if prior.series_any:
        print(f"\ntop series ({len(prior.series_any)} seen)")
        for series, count in prior.series_any.most_common(8):
            print(f"  {series:6} {count:6}")

    print("\nexample scores (higher is more plausible)")
    for plate in ("GJ01AB1234", "GJ27AB1234", "GJ30ZZ9999", "GJ99AB1234", "GG02XX4499"):
        print(f"  {plate:12} {prior.score(plate):+7.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the plate prior")
    parser.add_argument("--seed", action="store_true",
                        help="Add Gujarat district structure before learning")
    parser.add_argument("--report", action="store_true",
                        help="Show the current prior and exit")
    parser.add_argument("--path", default=str(DEFAULT_PRIOR_PATH))
    args = parser.parse_args()

    path = Path(args.path)

    if args.report:
        report(PlatePrior.load(path))
        return 0

    prior = PlatePrior()

    if args.seed:
        added = seed_structure(prior)
        print(f"Seeded {added} district observations from the RTO tables.")

    try:
        plates = load_indexed_plates()
    except Exception as exc:                      # noqa: BLE001
        print(f"Could not read the detection index: {exc}", file=sys.stderr)
        print("Seeding only.", file=sys.stderr)
        plates = []

    if plates:
        learned = prior.observe_many(plates)
        print(f"Learned from {learned} indexed registrations "
              f"({len(set(plates))} distinct).")

    prior.save(path)
    print(f"\nWrote {path}")
    report(prior)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
