"""
Tests for the capture and tracking layer.

These deliberately avoid loading the ONNX models: they cover the logic that
surrounds inference — frame-quality gating, tiling geometry, deduplication and
track association — which is where the sandbox-specific bugs actually lived.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.plate_grammar import PlateRead

from app.vision import (
    MIN_ALERTABLE_PX_PER_CHAR,
    RawDetection,
    frame_is_smeared,
    Track,
    TrackManager,
    build_tiles,
    deduplicate,
    frame_is_decodable,
    read_is_alertable,
)


def _detection(text: str, bbox: tuple[int, int, int, int],
               confidence: float = 0.9) -> RawDetection:
    return RawDetection(text=text, char_confidences=[confidence] * len(text),
                        bbox=bbox, detector_confidence=confidence)


class TestFrameQuality:
    def test_flat_grey_frame_is_rejected(self) -> None:
        # Pre-IDR decoder output looks like this: uniform, no structure.
        assert not frame_is_decodable(np.full((480, 640, 3), 128, np.uint8))

    def test_pure_black_frame_is_rejected(self) -> None:
        assert not frame_is_decodable(np.zeros((480, 640, 3), np.uint8))

    def test_empty_and_none_are_rejected(self) -> None:
        assert not frame_is_decodable(None)
        assert not frame_is_decodable(np.zeros((0, 0, 3), np.uint8))

    def test_structured_frame_is_accepted(self) -> None:
        frame = np.zeros((480, 640, 3), np.uint8)
        # Hard-edged blocks give both luminance spread and edge content.
        frame[:240, :320] = 235
        frame[240:, 320:] = 200
        frame[100:150, 400:600] = 30
        assert frame_is_decodable(frame)

    def test_dark_but_real_night_frame_is_accepted(self) -> None:
        # A night scene is dim but still has streetlights and markings; it must
        # not be discarded along with the corrupt frames.
        rng = np.random.default_rng(3)
        frame = rng.integers(0, 40, (480, 640, 3), dtype=np.uint8)
        frame[200:210, 100:540] = 255      # lane marking
        frame[50:70, 60:90] = 250          # streetlight
        assert frame_is_decodable(frame)


class TestTiling:
    def test_tile_count_matches_grid(self) -> None:
        tiles = build_tiles(np.zeros((720, 1280, 3), np.uint8), rows=2, cols=3)
        assert len(tiles) == 6

    def test_tiles_are_upscaled_by_the_requested_factor(self) -> None:
        frame = np.zeros((720, 1280, 3), np.uint8)
        plain = build_tiles(frame, rows=2, cols=3, overlap=0.0, scale=1.0)[0]
        scaled = build_tiles(frame, rows=2, cols=3, overlap=0.0, scale=2.0)[0]
        assert scaled.image.shape[0] == plain.image.shape[0] * 2
        assert scaled.scale == 2.0

    def test_tiles_overlap_so_a_plate_on_a_seam_survives(self) -> None:
        tiles = build_tiles(np.zeros((720, 1280, 3), np.uint8),
                            rows=1, cols=2, overlap=0.2, scale=1.0)
        left, right = tiles[0], tiles[1]
        left_edge = left.offset_x + left.image.shape[1]
        assert left_edge > right.offset_x, "adjacent tiles must overlap"

    def test_offsets_allow_mapping_back_to_full_frame(self) -> None:
        tiles = build_tiles(np.zeros((720, 1280, 3), np.uint8),
                            rows=2, cols=2, overlap=0.0, scale=2.0)
        for tile in tiles:
            assert 0 <= tile.offset_x < 1280
            assert 0 <= tile.offset_y < 720


class TestDeduplication:
    def test_overlapping_reads_collapse_to_the_most_confident(self) -> None:
        kept = deduplicate([
            _detection("GJ01AB1234", (100, 100, 200, 130), 0.95),
            _detection("GJ01AB1Z34", (104, 102, 204, 132), 0.60),
        ])
        assert len(kept) == 1
        assert kept[0].text == "GJ01AB1234"

    def test_distinct_vehicles_are_both_kept(self) -> None:
        kept = deduplicate([
            _detection("GJ01AB1234", (100, 100, 200, 130)),
            _detection("MH12DE1433", (600, 400, 700, 430)),
        ])
        assert len(kept) == 2

    def test_empty_input(self) -> None:
        assert deduplicate([]) == []


class TestTrackManager:
    def test_overlapping_detections_join_one_track(self) -> None:
        manager = TrackManager(min_reads=1)
        manager.update([_detection("GJ01AB1234", (100, 100, 200, 130))], 1, 1000)
        manager.update([_detection("GJ01AB1234", (106, 104, 206, 134))], 2, 1040)
        assert manager.active_count == 1

    def test_fast_approaching_plate_stays_one_track(self) -> None:
        # Boxes that barely overlap must still associate by proximity, otherwise
        # one vehicle pass fragments and the vote is starved of reads.
        manager = TrackManager(min_reads=1)
        manager.update([_detection("GJ01AB1234", (100, 100, 160, 118))], 1, 1000)
        manager.update([_detection("GJ01AB1234", (150, 130, 240, 156))], 2, 1040)
        assert manager.active_count == 1

    def test_distant_detections_start_separate_tracks(self) -> None:
        manager = TrackManager(min_reads=1)
        manager.update([_detection("GJ01AB1234", (100, 100, 200, 130))], 1, 1000)
        manager.update([_detection("MH12DE1433", (900, 600, 1000, 630))], 1, 1000)
        assert manager.active_count == 2

    def test_idle_track_is_emitted(self) -> None:
        manager = TrackManager(min_reads=1, max_idle_frames=5)
        manager.update([_detection("GJ01AB1234", (100, 100, 200, 130))], 1, 1000)
        assert list(manager.collect_finished(3)) == []       # still active
        finished = list(manager.collect_finished(50))
        assert len(finished) == 1
        assert manager.active_count == 0

    def test_tracks_below_min_reads_are_discarded(self) -> None:
        # Single-frame phantom reads must not reach the index.
        manager = TrackManager(min_reads=3, max_idle_frames=5)
        manager.update([_detection("GJ01AB1234", (100, 100, 200, 130))], 1, 1000)
        assert list(manager.collect_finished(50)) == []

    def test_reset_clears_state_at_the_loop_point(self) -> None:
        manager = TrackManager(min_reads=1)
        manager.update([_detection("GJ01AB1234", (100, 100, 200, 130))], 1, 1000)
        manager.reset()
        assert manager.active_count == 0

    def test_track_records_first_and_last_pts(self) -> None:
        track = Track(track_id="t1")
        track.add(_detection("GJ01AB1234", (10, 10, 60, 26)), 1, 5000)
        track.add(_detection("GJ01AB1234", (12, 12, 64, 28)), 2, 5200)
        assert track.first_pts_ms == 5000
        assert track.last_pts_ms == 5200
        assert len(track.reads) == 2


class TestSmearDetection:
    """
    A corrupt H.264 keyframe drags one row of pixels down the image. The result
    still passes the decodable check — it has colour and edges — but is useless to
    look at, so the relay holds the previous frame instead.
    """

    @staticmethod
    def _scene() -> np.ndarray:
        # A frame with horizontal structure, as any real street scene has.
        rng = np.random.default_rng(11)
        frame = np.zeros((360, 640, 3), np.uint8)
        frame[:120] = (150, 140, 130)          # sky
        frame[120:] = (70, 70, 72)             # road
        for x in range(0, 640, 60):
            frame[300:308, x:x + 34] = (235, 235, 230)   # lane markings
        for _ in range(12):
            x, y = int(rng.integers(0, 580)), int(rng.integers(140, 300))
            frame[y:y + 34, x:x + 52] = tuple(int(v) for v in rng.integers(30, 210, 3))
        return frame

    def test_healthy_frame_is_not_smeared(self) -> None:
        assert not frame_is_smeared(self._scene())

    def test_row_dragged_down_is_detected(self) -> None:
        frame = self._scene()
        # Exactly what a lost macroblock row produces.
        frame[120:, :] = frame[120:121, :]
        assert frame_is_smeared(frame)

    def test_empty_and_none_treated_as_unusable(self) -> None:
        assert frame_is_smeared(None)
        assert frame_is_smeared(np.zeros((0, 0, 3), np.uint8))

    def test_uniform_frame_is_rejected(self) -> None:
        # No structure in either direction: nothing worth showing.
        assert frame_is_smeared(np.full((360, 640, 3), 128, np.uint8))


class TestResolutionGate:
    """
    A read from a plate too small to resolve must never raise an alert.

    These are regressions from a real sweep of the government grid on
    8 September 2026, kept because both reads were grammar-valid, confident and
    wrong — the combination that puts an innocent registration in front of an
    officer. Evidence crops are in DOCS/evidence/sweep_20260908/.
    """

    def test_cam10_false_positive_is_not_alertable(self):
        """
        cam10 read "GJ038988" at 0.83 confidence from a plate whose evidence
        crop reads GJ03HR4879. Grammar cannot catch this: a two-letter, two-digit,
        no-series, four-digit registration is a legitimate Indian format. Only the
        size of the thing being read tells us not to believe it.
        """
        track = Track(track_id="cam10")
        for _ in range(6):
            track.add(_detection("GJ038988", (100, 100, 152, 116), 0.83), 1, 40)

        assert track.pixels_per_character == pytest.approx(6.5, abs=0.1)
        assert not read_is_alertable(track)

    def test_cam18_two_line_plate_is_not_alertable(self):
        """
        cam18 flattened a two-line commercial plate into "GJ121181" at 0.466.
        Different cause from cam10 — the recogniser assumes one line — but the
        same consequence, and the same measurement rejects it.
        """
        track = Track(track_id="cam18")
        for _ in range(4):
            track.add(_detection("GJ121181", (200, 300, 249, 316), 0.466), 1, 40)

        assert track.pixels_per_character < MIN_ALERTABLE_PX_PER_CHAR
        assert not read_is_alertable(track)

    def test_well_resolved_plate_is_alertable(self):
        """The gate must not suppress reads from cameras sited for the job."""
        track = Track(track_id="good")
        track.add(_detection("GJ03HR4879", (0, 0, 220, 60), 0.95), 1, 40)

        assert track.pixels_per_character == pytest.approx(22.0)
        assert read_is_alertable(track)

    def test_resolution_measured_at_closest_approach(self):
        """
        Readability is set by the vehicle's closest frame, not by wherever it
        happened to be when the track ended. Measuring the last box would let a
        departing vehicle suppress a read that was clearly resolved on approach.
        """
        track = Track(track_id="approach")
        track.add(_detection("GJ03HR4879", (0, 0, 220, 60), 0.95), 1, 40)
        track.add(_detection("GJ03HR4879", (0, 0, 40, 12), 0.6), 2, 80)

        assert track.widest_box == 220
        assert read_is_alertable(track)

    def test_track_without_boxes_is_not_gated(self):
        """
        Synthetic reads carry no geometry. The gate abstains rather than
        rejecting, so it cannot silently disable alerting where no measurement
        was ever available.
        """
        track = Track(track_id="synthetic")
        track.reads.append(PlateRead("GJ01AB1234", [0.9] * 10))

        assert track.pixels_per_character == 0.0
        assert read_is_alertable(track)


class TestStaticOverlaySuppression:
    """
    Burnt-in captions must not be indexed as plates.

    Regression from the 8 September sweep: cam24 returned the caption
    "Camera 01" 26 times in 45 seconds as C4MPC871 and similar, at 14.2 px per
    character — the highest resolution measured anywhere on the grid, because a
    rendered caption is sharper than any real plate. The camera watches an empty
    street. Evidence: DOCS/evidence/sweep_20260908/.
    """

    @staticmethod
    def _bare_detector():
        """A PlateDetector without loading ONNX models — only the filter is under test."""
        from app.vision import PlateDetector
        detector = PlateDetector.__new__(PlateDetector)
        detector._static_regions = {}
        return detector

    def test_caption_suppressed_after_repeated_hits(self):
        from app.vision import STATIC_REGION_HITS
        detector = self._bare_detector()
        caption = (690, 508, 810, 532)

        seen = [detector._is_static_furniture(caption, "cam24")
                for _ in range(STATIC_REGION_HITS + 3)]

        assert not any(seen[:STATIC_REGION_HITS]), "must not suppress before it is proven static"
        assert all(seen[STATIC_REGION_HITS:]), "must suppress once established"

    def test_moving_vehicle_is_never_suppressed(self):
        """A vehicle's box sweeps across frame, so it never repeats."""
        detector = self._bare_detector()
        suppressed = [detector._is_static_furniture((x, 300, x + 120, 340), "cam24")
                      for x in range(0, 800, 40)]
        assert not any(suppressed)

    def test_furniture_is_not_pooled_between_cameras(self):
        """
        One detector serves every stream in the worker, so a caption learned on
        one camera must not suppress a plate at the same coordinates on another.
        """
        from app.vision import STATIC_REGION_HITS
        detector = self._bare_detector()
        caption = (690, 508, 810, 532)
        for _ in range(STATIC_REGION_HITS + 2):
            detector._is_static_furniture(caption, "cam24")

        assert detector._is_static_furniture(caption, "cam24")
        assert not detector._is_static_furniture(caption, "cam07")

    def test_region_memory_stays_bounded(self):
        """A busy camera must not grow this list without limit."""
        detector = self._bare_detector()
        for i in range(500):
            detector._is_static_furniture((i * 3, 0, i * 3 + 20, 20), "cam01")
        assert len(detector._static_regions["cam01"]) <= 64
