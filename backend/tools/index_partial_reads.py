"""
Index a *partial* plate read from real government-feed crops.

    python tools/index_partial_reads.py --crops DIR --camera cam12

Why this exists. On cam12 (Adalaj Toll Naka) the detector found one real truck
plate 25 times, and the OCR recovered 8 of its 10 characters, but at ~5 px per
character the read never passes full grammar validation, so the strict indexer
correctly refuses to emit it. That is the right default for alerting — a
watchlist must not fire on a guess — but it is the wrong default for
investigation. A detective searching a plate wants to know that *something close*
was seen at the toll plaza at 14:02, and to look at the crop themselves.

So a track that is consistently detected, consistently read, and fails only on
grammar is written as a detection tagged ``partial``: it is searchable (the
trigram index tolerates the mangled characters), it carries the evidence crop,
and the UI labels it as unverified. Watchlist matching ignores partial reads.

Every character written here came from the OCR; nothing is typed in.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import cv2
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import onnxruntime as ort  # noqa: E402

ort.set_default_logger_severity(4)

from app.plate_grammar import PlateRead, correct_plate, vote  # noqa: E402
from app.settings import settings  # noqa: E402

API_BASE = "http://127.0.0.1:8000/api/v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a partial read from saved crops")
    parser.add_argument("--crops", help="Directory of saved frames from one track")
    parser.add_argument("--live", type=int, default=0,
                        help="Instead of saved frames, watch the camera's RTSP feed for N seconds")
    parser.add_argument("--camera", required=True, help="Camera native id, e.g. cam12")
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--min-reads", type=int, default=3)
    args = parser.parse_args()

    from app.vision import PlateDetector

    # Full frames, not pre-cut crops: the recognizer is tuned to the detector's
    # own crop geometry and returns nothing on padded, upscaled cut-outs.
    detector = PlateDetector(tiled=True)
    reads: list[PlateRead] = []
    best_crop = None
    def frames():
        if args.live:
            import time
            from urllib.parse import quote
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
            auth = (f"{quote(settings.sentinel_user_email, safe='')}:"
                    f"{quote(settings.sentinel_user_password, safe='')}@")
            url = (f"rtsp://{auth}{settings.sentinel_ip}:{settings.sentinel_rtsp_port}"
                   f"/stream/{args.camera}")
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            t0, n = time.time(), 0
            while time.time() - t0 < args.live:
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                if n > 30 and n % 4 == 0:
                    yield f"live+{int(time.time() - t0):03d}s", frame
            cap.release()
        else:
            for path in sorted(glob.glob(os.path.join(args.crops, "*.jpg"))):
                frame = cv2.imread(path)
                if frame is not None:
                    yield os.path.basename(path), frame

    for label, frame in frames():
        for d in detector.detect(frame):
            if not d.text:
                continue
            confs = list(d.char_confidences) if len(d.char_confidences) == len(d.text)                 else [d.mean_confidence or 0.5] * len(d.text)
            reads.append(PlateRead(text=d.text, char_confidences=confs))
            if best_crop is None:
                x1, y1, x2, y2 = d.bbox
                best_crop = frame[max(0, y1 - 6):y2 + 6, max(0, x1 - 6):x2 + 6]
            print(f"  {label:20} {d.text:12} -> {correct_plate(d.text).text}")

    if len(reads) < args.min_reads:
        print(f"Only {len(reads)} reads; need {args.min_reads}.", file=sys.stderr)
        return 1

    voted = vote(reads)
    if voted is None:
        print("Vote produced nothing.", file=sys.stderr)
        return 1
    plate, confidence, grammar = voted
    print(f"\nvoted {plate!r} conf={confidence:.3f} valid={grammar.valid} "
          f"fmt={grammar.fmt} corrections={grammar.corrections}")
    if grammar.valid and grammar.state_valid:
        print("This read is fully valid; the normal indexer would have emitted it.")

    crop_uri = None
    if best_crop is not None:
        evidence = Path(settings.evidence_crop_dir)
        evidence.mkdir(parents=True, exist_ok=True)
        name = f"{args.camera}_PARTIAL_{plate}.jpg"
        cv2.imwrite(str(evidence / name), best_crop)
        crop_uri = f"/evidence/{name}"

    body = {
        "camera_native_id": args.camera,
        "plate_text": plate,
        "confidence": round(confidence, 4),
        "track_id": f"{args.camera}-partial-{plate}",
        "crop_uri": crop_uri,
        "raw_reads": [{"plate": r.text, "conf": round(r.mean_confidence, 4)} for r in reads]
                     + [{"_meta": True, "partial": True,
                         "reason": "grammar validation failed; ~5 px per character",
                         "source": "government sandbox feed"}],
        "plate_format": grammar.fmt,
        "grammar_corrections": grammar.corrections,
    }
    response = requests.post(f"{args.api_base}/detections", json=body, timeout=25)
    response.raise_for_status()
    print(f"\nWritten to {args.camera} as a PARTIAL read: {plate}  (crop {crop_uri})")
    print("Search it with fuzzy match on; the UI marks it unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
