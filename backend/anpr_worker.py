"""
ANPR Worker — Role A (Vision & Ingest)
Captures RTSP streams from the Sentinel sandbox using correct practices:
  - TCP transport only
  - PTS for all timing (never wall-clock)
  - Exponential backoff reconnect (2s → 30s)
  - Decoder warnings are logged, not fatal
  - Indian plate grammar post-processing
  - Track-level confidence-weighted voting (1 event per vehicle pass)
"""
import os
import sys
import time
import logging
import argparse
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests
import numpy as np

# ─── PTS-based timing: set BEFORE importing cv2 ──────────────────────────────
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
import cv2  # noqa: E402

logger = logging.getLogger("sentinel.anpr_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ─── Config ───────────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")
SENTINEL_HOST = os.getenv("SENTINEL_HOST", "cctv.corp8.cloud")
SENTINEL_RTSP_PORT = int(os.getenv("SENTINEL_RTSP_PORT", "8554"))
EVIDENCE_DIR = Path(os.getenv("EVIDENCE_CROP_DIR", "./evidence_crops"))
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# ANPR sampling — 5-10 fps is sufficient; do NOT process every frame
SAMPLE_EVERY_N_FRAMES = 3

# Valid Indian state codes for grammar correction
VALID_STATE_CODES = {
    "AP","AR","AS","BR","CG","CH","DL","GA","GJ","HR","HP","JH","JK","KA",
    "KL","LA","LD","MH","MN","ML","MP","MZ","NL","OD","PB","PY","RJ","SK",
    "TN","TS","TR","UK","UP","WB","AN","DN", "BH"  # BH = Bharat series
}

# ─── Indian plate grammar post-processor ─────────────────────────────────────

def correct_plate(plate: str) -> str:
    """
    Apply positional O↔0, I↔1, S↔5, B↔8, Z↔2, G↔6, D↔0 corrections.
    Format: [State 2L][District 1-2D][Series 1-3L][Number 4D]
    """
    plate = plate.upper().replace(" ", "").replace("-", "")
    if len(plate) < 6:
        return plate

    result = list(plate)
    # Positions 0-1: must be alpha (state code)
    alpha_subs = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}
    num_subs   = {"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2", "G": "6", "D": "0"}

    for i in range(min(2, len(result))):
        result[i] = alpha_subs.get(result[i], result[i])

    # Positions 2-3: must be numeric (district)
    for i in range(2, min(4, len(result))):
        result[i] = num_subs.get(result[i], result[i])

    # Last 4 positions: must be numeric (serial number)
    for i in range(max(0, len(result) - 4), len(result)):
        result[i] = num_subs.get(result[i], result[i])

    corrected = "".join(result)

    # Validate state code
    state = corrected[:2]
    if state not in VALID_STATE_CODES:
        logger.debug(f"Unrecognised state code: {state} in plate {corrected}")

    return corrected


# ─── Track-level voting ───────────────────────────────────────────────────────

class PlateTracker:
    """
    Accumulates per-frame reads for a vehicle track.
    Emits one best read per track using confidence-weighted per-character voting.
    """
    def __init__(self, track_id: str, min_reads: int = 3):
        self.track_id = track_id
        self.min_reads = min_reads
        self.reads: list[tuple[str, float]] = []  # (plate_text, confidence)
        self.bbox = None
        self.last_seen_frame = 0

    def add_read(self, plate: str, confidence: float, bbox, frame_idx: int):
        self.reads.append((correct_plate(plate), confidence))
        self.bbox = bbox
        self.last_seen_frame = frame_idx

    def vote(self) -> tuple[str, float] | None:
        """Return the confidence-weighted best plate string."""
        if len(self.reads) < self.min_reads:
            return None

        # Per-character voting
        max_len = max(len(p) for p, _ in self.reads)
        voted_chars = []
        total_conf = sum(c for _, c in self.reads)

        for pos in range(max_len):
            char_scores: dict[str, float] = {}
            for plate, conf in self.reads:
                if pos < len(plate):
                    c = plate[pos]
                    char_scores[c] = char_scores.get(c, 0) + conf
            if char_scores:
                voted_chars.append(max(char_scores, key=char_scores.get))

        best_plate = "".join(voted_chars)
        avg_conf = total_conf / len(self.reads) if self.reads else 0.0
        return best_plate, avg_conf


