"""
Generate a synthetic 'own feed' clip with known ground-truth Indian plates.

Two uses:

1. **Pipeline validation.** Because the plates are known, this measures end-to-end
   accuracy — detection, tracking, per-character voting and grammar correction —
   and prints a confusion summary. Run it after any change to the vision code.

2. **The own-feed demo video.** The playbook asks for a 2-3 minute video on your
   own footage. A phone video of a real road is the better artefact and should be
   preferred; this clip exists so the pipeline can be demonstrated end to end even
   when no such footage is to hand, and it is clearly labelled synthetic on every
   frame so it can never be mistaken for real evidence.

    python tools/make_sample_feed.py --validate

Serve it over RTSP with MediaMTX (or point the worker at the .mp4 directly) to
exercise the same capture path the sandbox uses.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "sample_feeds"
WIDTH, HEIGHT, FPS = 1280, 720, 25

# Ground truth for the synthetic clip.
#
# These use RTO district codes that DO NOT EXIST — Gujarat issues GJ-01 to GJ-39,
# Maharashtra MH-01 to MH-50, Rajasthan RJ-01 to RJ-58 — so every plate here is
# correctly *formatted* and passes the pipeline's grammar validation, while being
# impossible to issue to a real vehicle.
#
# That matters. An earlier version used plausible registrations like GJ18CD5678,
# which turns out to belong to a real motorcycle: a reviewer who looks one up
# finds a real owner beside our synthetic VAHAN record, and the demonstration
# starts to look like it is making claims about a real person. Unissuable codes
# remove that risk entirely without weakening the test — the OCR and the grammar
# checks cannot tell the difference.
GROUND_TRUTH = [
    "GJ99AB1234",   # GJ-99 is not an issued RTO code
    "GJ98CD5678",
    "GJ97JV7219",
    "MH99DE1433",   # nor is MH-99
    "RJ99GH9012",   # nor RJ-99
    "GJ96XY4455",
]

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\ariblk.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _font_path() -> str:
    for candidate in _FONT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        "No TrueType font found. Plate glyphs must be rendered with a real font — "
        "OpenCV's Hershey fonts do not resemble plate characters and make OCR "
        "results look far worse than they are."
    )


def render_plate(text: str, width: int = 440, height: int = 95) -> np.ndarray:
    """A white Indian plate with a black border, drawn with a real font."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), (250, 250, 248))
    draw = ImageDraw.Draw(image)
    draw.rectangle([2, 2, width - 3, height - 3], outline=(15, 15, 15), width=4)

    font_file = _font_path()
    size = int(height * 0.62)
    while size > 12:
        font = ImageFont.truetype(font_file, size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= width - 46:
            break
        size -= 2

    font = ImageFont.truetype(font_file, size)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2 - box[0],
               (height - (box[3] - box[1])) / 2 - box[1]),
              text, font=font, fill=(10, 10, 10))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def road_background() -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 120, np.uint8)
    cv2.rectangle(frame, (0, 0), (WIDTH, 250), (150, 175, 200), -1)     # sky
    cv2.rectangle(frame, (0, 250), (WIDTH, HEIGHT), (68, 68, 70), -1)   # carriageway
    cv2.rectangle(frame, (0, 250), (WIDTH, 264), (190, 190, 182), -1)   # far kerb
    for x in range(0, WIDTH, 170):
        cv2.rectangle(frame, (x, 520), (x + 95, 534), (232, 232, 228), -1)
    return frame


