"""
Fine-tune the plate recogniser on collected crops. **Not used in this build.**

    python tools/train_ocr.py --assess      # is training worth attempting?
    python tools/train_ocr.py --train       # run it, if --assess says yes

Read DOCS/TRAINING.md before running either.

This exists so the question "did you consider training your own model?" has a
real answer rather than an opinion. It was written, it runs, and it is not used,
because the assessment below says the available data cannot support it.

**The measurement that decided it.** The dataset at the time of writing is 124
crops of 10 distinct registrations, every one rendered by our own synthetic feed
generator. A model fine-tuned on those learns one font on a clean background. It
would score near-perfectly on the synthetic benchmark — the same images it
trained on — and generalise to nothing. Published Indian ANPR work uses 10,000
to 100,000 annotated *real* crops.

**The other reason.** The measured limit on the government cameras is 5 pixels
per character at cam12 and 10 at cam14, against the 20-30 that ANPR needs. That
is a property of the optics. No model reads characters the sensor never
captured, so a better recogniser does not move the number that actually blocks
this deployment.

`--assess` refuses to train when the data cannot support it, and says why. That
refusal is the useful part of this file.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATASET = Path(__file__).resolve().parents[1] / "data" / "plate_dataset"
IMAGES = DATASET / "images"
LABELS = DATASET / "labels.csv"

# Thresholds below which a fine-tune cannot be justified. These are not
# arbitrary: they are the points at which a held-out split stops being
# meaningful and overfitting stops being detectable.
MIN_CROPS = 500              # below this, a validation split is noise
MIN_DISTINCT_PLATES = 100    # below this, the model memorises registrations
MIN_REAL_FRACTION = 0.6      # below this, it learns the synthetic font


def load_labels() -> list[tuple[str, str]]:
    if not LABELS.exists():
        return []
    with LABELS.open(encoding="utf-8", newline="") as fh:
        return [(row["image"], row["plate"]) for row in csv.DictReader(fh)]


def load_rows() -> list[dict[str, str]]:
    """Labels with provenance, which is recorded rather than guessed."""
    if not LABELS.exists():
        return []
    with LABELS.open(encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def is_synthetic(row: dict[str, str]) -> bool:
    """
    Whether a crop came from a generated feed rather than a camera.

    Provenance is a recorded column, not an inference. An earlier version
    guessed from the filename and the plate, and reported a dataset that was
    entirely replayed synthetic video as "81% real" — because the seeder stamps
    camera names like cam01 onto crops it took from a rendered clip. A training
    tool whose first measurement flatters the data is worse than none, so the
    guess was replaced by a column that `collect_dataset.py` writes at capture
    time and the importer sets explicitly.
    """
    return (row.get("source") or "").strip().lower() != "camera"


def assess() -> int:
    """Report whether the dataset can support a fine-tune. Returns 0 if it can."""
    rows = load_rows()
    print("=" * 62)
    print(" TRAINING FEASIBILITY")
    print("=" * 62)

    if not rows:
        print("\n  No labelled dataset.")
        print("  Build one:  python tools/collect_dataset.py --source <feed>")
        print("              python tools/collect_dataset.py --label")
        return 1

    plates = [r["plate"] for r in rows]
    distinct = len(set(plates))
    synthetic = sum(1 for r in rows if is_synthetic(r))
    real = len(rows) - synthetic
    real_fraction = real / len(rows)

    print(f"\n  labelled crops     : {len(rows)}")
    print(f"  distinct plates    : {distinct}")
    print(f"  from real cameras  : {real} ({real_fraction * 100:.0f}%)")
    print(f"  synthetic          : {synthetic}")

    counts = Counter(plates)
    print(f"  crops per plate    : min {min(counts.values())} "
          f"median {sorted(counts.values())[len(counts) // 2]} max {max(counts.values())}")

    blockers: list[str] = []
    if len(rows) < MIN_CROPS:
        blockers.append(
            f"{len(rows)} crops, need at least {MIN_CROPS}. Below this a held-out "
            f"split is too small to detect overfitting, so the reported accuracy "
            f"would be meaningless.")
    if distinct < MIN_DISTINCT_PLATES:
        blockers.append(
            f"{distinct} distinct registrations, need at least {MIN_DISTINCT_PLATES}. "
            f"With fewer, the model memorises specific plates instead of learning "
            f"to read characters.")
    if real_fraction < MIN_REAL_FRACTION:
        blockers.append(
            f"{real_fraction * 100:.0f}% of crops are from real cameras, need "
            f"{MIN_REAL_FRACTION * 100:.0f}%. Synthetic crops all share one font on "
            f"a clean background; a model trained on them learns the font, not the "
            f"task, and fails on the first real plate.")

    print()
    if blockers:
        print("  NOT VIABLE:\n")
        for blocker in blockers:
            print(f"    - {blocker}\n")
        print("  Collect more real crops, or keep the pretrained model. The")
        print("  pretrained cct-s-v2 was trained on a large multi-country plate")
        print("  corpus; beating it needs data of comparable quality, not less.")
        print("=" * 62)
        return 1

    print("  VIABLE. A fine-tune can be attempted and honestly validated.")
    print("=" * 62)
    return 0


def split(rows: list[tuple[str, str]], holdout: float = 0.2, seed: int = 11):
    """
    Split by *registration*, never by crop.

    Splitting by crop puts different photographs of the same plate on both sides
    of the split, so the model can score well by memorising registrations it has
    already seen. Splitting by plate is the only division that measures reading.
    """
    plates = sorted({p for _, p in rows})
    random.Random(seed).shuffle(plates)
    cut = max(1, int(len(plates) * holdout))
    held = set(plates[:cut])
    train = [(i, p) for i, p in rows if p not in held]
    validate = [(i, p) for i, p in rows if p in held]
    return train, validate


def train(epochs: int, holdout: float) -> int:
    if assess() != 0:
        print("\nRefusing to train. See the blockers above.", file=sys.stderr)
        return 1

    try:
        import torch  # noqa: F401
    except ImportError:
        print("\nPyTorch is not installed. Install it first:", file=sys.stderr)
        print("  pip install torch --index-url https://download.pytorch.org/whl/cpu",
              file=sys.stderr)
        return 1

    rows = [(r["image"], r["plate"]) for r in load_rows()]
    train_rows, validate_rows = split(rows, holdout)
    print(f"\ntrain {len(train_rows)} crops / validate {len(validate_rows)} crops")
    print("Split by registration, so no plate appears on both sides.")

    # Deliberately not implemented further. Writing an untested training loop
    # that has never had data to run on would be worse than not writing one:
    # it would look finished and would not be. When a dataset exists that passes
    # the assessment, the shape is a CRNN or CTC head over the existing backbone,
    # trained here and exported to ONNX so app/vision.py loads it unchanged.
    print("\nThe training loop is intentionally not implemented in this build.")
    print("See DOCS/TRAINING.md section 4 for what it should be, and why writing")
    print("an untested loop against data that cannot support it would be worse")
    print("than leaving this honest.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune the plate recogniser")
    parser.add_argument("--assess", action="store_true",
                        help="Report whether the dataset can support training")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--holdout", type=float, default=0.2)
    args = parser.parse_args()

    if args.train:
        return train(args.epochs, args.holdout)
    return assess()


if __name__ == "__main__":
    raise SystemExit(main())