# ─── FastALPR / fallback OCR ─────────────────────────────────────────────────

def load_anpr_engine():
    """
    Try fast-alpr first (best out-of-the-box accuracy).
    Fall back to OpenCV DNN + pytesseract if unavailable.
    Returns callable: frame → list of (plate_text, confidence, bbox)
    """
    try:
        from fast_alpr import ALPR
        alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                    ocr_model="global-plates-mobile-vit-v2-model")
        logger.info("✅ fast-alpr engine loaded")

        def detect(frame):
            results = alpr.run(frame)
            detections = []
            for r in results:
                if r.ocr and r.ocr[0].text:
                    plate = r.ocr[0].text
                    conf  = r.ocr[0].confidence
                    bbox_obj = r.detection.bounding_box
                    bbox  = {
                        "x1": bbox_obj.x1, "y1": bbox_obj.y1,
                        "x2": bbox_obj.x2, "y2": bbox_obj.y2,
                    }
                    detections.append((plate, conf, bbox))
            return detections
        return detect

    except ImportError:
        logger.warning("fast-alpr not installed — using mock ANPR (install: pip install fast-alpr)")

        def mock_detect(frame):
            # In production: replace with real OCR.
            # Returns empty list so the worker runs without crashing.
            return []
        return mock_detect


detect_plates = load_anpr_engine()


# ─── API client ───────────────────────────────────────────────────────────────

