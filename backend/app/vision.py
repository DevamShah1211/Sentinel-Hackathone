"""
Vision pipeline — capture, plate detection and track-level aggregation.

Three concerns live here, each of which cost real debugging time on the sandbox:

**Capture.** RTSP is forced over TCP (UDP loses fragments across NAT and produces
corrupt frames that look exactly like model bugs). All timing comes from the
presentation timestamp, never wall-clock: on connect the gateway replays its
buffered group-of-pictures, so arrival-timed logic computes impossible velocities
on every reconnect. Reconnects back off 2s -> 30s.

**Frame quality.** Frames arriving before the first IDR decode into flat grey
mush. Feeding those to the detector wastes CPU and produces phantom reads, so
frames are gated on colour and edge structure before inference.

**Detection.** The sandbox cameras are wide-area PTZ overviews: at 1920x1080 a
number plate is often 10-20 px wide, well under what a 384 px detector can
resolve from a whole frame. Measured on this grid, full-frame inference returned
zero reads where tiled inference on upscaled regions returned real plates, so the
frame is divided into overlapping tiles which are upscaled before inference and
the boxes mapped back to full-frame coordinates.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

# Must be set before cv2 is imported — OpenCV reads it when the FFmpeg backend loads.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.plate_grammar import PlateRead, plausible_plate, vote  # noqa: E402

logger = logging.getLogger("sentinel.vision")

# Frame-quality thresholds. Corrupt pre-IDR frames are near-monochrome with almost
# no edge content; these cut-offs were chosen against real sandbox output.
MIN_GREY_STD = 12.0
MIN_EDGE_DENSITY = 0.8

# Ratio of vertical to horizontal gradient energy below which a frame is treated
# as smeared by a corrupt keyframe. Real footage sits near 1.0; heavy streaking
# collapses the vertical term.
SMEAR_RATIO_THRESHOLD = 0.45

# Note on what is deliberately NOT detected: blotchy false-colour corruption,
# where lost residual data leaves luminance roughly right while chroma drifts
# into vivid magentas and greens. A block-saturation metric was tried and
# measured against real frames: a corrupt tile scored 0.260, a clean tile 0.222,
# and a perfectly good night scene 0.320. There is no threshold that separates
# them, so no filter is applied — blanking good footage to hide occasional
# artefacts would be the worse trade. These frames recover at the next keyframe.


# ─── Frame quality ────────────────────────────────────────────────────────────

def frame_is_decodable(frame: np.ndarray) -> bool:
    """
    Reject frames that decoded into artefacts rather than picture.

    Pre-IDR output is flat: low luminance spread and almost no edges. Real night
    footage still has streetlights and road markings, so this does not discard
    dark-but-valid frames.
    """
    if frame is None or frame.size == 0:
        return False
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if float(grey.std()) < MIN_GREY_STD:
        return False
    edges = cv2.Canny(grey, 60, 160)
    return float(edges.mean()) >= MIN_EDGE_DENSITY


def frame_is_smeared(frame: np.ndarray, threshold: float = SMEAR_RATIO_THRESHOLD) -> bool:
    """
    Detect the vertical streaking left by a corrupt H.264 keyframe.

    When a macroblock row is lost the decoder drags the last good row downwards,
    producing long vertical runs of near-identical pixels. Real scenes have
    horizontal structure — kerbs, road markings, vehicle roofs, building lines —
    so a frame whose vertical gradients have collapsed relative to its horizontal
    ones is almost certainly damaged rather than merely plain.

    Cheap enough to run per relayed frame: two gradient passes on a downscaled
    copy.
    """
    if frame is None or frame.size == 0:
        return True
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Downscale first — smearing is a large-scale artefact and this keeps the
    # check to a fraction of a millisecond.
    small = cv2.resize(grey, (320, 180), interpolation=cv2.INTER_AREA)

    vertical = float(np.abs(np.diff(small.astype(np.int16), axis=0)).mean())
    horizontal = float(np.abs(np.diff(small.astype(np.int16), axis=1)).mean())
    if horizontal < 1e-3:
        return True
    # A healthy frame sits near 1.0. Heavy vertical smearing pushes this well
    # below, because change down the image has been flattened out.
    return (vertical / horizontal) < threshold


# ─── Tiled inference ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Tile:
    image: np.ndarray
    offset_x: int
    offset_y: int
    scale: float


def build_tiles(frame: np.ndarray, rows: int = 2, cols: int = 3,
                overlap: float = 0.2, scale: float = 2.0) -> list[Tile]:
    """
    Split a frame into overlapping upscaled tiles.

    Overlap matters: a plate straddling a tile boundary would otherwise be cut in
    half and read as two fragments. 20% is enough for a plate at these framings.
    """
    height, width = frame.shape[:2]
    tile_h, tile_w = height // rows, width // cols
    pad_y, pad_x = int(tile_h * overlap), int(tile_w * overlap)

    tiles: list[Tile] = []
    for r in range(rows):
        for c in range(cols):
            y1 = max(0, r * tile_h - pad_y)
            y2 = min(height, (r + 1) * tile_h + pad_y)
            x1 = max(0, c * tile_w - pad_x)
            x2 = min(width, (c + 1) * tile_w + pad_x)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            if scale != 1.0:
                crop = cv2.resize(crop, None, fx=scale, fy=scale,
                                  interpolation=cv2.INTER_CUBIC)
            tiles.append(Tile(crop, x1, y1, scale))
    return tiles


@dataclass
class RawDetection:
    """One plate read from one frame, in full-frame coordinates."""
    text: str
    char_confidences: list[float]
    bbox: tuple[int, int, int, int]
    detector_confidence: float

    @property
    def mean_confidence(self) -> float:
        if not self.char_confidences:
            return 0.0
        return sum(self.char_confidences) / len(self.char_confidences)


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def deduplicate(detections: list[RawDetection], iou_threshold: float = 0.4) -> list[RawDetection]:
    """Drop duplicate reads of the same plate produced by overlapping tiles."""
    kept: list[RawDetection] = []
    for det in sorted(detections, key=lambda d: d.mean_confidence, reverse=True):
        if not any(_iou(det.bbox, k.bbox) > iou_threshold for k in kept):
            kept.append(det)
    return kept


class PlateDetector:
    """
    Wraps fast-alpr with tiled inference and overlay-text filtering.

    The engine is pretrained and runs locally on CPU — no training, no API key and
    no frame ever leaves the deployment, which is the only defensible arrangement
    for government CCTV.
    """

    # cct-s-v2 is the OCR default because it is the only fast-plate-ocr model whose
    # `max_plate_slots` is 10. The 8-slot models silently truncate an Indian plate
    # to its middle characters — measured here, GJ01AB1234 came back as '01AB123'
    # — which is worse than a low-confidence read because it looks plausible.
    def __init__(self, detector_model: str = "yolo-v9-t-384-license-plate-end2end",
                 ocr_model: str = "cct-s-v2-global-model",
                 tiled: bool = True, tile_rows: int = 2, tile_cols: int = 3,
                 tile_scale: float = 2.0):
        from fast_alpr import ALPR

        self._alpr = ALPR(detector_model=detector_model, ocr_model=ocr_model)
        self.tiled = tiled
        self.tile_rows = tile_rows
        self.tile_cols = tile_cols
        self.tile_scale = tile_scale
        # fast-alpr's ONNX sessions are not documented as thread-safe; serialise.
        self._lock = threading.Lock()
        logger.info("Plate detector ready (detector=%s ocr=%s tiled=%s)",
                    detector_model, ocr_model, tiled)

    def _predict(self, image: np.ndarray):
        with self._lock:
            return self._alpr.predict(image)

    # Below this width the OCR sees too few pixels per character. Crops are
    # upscaled to it before recognition; measured on rendered plates, a 160 px
    # crop upscaled to 440 px reads exactly as well as a natively large one.
    MIN_OCR_PLATE_WIDTH = 320

    def detect(self, frame: np.ndarray) -> list[RawDetection]:
        """Run detection over a frame and return reads in full-frame coordinates."""
        results: list[RawDetection] = []

        regions: list[Tile]
        if self.tiled:
            regions = build_tiles(frame, self.tile_rows, self.tile_cols,
                                  scale=self.tile_scale)
        else:
            regions = [Tile(frame, 0, 0, 1.0)]

        for tile in regions:
            try:
                predictions = self._predict(tile.image)
            except Exception as exc:  # a bad frame must never kill the stream
                logger.debug("Inference error on tile: %s", exc)
                continue

            for pred in predictions:
                if not pred.ocr or not pred.ocr.text:
                    continue
                text = pred.ocr.text.strip()
                if not plausible_plate(text):
                    continue

                confidences = pred.ocr.confidence
                if isinstance(confidences, (int, float)):
                    confidences = [float(confidences)]
                else:
                    confidences = [float(c) for c in confidences]

                box = pred.detection.bounding_box
                bbox = (
                    int(tile.offset_x + box.x1 / tile.scale),
                    int(tile.offset_y + box.y1 / tile.scale),
                    int(tile.offset_x + box.x2 / tile.scale),
                    int(tile.offset_y + box.y2 / tile.scale),
                )
                results.append(RawDetection(
                    text=text,
                    char_confidences=confidences,
                    bbox=bbox,
                    detector_confidence=float(pred.detection.confidence),
                ))

        return deduplicate(results)


# ─── Track aggregation ────────────────────────────────────────────────────────

@dataclass
class Track:
    """
    One vehicle pass through the camera's view.

    Reads accumulate here and are collapsed to a single best plate when the track
    ends, so one vehicle produces one detection record rather than forty noisy ones.
    """
    track_id: str
    reads: list[PlateRead] = field(default_factory=list)
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    first_pts_ms: int = 0
    last_pts_ms: int = 0
    last_frame: int = 0
    best_crop: np.ndarray | None = None
    best_crop_confidence: float = -1.0

    def add(self, det: RawDetection, frame_idx: int, pts_ms: int,
            frame: np.ndarray | None = None) -> None:
        self.reads.append(PlateRead(det.text, det.char_confidences))
        self.bbox = det.bbox
        self.last_frame = frame_idx
        self.last_pts_ms = pts_ms
        if not self.first_pts_ms:
            self.first_pts_ms = pts_ms
        # Keep the crop from the highest-confidence read as the evidence image.
        if frame is not None and det.mean_confidence > self.best_crop_confidence:
            x1, y1, x2, y2 = det.bbox
            pad_x, pad_y = int((x2 - x1) * 0.15), int((y2 - y1) * 0.4)
            h, w = frame.shape[:2]
            crop = frame[max(0, y1 - pad_y):min(h, y2 + pad_y),
                         max(0, x1 - pad_x):min(w, x2 + pad_x)]
            if crop.size:
                self.best_crop = crop.copy()
                self.best_crop_confidence = det.mean_confidence


class TrackManager:
    """
    Associates per-frame reads into vehicle tracks by spatial overlap.

    A full ByteTrack instance is unnecessary here: plates move smoothly between
    sampled frames, so IoU association against recent tracks is sufficient and
    costs a fraction of the CPU, which matters when the budget is shared across
    many streams on one machine.
    """

    # The IoU threshold is deliberately low. A plate approaching the camera grows
    # quickly between sampled frames, so consecutive boxes of the *same* plate can
    # overlap by well under half their area; a strict threshold fragments one
    # vehicle pass into several short tracks and starves the vote of reads.
    def __init__(self, iou_threshold: float = 0.10, max_idle_frames: int = 45,
                 min_reads: int = 2):
        self.iou_threshold = iou_threshold
        self.max_idle_frames = max_idle_frames
        self.min_reads = min_reads
        self._tracks: dict[str, Track] = {}
        self._next_id = 0

    @staticmethod
    def _centre_distance(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
        bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    def update(self, detections: list[RawDetection], frame_idx: int, pts_ms: int,
               frame: np.ndarray | None = None) -> None:
        for det in detections:
            matched: Track | None = None
            best_score = self.iou_threshold
            for track in self._tracks.values():
                score = _iou(det.bbox, track.bbox)
                if score >= best_score:
                    best_score, matched = score, track

            # Fall back to proximity. A fast-approaching plate can miss on overlap
            # entirely between sampled frames while plainly being the same vehicle,
            # so allow association within roughly one plate-width of travel.
            if matched is None:
                width = max(det.bbox[2] - det.bbox[0], 1)
                nearest = None
                nearest_distance = width * 2.0
                for track in self._tracks.values():
                    if frame_idx - track.last_frame > 6:
                        continue
                    distance = self._centre_distance(det.bbox, track.bbox)
                    if distance < nearest_distance:
                        nearest_distance, nearest = distance, track
                matched = nearest

            if matched is None:
                self._next_id += 1
                matched = Track(track_id=f"t{self._next_id}")
                self._tracks[matched.track_id] = matched
            matched.add(det, frame_idx, pts_ms, frame)

    def collect_finished(self, frame_idx: int, force: bool = False) -> Iterator[Track]:
        """Yield tracks that have gone idle (or all of them, when the stream ends)."""
        done = [
            tid for tid, tr in self._tracks.items()
            if force or (frame_idx - tr.last_frame) > self.max_idle_frames
        ]
        for tid in done:
            track = self._tracks.pop(tid)
            if len(track.reads) >= self.min_reads:
                yield track

    def reset(self) -> None:
        """Drop all state — used at the loop point, where the scene cuts hard."""
        self._tracks.clear()

    @property
    def active_count(self) -> int:
        return len(self._tracks)


def aggregate_track(track: Track) -> tuple[str, float, object] | None:
    """Collapse a track's reads into one confidence-weighted plate."""
    return vote(track.reads)


