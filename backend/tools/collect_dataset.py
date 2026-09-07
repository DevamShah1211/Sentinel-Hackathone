"""
Capture and label real plate crops, so a training set can exist at all.

    # Capture from your phone, a webcam, or a video file
    python tools/collect_dataset.py --source "rtsp://192.168.1.42:8554/live"

    # Label what was captured (the OCR proposes; you confirm or correct)
    python tools/collect_dataset.py --label

    # See what the dataset contains
    python tools/collect_dataset.py --report

Why this is separate from the recogniser.

Fine-tuning an OCR model needs annotated crops of *real* plates: glare, motion
blur, oblique angles, dirt, night-time sodium light. The synthetic clip cannot
provide them — every crop it produces is the same PIL-rendered font on a clean
background, and a model trained on those learns the font rather than the task.

So this tool exists to make honest data collection possible. It runs the
production detector over a feed, saves every plate crop it finds, and then walks
you through labelling them: the OCR proposes a reading, you press Enter to
accept or type the correct one. Roughly two seconds per crop.

The dataset it writes is what `tools/train_ocr.py` consumes. See DOCS/TRAINING.md
for how many crops are actually needed, and why 124 is not close.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import onnxruntime as ort  # noqa: E402

ort.set_default_logger_severity(4)

from app.plate_grammar import correct_plate, plausible_plate  # noqa: E402

DATASET = Path(__file__).resolve().parents[1] / "data" / "plate_dataset"
IMAGES = DATASET / "images"
LABELS = DATASET / "labels.csv"


def capture(source: str, seconds: int, min_width: int) -> int:
    """Save every plate crop the detector finds, unlabelled."""
    from app.vision import PlateDetector, frame_is_decodable

    IMAGES.mkdir(parents=True, exist_ok=True)
    capture_source = int(source) if source.isdigit() else source
    stream = cv2.VideoCapture(capture_source, cv2.CAP_DSHOW if source.isdigit() else cv2.CAP_FFMPEG)
    if not stream.isOpened():
        print(f"Could not open {source}", file=sys.stderr)
        return 0

    detector = PlateDetector(tiled=True)
    saved = frames = 0
    started = time.time()
    print(f"Capturing from {source} for {seconds}s. Ctrl-C to stop early.")

    try:
        while time.time() - started < seconds:
            ok, frame = stream.read()
            if not ok:
                break
            frames += 1
            if frames % 3:
                continue
            if not frame_is_decodable(frame):
                continue
            for det in detector.detect(frame):
                x1, y1, x2, y2 = det.bbox
                if (x2 - x1) < min_width:
                    # Too small to be worth labelling. A crop the model cannot
                    # read is a crop that teaches it nothing.
                    continue
                pad = 6
                h, w = frame.shape[:2]
                crop = frame[max(0, y1 - pad):min(h, y2 + pad),
                             max(0, x1 - pad):min(w, x2 + pad)]
                if crop.size == 0:
                    continue
                name = f"{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
                cv2.imwrite(str(IMAGES / name), crop)
                saved += 1
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.release()

    print(f"\nSaved {saved} crops from {frames} frames to {IMAGES}")
    print("Label them with:  python tools/collect_dataset.py --label")
    return saved


def _existing_labels() -> dict[str, str]:
    if not LABELS.exists():
        return {}
    with LABELS.open(encoding="utf-8", newline="") as fh:
        return {row["image"]: row["plate"] for row in csv.DictReader(fh)}


# Provenance is recorded, never inferred. Guessing it from filenames once made a
# wholly synthetic dataset report as 81% real, because the demonstration seeder
# stamps camera names onto crops taken from a rendered clip.
SOURCE_CAMERA = "camera"


def label() -> int:
    """
    Walk the unlabelled crops, proposing the OCR's reading for confirmation.

    The proposal matters: confirming a correct read is one keypress, so the
    labelling cost is dominated by the crops the recogniser got wrong, which are
    exactly the ones worth having in a training set.
    """
    from app.vision import PlateDetector

    labelled = _existing_labels()
    pending = sorted(p for p in IMAGES.glob("*.jpg") if p.name not in labelled)
    if not pending:
        print(f"Nothing to label. {len(labelled)} crops already labelled.")
        return 0

    detector = PlateDetector(tiled=False)
    print(f"{len(pending)} crops to label.\n")
    print("  Enter        accept the proposed reading")
    print("  <plate>      type the correct registration")
    print("  s            skip (unreadable, or not a plate)")
    print("  q            stop and save\n")

    LABELS.parent.mkdir(parents=True, exist_ok=True)
    new = 0
    try:
        for path in pending:
            image = cv2.imread(str(path))
            if image is None:
                continue
            reads = detector.read_crop(image)
            proposal = correct_plate(reads[0].text).text if reads else ""

            window = f"{path.name}  —  {proposal or 'no reading'}"
            cv2.imshow(window, cv2.resize(image, None, fx=3, fy=3,
                                          interpolation=cv2.INTER_CUBIC))
            cv2.waitKey(1)

            answer = input(f"  [{proposal or '?'}] > ").strip().upper()
            cv2.destroyWindow(window)

            if answer == "Q":
                break
            if answer == "S":
                continue
            plate = answer or proposal
            if not plate or not plausible_plate(plate):
                print("    not a plausible registration; skipped")
                continue

            labelled[path.name] = plate
            new += 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopping.")
    finally:
        cv2.destroyAllWindows()
        with LABELS.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=("image", "plate", "source"))
            writer.writeheader()
            for image, plate in sorted(labelled.items()):
                # Everything this tool captures came off a live feed.
                writer.writerow({"image": image, "plate": plate,
                                 "source": SOURCE_CAMERA})

    print(f"\n{new} newly labelled; {len(labelled)} total in {LABELS}")
    return new


def report() -> None:
    labelled = _existing_labels()
    crops = list(IMAGES.glob("*.jpg")) if IMAGES.exists() else []
    distinct = len(set(labelled.values()))

    print(f"crops captured : {len(crops)}")
    print(f"crops labelled : {len(labelled)}")
    print(f"distinct plates: {distinct}")

    if not labelled:
        print("\nNothing labelled yet.")
        return

    # The number that decides whether training is worth attempting.
    print(f"\nAgainst what the task needs (see DOCS/TRAINING.md):")
    for target, note in ((500, "bare minimum for a fine-tune to mean anything"),
                         (5000, "a fine-tune that might beat the baseline"),
                         (50000, "published Indian ANPR work")):
        pct = 100 * len(labelled) / target
        print(f"  {target:>6} crops  {pct:5.1f}%  {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture and label plate crops")
    parser.add_argument("--source", help="RTSP/HTTP URL, video file, or webcam index")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--min-width", type=int, default=90,
                        help="Ignore crops narrower than this; they teach nothing")
    parser.add_argument("--label", action="store_true", help="Label captured crops")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        report()
        return 0
    if args.label:
        label()
        report()
        return 0
    if not args.source:
        parser.error("--source is required unless --label or --report is given")
    capture(args.source, args.seconds, args.min_width)
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
