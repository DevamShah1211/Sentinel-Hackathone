"""
General object detection — vehicles, people, and the classes a control room acts on.

ANPR answers "which vehicle", and it only works where a plate is legible. This
answers "what is in view", and it works at the framing the government cameras
actually have. The submission asks for both, and the sweep in MEASUREMENTS §2g
is the reason the second one matters: across all thirty sandbox cameras not one
produced a readable plate, while the same frames contain cars, motorcycles,
auto-rickshaws and pedestrians that a detector resolves comfortably. A camera
that cannot do ANPR is not a camera that cannot do analytics.

**Model.** `rf-detr-nano-384-coco`, run through ONNX Runtime on CPU — the same
runtime and the same constraint as the plate pipeline. No GPU, no training, no
frame leaving the deployment. Measured at ~70 ms per 1920x1080 frame on this
machine, single-threaded. That is what makes the tiered design in HLD §9.4
work: this tier is cheap enough to run on cameras the ANPR tier cannot serve.

**Classes.** COCO's 80 classes, filtered to the ones a surveillance operator has
a decision to make about. The rest are not wrong, they are noise: a control room
does not need to know about potted plants, and every class admitted is a class
that can produce a false alert at three in the morning.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Iterable

import numpy as np

logger = logging.getLogger("sentinel.objects")

# The model. Measured on a real sandbox frame (1920x1080, cam10) on this CPU:
#
#   rf-detr-nano-384-coco     66 ms   12 objects
#   rf-detr-small-512-coco   126 ms   15 objects
#
# Nano is 1.9x cheaper and finds 12 of the 15. The three it misses are small and
# distant — the same objects the operator cannot act on anyway — and the whole
# argument for this tier is that it runs on cameras ANPR cannot serve, which
# means cost per frame is the property being optimised. Small is the right
# default if a deployment has GPUs; the switch is one argument.
DEFAULT_MODEL = "rf-detr-nano-384-coco"

# What a control room acts on, grouped so the UI and the alerting rules do not
# each have to know the COCO taxonomy.
#
# 'truck' carries auto-rickshaws on Indian roads — COCO has no class for one, and
# the detector puts them there consistently. Documented rather than renamed,
# because silently relabelling a model's output is how a system starts lying
# about what it saw.
VEHICLE_CLASSES = frozenset({"car", "motorcycle", "bus", "truck", "bicycle", "train"})
PERSON_CLASSES = frozenset({"person"})

# Classes admitted at all. Everything else COCO can emit is dropped before it
# reaches the index.
TRACKED_CLASSES = VEHICLE_CLASSES | PERSON_CLASSES

# Below this a detection is not worth an operator's attention. Chosen from the
# real sandbox frames: genuine vehicles and people scored 0.5-0.85, while the
# handful of spurious boxes sat below 0.4.
MIN_CONFIDENCE = 0.45


@dataclass(frozen=True)
class ObjectDetection:
    """One detected object in full-frame coordinates."""
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]

    @property
    def category(self) -> str:
        """'vehicle', 'person', or the raw label — what the UI groups on."""
        if self.label in VEHICLE_CLASSES:
            return "vehicle"
        if self.label in PERSON_CLASSES:
            return "person"
        return self.label

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)


class ObjectDetector:
    """
    Wraps the COCO detector with the filtering a surveillance system needs.

    Loaded lazily and shared across cameras: the ONNX session is ~114 MB, and one
    per stream would exhaust memory long before it exhausted CPU. The session is
    serialised behind a lock for the same reason as the plate detector — ONNX
    Runtime sessions are not documented as thread-safe.
    """

    def __init__(self, model: str = DEFAULT_MODEL,
                 min_confidence: float = MIN_CONFIDENCE,
                 classes: Iterable[str] | None = None):
        self.model_name = model
        self.min_confidence = min_confidence
        self.classes = frozenset(classes) if classes is not None else TRACKED_CLASSES
        self._detector = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """
        Load on first use, not at import.

        The model is a 114 MB download on a cold machine. Importing this module
        should not block a web request or fail a unit test that never detects
        anything.
        """
        if self._detector is None:
            import open_image_models as oim
            self._detector = oim.create_detector(self.model_name)
            logger.info("Object detector ready (%s)", self.model_name)
        return self._detector

    def detect(self, frame: np.ndarray) -> list[ObjectDetection]:
        """Return the tracked objects in one frame, in full-frame coordinates."""
        if frame is None or frame.size == 0:
            return []

        detector = self._ensure_loaded()
        try:
            with self._lock:
                raw = detector.predict(frame)
        except Exception as exc:                      # never kill a stream
            logger.debug("Object inference failed: %s", exc)
            return []

        # The library returns either a flat list or one list per batched image.
        items = raw[0] if raw and isinstance(raw[0], list) else raw

        out: list[ObjectDetection] = []
        for item in items or []:
            label = getattr(item, "label", None) or getattr(item, "class_name", "")
            confidence = float(getattr(item, "confidence", 0.0))
            if label not in self.classes or confidence < self.min_confidence:
                continue
            box = getattr(item, "bounding_box", None)
            if box is None:
                continue
            out.append(ObjectDetection(
                label=label,
                confidence=confidence,
                bbox=(int(box.x1), int(box.y1), int(box.x2), int(box.y2)),
            ))
        return out


def summarise(detections: list[ObjectDetection]) -> dict[str, dict[str, int]]:
    """
    Counts by category and by label, in separate maps.

    Both, deliberately: "vehicles: 7" is what an operator reads at a glance, and
    "motorcycle: 4" is what a traffic engineer needs.

    They are separate maps because 'person' is both a category and a label, so a
    single flat dictionary double-counted it — five people were reported as ten,
    which is exactly the kind of quiet arithmetic error that survives review and
    ends up in a report. Nesting makes the collision impossible rather than
    merely unlikely.

        {"category": {"vehicle": 7, "person": 5},
         "label":    {"car": 2, "motorcycle": 4, "truck": 1, "person": 5},
         "total":    12}
    """
    by_category: dict[str, int] = {}
    by_label: dict[str, int] = {}
    for d in detections:
        by_category[d.category] = by_category.get(d.category, 0) + 1
        by_label[d.label] = by_label.get(d.label, 0) + 1
    return {"category": by_category, "label": by_label, "total": len(detections)}


# ─── Bucketed aggregation ─────────────────────────────────────────────────────

class SceneAggregator:
    """
    Collapses per-frame detections into one row per camera per minute.

    This is the piece that makes the tier affordable at scale. Inference happens
    per frame; writes happen per bucket. At one inference per second across
    80,000 cameras, per-frame rows would be 6.9 billion a day — the aggregation
    turns that into 115 million, and the database load stops depending on frame
    rate at all.

    **Peak, not sum.** Within a bucket the count kept per class is the highest
    seen in any single frame, not the total across frames. Summing counts a
    parked car once per frame — sixty times a minute — and produces a number
    that grows with sampling rate rather than with traffic. Peak answers "how
    many were there at once", which is the question a junction count is asking.
    """

    def __init__(self, bucket_seconds: int = 60):
        self.bucket_seconds = bucket_seconds
        self._bucket_key: int | None = None
        self._frames = 0
        self._peak_label: dict[str, int] = {}
        self._peak_category: dict[str, int] = {}
        self._max_confidence = 0.0

    def _key(self, at: float) -> int:
        return int(at // self.bucket_seconds) * self.bucket_seconds

    def add(self, detections: list[ObjectDetection], at: float) -> dict | None:
        """
        Record one frame. Returns the completed bucket when this frame opens a
        new one, otherwise None.

        Returning the closed bucket rather than writing it here keeps this class
        free of any database dependency, which is what lets it be unit-tested
        without one.
        """
        key = self._key(at)
        closed = None
        if self._bucket_key is None:
            self._bucket_key = key
        elif key != self._bucket_key:
            closed = self.flush()
            self._bucket_key = key

        self._frames += 1
        summary = summarise(detections)
        for label, n in summary["label"].items():
            self._peak_label[label] = max(self._peak_label.get(label, 0), n)
        for category, n in summary["category"].items():
            self._peak_category[category] = max(self._peak_category.get(category, 0), n)
        for d in detections:
            self._max_confidence = max(self._max_confidence, d.confidence)
        return closed

    def flush(self) -> dict | None:
        """Close the current bucket and return it, or None if nothing was seen."""
        if self._bucket_key is None or self._frames == 0:
            return None
        bucket = {
            "bucket_start": self._bucket_key,
            "bucket_seconds": self.bucket_seconds,
            "frames_sampled": self._frames,
            "counts_by_label": dict(self._peak_label),
            "counts_by_category": dict(self._peak_category),
            "max_confidence": round(self._max_confidence, 4),
        }
        self._frames = 0
        self._peak_label = {}
        self._peak_category = {}
        self._max_confidence = 0.0
        return bucket