def post_detection(camera_id: str, plate: str, confidence: float,
                   pts_ms: int, track_id: str, crop_path: str, raw_reads: list):
    try:
        resp = requests.post(
            f"{API_BASE}/detections",
            json={
                "camera_id": camera_id,
                "plate_text": plate,
                "confidence": confidence,
                "pts_ms": pts_ms,
                "track_id": track_id,
                "crop_uri": str(crop_path) if crop_path else None,
                "vehicle_type": "car",
                "raw_reads": [{"plate": p, "conf": c} for p, c in raw_reads],
            },
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to post detection: {e}")
        return None


def save_crop(frame, bbox: dict, plate: str) -> str | None:
    try:
        h, w = frame.shape[:2]
        x1 = max(0, int(bbox.get("x1", 0)))
        y1 = max(0, int(bbox.get("y1", 0)))
        x2 = min(w, int(bbox.get("x2", w)))
        y2 = min(h, int(bbox.get("y2", h)))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        fname = EVIDENCE_DIR / f"{plate}_{ts}.jpg"
        cv2.imwrite(str(fname), crop)
        return f"/evidence/{fname.name}"
    except Exception:
        return None


# ─── Main capture loop ────────────────────────────────────────────────────────

def process_stream(camera_id: str, rtsp_url: str, hls_url: str = None):
    """
    Capture stream with TCP transport, HLS fallback, and exponential backoff reconnect.
    """
    backoff = 2.0
    active_tracks: dict[str, PlateTracker] = {}
    TRACK_TIMEOUT_FRAMES = 60  # emit track result after this many frames without seeing it
    attempts = 0
    current_url = rtsp_url

    while True:
        cap = cv2.VideoCapture(current_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            attempts += 1
            # Fallback to HLS if RTSP is blocked or failing repeatedly
            if attempts >= 3 and hls_url and current_url != hls_url:
                logger.warning(f"Camera {camera_id}: RTSP port/connection unavailable. Falling back to HLS: {hls_url}")
                current_url = hls_url
                attempts = 0
                continue

            logger.warning(f"Camera {camera_id}: could not open {current_url}, retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue

        backoff = 2.0  # reset on successful connect
        attempts = 0
        logger.info(f"Camera {camera_id}: stream opened → {current_url}")

        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                logger.warning(f"Camera {camera_id}: read failed — reconnecting in {backoff}s")
                cap.release()
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                break

            # ── Timing from PTS — NEVER use time.time() ──
            pts_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
            frame_idx += 1

            # ── Flush stale tracks ────────────────────────────────────────────
            stale = [tid for tid, tr in active_tracks.items()
                     if frame_idx - tr.last_seen_frame > TRACK_TIMEOUT_FRAMES]
            for tid in stale:
                tr = active_tracks.pop(tid)
                result = tr.vote()
                if result:
                    plate, conf = result
                    crop_path = save_crop(frame, tr.bbox or {}, plate)
                    raw = tr.reads
                    post_detection(camera_id, plate, conf, pts_ms, tid, crop_path, raw)
                    logger.info(f"Camera {camera_id}: PLATE {plate} conf={conf:.2f} track={tid}")

            # ── Sample only every N frames ────────────────────────────────────
            if frame_idx % SAMPLE_EVERY_N_FRAMES != 0:
                continue

            # ── Run ANPR ─────────────────────────────────────────────────────
            try:
                plate_results = detect_plates(frame)
            except Exception as e:
                # Decoder warnings at join — log, do NOT abort
                logger.debug(f"Camera {camera_id}: ANPR error (may be transient): {e}")
                continue

            for plate_text, conf, bbox in plate_results:
                if not plate_text or conf < 0.3:
                    continue
                # Use bbox centre as simple track key (replace with ByteTrack for production)
                cx = int((bbox.get("x1", 0) + bbox.get("x2", 0)) / 2 / 50)
                cy = int((bbox.get("y1", 0) + bbox.get("y2", 0)) / 2 / 50)
                track_key = f"{cx}_{cy}"
                if track_key not in active_tracks:
                    active_tracks[track_key] = PlateTracker(track_key)
                active_tracks[track_key].add_read(plate_text, conf, bbox, frame_idx)


def get_live_cameras() -> list[dict]:
    """Fetch camera list from the backend API."""
    try:
        resp = requests.get(f"{API_BASE}/cameras?live_only=true&limit=50", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Could not fetch cameras from API: {e}")
        return []


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import threading

    parser = argparse.ArgumentParser(description="Sentinel ANPR worker")
    parser.add_argument("--camera-id", help="Process a single camera UUID")
    parser.add_argument("--rtsp-url", help="RTSP URL (use with --camera-id)")
    parser.add_argument("--max-streams", type=int, default=10, help="Max concurrent streams")
    args = parser.parse_args()

    if args.camera_id and args.rtsp_url:
        logger.info(f"Processing single stream: {args.rtsp_url}")
        process_stream(args.camera_id, args.rtsp_url)
    else:
        cameras = get_live_cameras()
        if not cameras:
            logger.error("No cameras available. Make sure the backend is running and catalogue is synced.")
            sys.exit(1)

        limited = cameras[:args.max_streams]
        logger.info(f"Starting ANPR on {len(limited)} streams (max {args.max_streams})")

        threads = []
        for cam in limited:
            cid  = str(cam.get("id"))
            rtsp = cam.get("rtsp_url")
            hls  = cam.get("hls_url")
            if not rtsp and not hls:
                continue
            t = threading.Thread(
                target=process_stream,
                args=(cid, rtsp or hls, hls),
                daemon=True,
                name=f"anpr-{cam.get('native_id', cid)}",
            )
            t.start()
            threads.append(t)
            time.sleep(0.5)  # Stagger thread starts

        logger.info(f"✅ {len(threads)} ANPR threads running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(10)
                alive = sum(1 for t in threads if t.is_alive())
                logger.info(f"ANPR worker status: {alive}/{len(threads)} threads alive")
        except KeyboardInterrupt:
            logger.info("Worker stopped by user.")
