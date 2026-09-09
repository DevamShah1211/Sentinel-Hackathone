"""
Tests for the general object-detection tier.

These deliberately do NOT load the model. It is a 114 MB download, and a test
suite that needs it cannot run on a fresh checkout or in CI — so the contract
around the model is tested here, and the model itself is measured in
DOCS/MEASUREMENTS.md against real frames.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.object_detection import (
    MIN_CONFIDENCE,
    SceneAggregator,
    PERSON_CLASSES,
    TRACKED_CLASSES,
    VEHICLE_CLASSES,
    ObjectDetection,
    ObjectDetector,
    summarise,
)


def _det(label: str, conf: float = 0.8, bbox=(0, 0, 40, 40)) -> ObjectDetection:
    return ObjectDetection(label=label, confidence=conf, bbox=bbox)


class TestCategories:
    """The UI and the alert rules group on category, not on COCO's taxonomy."""

    @pytest.mark.parametrize("label", sorted(VEHICLE_CLASSES))
    def test_vehicles_group_as_vehicle(self, label):
        assert _det(label).category == "vehicle"

    @pytest.mark.parametrize("label", sorted(PERSON_CLASSES))
    def test_people_group_as_person(self, label):
        assert _det(label).category == "person"

    def test_auto_rickshaws_are_documented_as_trucks(self):
        """
        COCO has no auto-rickshaw class and the detector puts them in 'truck'
        consistently. The behaviour is documented rather than relabelled — see
        the module docstring — so this asserts the grouping we actually ship.
        """
        assert "truck" in VEHICLE_CLASSES
        assert _det("truck").category == "vehicle"

    def test_untracked_labels_keep_their_own_name(self):
        assert _det("boat").category == "boat"


class TestSummarise:
    """
    'person' is both a category and a label. A single flat dictionary
    double-counted it — five people reported as ten — which is the kind of quiet
    arithmetic error that survives review and reaches a report.
    """

    def test_person_is_not_double_counted(self):
        result = summarise([_det("person"), _det("person"), _det("car")])
        assert result["category"] == {"person": 2, "vehicle": 1}
        assert result["label"] == {"person": 2, "car": 1}
        assert result["total"] == 3

    def test_matches_a_real_frame_shape(self):
        """The counts measured on sandbox frame cam10: 7 vehicles, 5 people."""
        dets = ([_det("car")] * 2 + [_det("motorcycle")] * 4 + [_det("truck")]
                + [_det("person")] * 5)
        result = summarise(dets)
        assert result["category"]["vehicle"] == 7
        assert result["category"]["person"] == 5
        assert result["total"] == 12

    def test_empty_input(self):
        assert summarise([]) == {"category": {}, "label": {}, "total": 0}


class TestFiltering:
    """Noise excluded before it reaches the index, not after."""

    def test_only_tracked_classes_are_admitted(self):
        # COCO emits 80 classes; a control room acts on a handful of them.
        assert "potted plant" not in TRACKED_CLASSES
        assert "car" in TRACKED_CLASSES
        assert "person" in TRACKED_CLASSES

    def test_confidence_floor_is_set_from_measurement(self):
        # Genuine objects on the sandbox frames scored 0.5-0.85; spurious boxes
        # sat below 0.4. The floor sits between those populations.
        assert 0.4 <= MIN_CONFIDENCE <= 0.5

    def test_detector_accepts_a_custom_class_set(self):
        """A deployment watching only for people should not pay for vehicles."""
        detector = ObjectDetector(classes={"person"})
        assert detector.classes == frozenset({"person"})


class TestDetectorIsSafeToCall:
    """A bad frame must never take a stream down."""

    def test_empty_frame_returns_nothing_without_loading_the_model(self):
        detector = ObjectDetector()
        assert detector.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []
        assert detector.detect(None) == []
        # The 114 MB session was never loaded, which is the point of the guard.
        assert detector._detector is None

    def test_model_is_not_loaded_at_construction(self):
        """
        Lazy loading matters: importing this module must not block a web request
        or fail a test that never detects anything.
        """
        assert ObjectDetector()._detector is None


class TestGeometry:
    def test_area(self):
        assert _det("car", bbox=(10, 10, 30, 50)).area == 800

    def test_degenerate_box_has_no_area(self):
        assert _det("car", bbox=(30, 30, 10, 10)).area == 0


class TestSceneAggregator:
    """
    The aggregator is what makes this tier affordable: inference per frame,
    writes per bucket. At one inference per second across 80,000 cameras,
    per-frame rows would be 6.9 billion a day; a minute bucket is 115 million.
    """

    def test_peak_not_sum(self):
        """
        Summing across frames counts a parked car once per frame and produces a
        number that grows with sampling rate rather than with traffic.
        """
        agg = SceneAggregator(bucket_seconds=60)
        agg.add([_det("car")] * 3, 0)
        agg.add([_det("car")] * 5, 20)
        agg.add([_det("car")] * 2, 40)

        bucket = agg.flush()
        assert bucket["counts_by_label"]["car"] == 5, "peak, not 10"
        assert bucket["frames_sampled"] == 3

    def test_bucket_closes_on_boundary(self):
        agg = SceneAggregator(bucket_seconds=60)
        assert agg.add([_det("car")], 10) is None
        closed = agg.add([_det("person")], 61)

        assert closed is not None
        assert closed["bucket_start"] == 0
        assert closed["counts_by_label"] == {"car": 1}

    def test_frames_sampled_disambiguates_an_empty_bucket(self):
        """
        A count of zero is ambiguous without it: nothing was there, or nothing
        was looked at.
        """
        agg = SceneAggregator(bucket_seconds=60)
        agg.add([], 0)
        agg.add([], 30)

        bucket = agg.flush()
        assert bucket["frames_sampled"] == 2
        assert bucket["counts_by_label"] == {}

    def test_flush_on_nothing_returns_none(self):
        assert SceneAggregator().flush() is None

    def test_flush_resets_state(self):
        agg = SceneAggregator(bucket_seconds=60)
        agg.add([_det("car")], 0)
        agg.flush()
        assert agg.flush() is None, "a flushed bucket must not be emitted twice"

    def test_categories_and_labels_both_peak(self):
        agg = SceneAggregator(bucket_seconds=60)
        agg.add([_det("car"), _det("motorcycle")], 0)      # vehicle: 2
        agg.add([_det("car")] * 3, 30)                     # vehicle: 3

        bucket = agg.flush()
        assert bucket["counts_by_category"]["vehicle"] == 3
        assert bucket["counts_by_label"]["car"] == 3
        assert bucket["counts_by_label"]["motorcycle"] == 1

    def test_max_confidence_is_kept_for_triage(self):
        agg = SceneAggregator(bucket_seconds=60)
        agg.add([_det("car", conf=0.51)], 0)
        agg.add([_det("car", conf=0.93)], 10)
        assert agg.flush()["max_confidence"] == pytest.approx(0.93)