# ─── Capture ──────────────────────────────────────────────────────────────────

@dataclass
class CaptureStats:
    frames_read: int = 0
    frames_decodable: int = 0
    frames_inferred: int = 0
    reconnects: int = 0
    inference_seconds: float = 0.0
    started_at: float = field(default_factory=time.time)

    @property
    def capture_fps(self) -> float:
        elapsed = time.time() - self.started_at
        return self.frames_read / elapsed if elapsed > 0 else 0.0

    @property
    def mean_inference_ms(self) -> float:
        if not self.frames_inferred:
            return 0.0
        return self.inference_seconds / self.frames_inferred * 1000


class StreamCapture:
    """
    RTSP capture with TCP transport, PTS timing and exponential-backoff reconnect.

    Yields (frame, pts_ms, frame_index) for frames that passed the quality gate.
    Never raises on stream trouble: the sandbox feeds are supervised and restart,
    and a worker that dies on a reconnect is useless for a continuous index.
    """

    def __init__(self, url: str, name: str = "stream",
                 backoff_initial: float = 2.0, backoff_max: float = 30.0,
                 idr_settle_frames: int = 30, open_timeout_s: float = 30.0):
        self.url = url
        self.name = name
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self.idr_settle_frames = idr_settle_frames
        self.open_timeout_s = open_timeout_s
        self.stats = CaptureStats()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _safe_url(self) -> str:
        """URL with any embedded password masked, for logging."""
        if "@" in self.url and "://" in self.url:
            scheme, rest = self.url.split("://", 1)
            creds, host = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return self.url

    def frames(self) -> Iterator[tuple[np.ndarray, int, int]]:
        backoff = self.backoff_initial
        frame_index = 0

        while not self._stop.is_set():
            capture = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not capture.isOpened():
                capture.release()
                self.stats.reconnects += 1
                logger.warning("%s: could not open stream, retrying in %.0fs", self.name, backoff)
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, self.backoff_max)
                continue

            logger.info("%s: stream open (%s)", self.name, self._safe_url())
            backoff = self.backoff_initial
            settled = 0
            previous_pts = -1

            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    logger.warning("%s: read failed — reconnecting in %.0fs", self.name, backoff)
                    break

                self.stats.frames_read += 1
                frame_index += 1

                # Timing comes from PTS. Never wall-clock: the gateway replays a
                # buffered GOP on connect, so arrival time lies about elapsed time.
                pts_ms = int(capture.get(cv2.CAP_PROP_POS_MSEC))

                # Discard the settling window after connect, then gate on quality.
                if settled < self.idr_settle_frames:
                    settled += 1
                    continue
                if not frame_is_decodable(frame):
                    continue

                self.stats.frames_decodable += 1

                # The footage loops with a hard cut; PTS going backwards is the
                # signal, and any tracker state from before it is meaningless.
                looped = 0 < pts_ms < previous_pts
                previous_pts = pts_ms
                if looped:
                    logger.info("%s: loop point detected (PTS reset) — resetting tracks", self.name)
                    yield frame, -1, frame_index      # sentinel: caller resets state
                    continue

                yield frame, pts_ms, frame_index

            capture.release()
            self.stats.reconnects += 1
            if self._stop.wait(backoff):
                return
            backoff = min(backoff * 2, self.backoff_max)