def build_clip(path: Path, plates: list[str], frames_per_pass: int = 80,
               seed: int = 11) -> Path:
    """Render each plate approaching the camera on a looping road scene."""
    random.seed(seed)
    rng = np.random.default_rng(seed)
    path.parent.mkdir(parents=True, exist_ok=True)

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                             FPS, (WIDTH, HEIGHT))
    background = road_background()

    for plate in plates:
        body_colour = tuple(int(c) for c in rng.integers(40, 160, size=3))
        for i in range(frames_per_pass):
            frame = background.copy()
            t = i / frames_per_pass

            # The vehicle approaches: the plate grows from 70 px to 250 px wide.
            plate_w = int(70 + 180 * t)
            plate_h = max(16, int(plate_w * 0.215))
            cx = int(WIDTH * (0.32 + 0.26 * t))
            cy = int(300 + 330 * t)

            body_w, body_h = int(plate_w * 2.7), int(plate_w * 2.1)
            cv2.rectangle(frame,
                          (cx - body_w // 2, cy - body_h + plate_h),
                          (cx + body_w // 2, cy + plate_h // 2),
                          body_colour, -1)
            cv2.rectangle(frame,
                          (cx - body_w // 2, cy - body_h + plate_h),
                          (cx + body_w // 2, cy + plate_h // 2),
                          (25, 25, 25), 2)

            tile = render_plate(plate)
            tile = cv2.resize(tile, (plate_w, plate_h), interpolation=cv2.INTER_AREA)

            # A little perspective and motion blur, as a real camera would see.
            angle = (t - 0.5) * 7
            matrix = cv2.getRotationMatrix2D((plate_w / 2, plate_h / 2), angle, 1.0)
            tile = cv2.warpAffine(tile, matrix, (plate_w, plate_h),
                                  borderMode=cv2.BORDER_REPLICATE)
            if t < 0.3:
                tile = cv2.GaussianBlur(tile, (3, 3), 0)

            y1, x1 = cy - plate_h // 2, cx - plate_w // 2
            if 0 <= y1 and y1 + plate_h < HEIGHT and 0 <= x1 and x1 + plate_w < WIDTH:
                frame[y1:y1 + plate_h, x1:x1 + plate_w] = tile

            noise = rng.normal(0, 4, frame.shape)
            frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

            # Labelled synthetic on every frame — this must never be mistaken for
            # real evidence in a submission.
            cv2.putText(frame, "SENTINEL SYNTHETIC TEST FEED - NOT REAL FOOTAGE",
                        (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
            writer.write(frame)

    writer.release()
    return path


def validate(clip: Path, truth: list[str], stride: int = 3, tiled: bool = True) -> int:
    """Run the production pipeline over the clip and report accuracy."""
    from app.vision import PlateDetector, TrackManager, aggregate_track

    detector = PlateDetector(tiled=tiled)
    # Production settings. Requiring two reads before a track is emitted is what
    # removes single-frame phantom reads: measured on this clip, every spurious
    # plate came from a one-read track, and every real vehicle produced 20+.
    tracks = TrackManager(min_reads=2)

    capture = cv2.VideoCapture(str(clip))
    emitted: list[tuple[str, float, int]] = []
    index = 0

    def collect(force: bool = False) -> None:
        for track in tracks.collect_finished(index, force=force):
            voted = aggregate_track(track)
            if voted:
                emitted.append((voted[0], voted[1], len(track.reads)))

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        index += 1
        if index % stride:
            continue
        tracks.update(detector.detect(frame), index, index * 40, frame)
        collect()
    collect(force=True)
    capture.release()

    recovered = {plate for plate, _, _ in emitted}
    expected = set(truth)
    matched = expected & recovered

    print("\n" + "═" * 62)
    print(" PIPELINE VALIDATION — synthetic feed, known ground truth")
    print("═" * 62)
    print(f"  frames processed : {index}")
    print(f"  tracks emitted   : {len(emitted)}")
    print(f"\n  {'voted plate':14} {'conf':>6} {'reads':>6}  correct")
    for plate, conf, reads in sorted(emitted):
        print(f"  {plate:14} {conf:6.3f} {reads:6d}  {'yes' if plate in expected else 'NO'}")
    print(f"\n  ground truth     : {sorted(expected)}")
    print(f"  recovered        : {sorted(recovered)}")
    print(f"  plate accuracy   : {len(matched)}/{len(expected)} "
          f"({100 * len(matched) / len(expected):.0f}%)")
    false_positives = recovered - expected
    if false_positives:
        print(f"  false positives  : {sorted(false_positives)}")
    print("═" * 62 + "\n")
    return 0 if matched == expected else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate a synthetic ANPR feed")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "own_feed_demo.mp4"))
    parser.add_argument("--validate", action="store_true",
                        help="Run the pipeline over the clip and report accuracy")
    parser.add_argument("--frames-per-pass", type=int, default=110)
    parser.add_argument("--no-tiling", action="store_true",
                        help="Validate with full-frame inference instead of tiling")
    args = parser.parse_args()

    clip = build_clip(Path(args.output), GROUND_TRUTH, args.frames_per_pass)
    print(f"Wrote {clip} ({len(GROUND_TRUTH)} vehicle passes)")

    if args.validate:
        return validate(clip, GROUND_TRUTH, tiled=not args.no_tiling)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
