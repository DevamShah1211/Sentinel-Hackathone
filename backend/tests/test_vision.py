"""
Tests for the capture and tracking layer.

These deliberately avoid loading the ONNX models: they cover the logic that
surrounds inference — frame-quality gating, tiling geometry, deduplication and
track association — which is where the sandbox-specific bugs actually lived.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.vision import (
    RawDetection,
    frame_is_smeared,
    Track,
    TrackManager,
    build_tiles,
    deduplicate,
    frame_is_decodable,
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
