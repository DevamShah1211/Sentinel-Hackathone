"""
Tests for Indian plate-grammar correction and track-level voting.

These cover the accuracy work that the OCR model itself does not do. Several
cases are errors this pipeline actually produced during development rather than
invented ones — `GJO1AB1234` and the `AEER75EEEE` billboard read both came off
real frames.
"""
from __future__ import annotations

import pytest

from app.plate_grammar import (
    PlateRead,
    plausible_in_gujarat,
    correct_plate,
    is_overlay_noise,
    normalise,
    plausible_plate,
    vote,
)


class TestCorrection:
    @pytest.mark.parametrize("raw,expected", [
        # Observed: the OCR returned O for the 0 in position 2.
        ("GJO1AB1234", "GJ01AB1234"),
        ("GJ01AB1234", "GJ01AB1234"),   # already correct, must not be altered
        ("6J01AB1Z34", "GJ01AB1234"),   # 6->G in the state code, Z->2 in the serial
        ("MHI2DE1433", "MH12DE1433"),   # I->1 in the RTO number
        ("DLBCAA1234", "DL8CAA1234"),   # B->8 in a two-character RTO code
        ("GJ05JV72I9", "GJ05JV7219"),   # I->1 in the serial
        ("22BH1234AA", "22BH1234AA"),   # Bharat series has a different shape
    ])
    def test_corrects_positional_confusions(self, raw: str, expected: str) -> None:
        assert correct_plate(raw).text == expected

    def test_flags_valid_format_and_state(self) -> None:
        result = correct_plate("GJO1AB1234")
        assert result.valid
        assert result.state_valid
        assert result.fmt == "standard"
        assert result.corrections == 1
        assert result.raw_text == "GJO1AB1234"   # the original read is preserved

    def test_unknown_state_code_is_reported_not_rewritten(self) -> None:
        # XX is not an RTO code. The read is kept as-is; we do not invent a state.
        result = correct_plate("XX01AB1234")
        assert result.text == "XX01AB1234"
        assert not result.state_valid

    def test_uncorrectable_read_is_returned_unchanged(self) -> None:
        result = correct_plate("!!!???")
        assert not result.valid
        assert result.corrections == 0

    def test_normalise_strips_separators_and_case(self) -> None:
        assert normalise(" gj-01 ab 1234 ") == "GJ01AB1234"


class TestNoiseRejection:
    @pytest.mark.parametrize("text", [
        "S10PTZ2",      # camera overlay, seen on the sandbox feeds
        "CSITMS-31",    # site identifier burnt into the frame
        "IPC",
        "14-06-2026",   # burnt-in date
    ])
    def test_camera_overlay_text_is_rejected(self, text: str) -> None:
        assert is_overlay_noise(text)
        assert not plausible_plate(text)

    @pytest.mark.parametrize("text", ["GJ01AB1234", "MH12DE1433", "22BH1234AA"])
    def test_real_plates_pass_the_prefilter(self, text: str) -> None:
        assert plausible_plate(text)

    def test_letters_only_and_digits_only_are_rejected(self) -> None:
        assert not plausible_plate("ABCDEFGHIJ")
        assert not plausible_plate("1234567890")

    def test_length_bounds(self) -> None:
        assert not plausible_plate("GJ01")               # too short
        assert not plausible_plate("GJ01AB1234567890")   # too long


class TestVoting:
    def test_majority_recovers_the_true_plate(self) -> None:
        reads = [
            PlateRead("GJO1AB1234", [0.90] * 10),
            PlateRead("GJ01AB1234", [0.95] * 10),
            PlateRead("GJ01A81234", [0.60] * 10),
            PlateRead("GJ01AB1Z34", [0.50] * 10),
            PlateRead("GJ01AB1234", [0.92] * 10),
        ]
        text, confidence, result = vote(reads)
        assert text == "GJ01AB1234"
        assert result.valid
        assert confidence > 0.8

    def test_confidence_outweighs_count(self) -> None:
        # Two low-confidence reads must not outvote three high-confidence ones.
        reads = [
            PlateRead("GJ05JV7219", [0.97] * 10),
            PlateRead("GJ05JV7219", [0.95] * 10),
            PlateRead("GJ05JV7219", [0.96] * 10),
            PlateRead("GJ05JV7218", [0.20] * 10),
            PlateRead("GJ05JV7217", [0.18] * 10),
        ]
        text, _, _ = vote(reads)
        assert text == "GJ05JV7219"

    def test_single_outlier_is_absorbed(self) -> None:
        reads = [
            PlateRead("GJ05JV7219", [0.90] * 10),
            PlateRead("GJ05JV7219", [0.88] * 10),
            PlateRead("XXXXXXXXXX", [0.20] * 10),
        ]
        text, _, _ = vote(reads)
        assert text == "GJ05JV7219"

    def test_more_reads_raise_confidence(self) -> None:
        few = vote([PlateRead("GJ01AB1234", [0.9] * 10)] * 2)
        many = vote([PlateRead("GJ01AB1234", [0.9] * 10)] * 8)
        assert many[1] > few[1]

    def test_empty_input_returns_none(self) -> None:
        assert vote([]) is None
        assert vote([PlateRead("", [])]) is None

    def test_mismatched_confidence_length_does_not_crash(self) -> None:
        # The OCR confidence array can disagree with the string length.
        text, _, _ = vote([
            PlateRead("GJ01AB1234", [0.9] * 3),
            PlateRead("GJ01AB1234", []),
        ])
        assert text == "GJ01AB1234"


class TestRegionalPlausibility:
    """
    A final filter for live indexing only. An observed read, LA1O0444, came from
    roadside text: correctly shaped, and LA is a real RTO code, so both earlier
    checks passed. Vehicles from distant union territories do not realistically
    appear on this grid, and admitting one silently corrupts the index.
    """

    @pytest.mark.parametrize("plate", ["GJ01AB1234", "MH12DE1433", "RJ14GH9012",
                                       "DL8CAA1234", "22BH1234AA"])
    def test_plates_seen_on_gujarat_roads_are_accepted(self, plate: str) -> None:
        assert plausible_in_gujarat(plate)

    @pytest.mark.parametrize("plate", ["LA1O0444", "LD01AB1234", "MZ05XY9999",
                                       "NL01AA1111"])
    def test_distant_territories_are_rejected_for_indexing(self, plate: str) -> None:
        assert not plausible_in_gujarat(plate)

    def test_empty_input_is_rejected(self) -> None:
        assert not plausible_in_gujarat("")

    def test_this_filter_does_not_touch_correctness(self) -> None:
        # A Ladakh plate is still a valid plate — it is only kept out of
        # automatic indexing, so search and manual entry still work.
        result = correct_plate("LA01AB1234")
        assert result.valid
        assert result.state_valid
