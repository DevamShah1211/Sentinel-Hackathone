"""
Tests for the scene-analytics seeding tool.

The tool writes demonstration data, which is exactly why it needs tests: nobody
eyeballs twenty thousand rows, and a curve that peaks at the wrong hour or a
category total that disagrees with its own labels would be shipped to a reviewer
without anyone noticing. These assert the properties a reviewer would check if
they thought to.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from tools.seed_scene_analytics import (
    COVERAGE,
    IST,
    PROFILES,
    build_buckets,
    diurnal,
    draw_counts,
)


class TestDiurnalCurve:
    """The curve is a claim about Indian urban traffic; hold it to that."""

    def test_night_is_quiet(self):
        for hour in (1, 2, 3, 4):
            assert diurnal(hour) <= 0.15, f"{hour}:00 should be near-dead"

    def test_morning_and_evening_peak(self):
        assert diurnal(10) > 0.9
        assert diurnal(19) > 0.9

    def test_afternoon_dips_between_the_peaks(self):
        """A single broad hump would be a different city."""
        assert diurnal(14) < diurnal(10)
        assert diurnal(14) < diurnal(19)
        assert diurnal(14) > diurnal(3)

    def test_never_leaves_the_unit_range(self):
        for tenth in range(240):
            assert 0.0 <= diurnal(tenth / 10.0) <= 1.0


class TestDrawCounts:
    def test_zero_expectation_draws_nothing(self):
        assert draw_counts(0.0, 0.5, {"car": 1.0}, random.Random(1)) == {}

    def test_only_labels_from_the_mix_appear(self):
        mix = {"car": 0.5, "truck": 0.5}
        counts = draw_counts(8.0, 1.0, mix, random.Random(7))
        assert set(counts) <= set(mix)

    def test_busier_sites_draw_more(self):
        rng = random.Random(3)
        quiet = sum(sum(draw_counts(1.0, 1.0, {"car": 1.0}, rng).values())
                    for _ in range(60))
        rng = random.Random(3)
        busy = sum(sum(draw_counts(10.0, 1.0, {"car": 1.0}, rng).values())
                   for _ in range(60))
        assert busy > quiet * 3


class TestBuckets:
    @staticmethod
    def _buckets(camera="cam12", hours=24, seed=99):
        return build_buckets(camera, hours, datetime.now(timezone.utc),
                             random.Random(seed))

    def test_categories_agree_with_labels(self):
        """
        The two maps are written independently, so they can disagree — and a
        page that reads one and a report that reads the other would then
        quietly differ.
        """
        for bucket in self._buckets():
            labels = bucket["counts_by_label"]
            categories = bucket["counts_by_category"]
            people = labels.get("person", 0)
            vehicles = sum(n for k, n in labels.items() if k != "person")
            assert categories.get("person", 0) == people
            assert categories.get("vehicle", 0) == vehicles

    def test_peaks_land_in_the_indian_working_day(self):
        """
        Buckets are stored in UTC. Forgetting the IST conversion puts the
        morning rush at 04:00 local, which is the bug this asserts against.
        """
        by_hour: dict[int, list[int]] = {}
        for bucket in self._buckets(hours=48):
            at = datetime.fromisoformat(bucket["bucket_start"]).astimezone(IST)
            by_hour.setdefault(at.hour, []).append(
                bucket["counts_by_category"].get("vehicle", 0))

        means = {h: sum(v) / len(v) for h, v in by_hour.items() if v}
        busiest = max(means, key=means.get)
        assert 8 <= busiest <= 21, f"peak at {busiest}:00 IST is not a rush hour"
        assert means[busiest] > means[3] * 4

    def test_coverage_is_partial(self):
        """A worker does not get every minute, and the data should not pretend."""
        buckets = self._buckets(hours=24)
        assert len(buckets) < 24 * 60
        assert len(buckets) > 24 * 60 * (COVERAGE - 0.12)

    def test_every_bucket_records_frames_sampled(self):
        # Without it a count of zero cannot be told from a camera nobody watched.
        assert all(b["frames_sampled"] > 0 for b in self._buckets())

    def test_bucket_starts_are_unique_and_on_the_minute(self):
        starts = [b["bucket_start"] for b in self._buckets()]
        assert len(starts) == len(set(starts)), "would violate the unique key"
        for start in starts:
            at = datetime.fromisoformat(start)
            assert at.second == 0 and at.microsecond == 0

    def test_window_is_respected(self):
        now = datetime.now(timezone.utc)
        buckets = build_buckets("cam01", 6, now, random.Random(5))
        for bucket in buckets:
            at = datetime.fromisoformat(bucket["bucket_start"])
            assert now - timedelta(hours=6, minutes=1) <= at <= now

    def test_deterministic_for_a_fixed_seed(self):
        """A screenshot taken today should still match the page tomorrow."""
        now = datetime.now(timezone.utc)
        first = build_buckets("cam10", 6, now, random.Random(42))
        second = build_buckets("cam10", 6, now, random.Random(42))
        assert first == second

    def test_quiet_cameras_are_mostly_empty(self):
        """
        cam24 and cam25 exist to demonstrate 'analysed, saw nothing'. If they
        report like a junction the page loses the state it was built to show.
        """
        buckets = self._buckets("cam24", hours=24)
        empty = sum(1 for b in buckets if not b["counts_by_category"])
        assert empty > len(buckets) * 0.3

    def test_confidence_sits_in_the_measured_range(self):
        for bucket in self._buckets():
            assert 0.5 <= bucket["max_confidence"] <= 1.0

    def test_every_bucket_declares_itself_seeded(self):
        """
        The one property that lets the page label these rows and `--clear`
        remove them. A bucket without it is indistinguishable from a worker's.
        """
        assert all(b["source"] == "seed" for b in self._buckets())


class TestProfiles:
    def test_every_profile_names_a_real_mix(self):
        for native_id, (veh, per, mix) in PROFILES.items():
            assert veh > 0 and per >= 0, native_id
            assert abs(sum(mix.values()) - 1.0) < 0.02, f"{native_id} mix"
            assert "person" not in mix, "people are drawn separately"

    def test_the_grid_has_quiet_cameras_and_busy_ones(self):
        peaks = [veh for veh, _, _ in PROFILES.values()]
        assert min(peaks) < 1.0, "no quiet camera to demonstrate"
        assert max(peaks) > 8.0, "no busy camera to rank"
