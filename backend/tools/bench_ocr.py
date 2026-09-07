"""
Measure recognition accuracy, so changes are proved rather than assumed.

    python tools/bench_ocr.py                 # end-to-end on the synthetic clip
    python tools/bench_ocr.py --strings       # grammar layer only, on real reads
    python tools/bench_ocr.py --both

Two benchmarks, because there are two ways to be wrong:

**End to end** runs the whole pipeline over a clip with known ground truth and
reports how many vehicles were recovered and how many plates were invented. This
is the number that matters, but it is slow and only covers what the clip shows.

**Strings** replays OCR output captured from the government cameras through the
grammar layer alone. It is instant, and it is the only way to test against the
specific errors real Indian plates and real Gujarat cameras produce — GJ read as
GI, a dropped character, a state code mangled by glare.

A change that improves one and worsens the other is not an improvement. Run both.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.plate_grammar import correct_plate, plausible_plate  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_CLIP = BACKEND / "sample_feeds" / "own_feed_demo.mp4"

# Real OCR output captured from the sandbox and the synthetic clip, paired with
# what the plate actually is. Cases marked None are strings that must NOT be
# accepted: signage, overlay text and reads too damaged to be trusted.
#
# Every entry here was produced by the recogniser on this project. None are
# invented, because a benchmark of imagined errors measures nothing.
CASES: list[tuple[str, str | None]] = [
    # --- Clean reads that must survive untouched -------------------------
    ("GJ99AB1234", "GJ99AB1234"),
    ("GJ98CD5678", "GJ98CD5678"),
    ("MH99DE1433", "MH99DE1433"),
    ("RJ99GH9012", "RJ99GH9012"),
    ("GJ01AB1234", "GJ01AB1234"),

    # --- Classic confusions the grammar already fixes --------------------
    ("GJO1AB1234", "GJ01AB1234"),   # O in a digit slot
    ("GJ0lAB1234", "GJ01AB1234"),   # lowercase l as 1
    ("6J01AB1234", "GJ01AB1234"),   # 6 for G in the state code
    ("GJ01A81234", "GJ01AB1234"),   # 8 for B in the series
    ("GJ01AB12E4", "GJ01AB1234"),   # E for 3 in the serial

    # --- Real cam14 reads. The plate is GJ06BA1316 by eye ----------------
    # These are 8 characters for a 10 character plate: the recogniser dropped
    # two. Nothing should "recover" them — inventing the missing characters
    # would be fabrication. They must be rejected, not repaired.
    ("GI65AA33", None),
    ("GI63AA31", None),
    ("KI484131", None),
    ("1168A111", None),

    # --- Real cam12 toll-plaza reads of one truck ------------------------
    ("66Q2XT449", None),
    ("6302XX449", None),
    ("6602XX449", None),

    # --- Signage and overlay text that must never be indexed -------------
    ("AEVETEE", None),
    ("CSITMS01", None),
    ("PTZ0001", None),
    ("LA1O0444", None),          # passes format, implausible state
    ("14-06-2026", None),

    # --- Bharat series ---------------------------------------------------
    ("22BH1234AA", "22BH1234AA"),
    ("21BH0001A", "21BH0001A"),
]


def bench_strings(verbose: bool = False) -> tuple[int, int, int]:
    """Return (correct, wrong, total) for the grammar layer."""
    from app.plate_grammar import plausible_in_gujarat

    correct = wrong = 0
    failures: list[str] = []

    for raw, expected in CASES:
        result = correct_plate(raw)
        accepted = (
            plausible_plate(raw)
            and result.valid
            and result.state_valid
            and plausible_in_gujarat(result.text)
        )
        got = result.text if accepted else None

        if got == expected:
            correct += 1
            if verbose:
                print(f"  ok    {raw:14} -> {got or 'rejected'}")
        else:
            wrong += 1
            failures.append(
                f"  FAIL  {raw:14} -> {got or 'rejected':14} "
                f"(expected {expected or 'rejected'})")

    for line in failures:
        print(line)
    total = correct + wrong
    print(f"\ngrammar layer: {correct}/{total} correct "
          f"({100 * correct / total:.0f}%)")
    return correct, wrong, total


def bench_clip(clip: Path, tiled: bool = True) -> int:
    """End-to-end accuracy on a clip with known ground truth."""
    import cv2
    import onnxruntime as ort

    ort.set_default_logger_severity(4)
    from app.vision import PlateDetector, TrackManager, aggregate_track
    from tools.make_sample_feed import GROUND_TRUTH

    if not clip.exists():
        print(f"No clip at {clip}. Build one with tools/make_sample_feed.py",
              file=sys.stderr)
        return 1

    detector = PlateDetector(tiled=tiled)
    tracks = TrackManager(min_reads=2)
    capture = cv2.VideoCapture(str(clip))
    emitted: list[tuple[str, float, int]] = []
    index = 0

    def collect(force: bool = False) -> None:
        for track in tracks.collect_finished(index, force=force):
            voted = aggregate_track(track, detector)
            if voted:
                emitted.append((voted[0], voted[1], len(track.reads)))

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        index += 1
        if index % 3:
            continue
        tracks.update(detector.detect(frame), index, index * 40, frame)
        collect()
    collect(force=True)
    capture.release()

    recovered = {p for p, _, _ in emitted}
    expected = set(GROUND_TRUTH)
    matched = expected & recovered
    false_positives = recovered - expected

    print(f"\nend to end on {clip.name}")
    print(f"  frames processed : {index}")
    print(f"  tracks emitted   : {len(emitted)}")
    for plate, conf, reads in sorted(emitted):
        mark = "ok" if plate in expected else "FALSE POSITIVE"
        print(f"    {plate:14} {conf:6.3f} {reads:4d} reads  {mark}")
    print(f"  recovered        : {len(matched)}/{len(expected)} "
          f"({100 * len(matched) / len(expected):.0f}%)")
    print(f"  false positives  : {len(false_positives)}"
          + (f" {sorted(false_positives)}" if false_positives else ""))
    return 0 if matched == expected and not false_positives else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure ANPR accuracy")
    parser.add_argument("--strings", action="store_true",
                        help="Grammar layer only, against captured real reads")
    parser.add_argument("--both", action="store_true")
    parser.add_argument("--clip", default=str(DEFAULT_CLIP))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.strings or args.both:
        _, wrong, _ = bench_strings(args.verbose)
        if args.strings and not args.both:
            return 1 if wrong else 0

    return bench_clip(Path(args.clip))


if __name__ == "__main__":
    raise SystemExit(main())
