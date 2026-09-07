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


class TestExtendedConfusions:
    """
    Substitutions the first table was missing.

    Each of these was a plate the pipeline threw away: E had no digit form, so
    `GJ01AB12E4` was rejected outright rather than corrected to a valid serial.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("GJ01AB12E4", "GJ01AB1234"),   # E -> 3 in the serial
        ("GJ01AB1Z34", "GJ01AB1234"),   # Z -> 2
        ("GJ01ABI234", "GJ01AB1234"),   # I -> 1
        ("GJ01ABT234", "GJ01AB7234"),   # T -> 7
    ])
    def test_serial_letter_confusions(self, raw, expected):
        assert correct_plate(raw).text == expected

    def test_delhi_alphanumeric_rto_survives(self):
        """DL8C is a real Delhi RTO code; C must not be coerced to 6."""
        result = correct_plate("DLBCAA1234")
        assert result.text == "DL8CAA1234"
        assert result.valid

    def test_two_digit_rto_preferred_over_three_letter_series(self):
        """
        `GJ0LAB1234` splits two ways. Reading it as RTO 0 with series LAB needs
        no substitution at all, but single-digit RTO codes with a three-letter
        series are rare, so the common shape must win.
        """
        assert correct_plate("GJ0LAB1234").text == "GJ01AB1234"

    def test_damaged_reads_are_still_refused(self):
        """
        Real eight-character reads of ten-character plates from cam14. A wider
        substitution table must not make these look repairable — inventing the
        missing characters would be fabrication.
        """
        for raw in ("GI65AA33", "GI63AA31", "KI484131"):
            result = correct_plate(raw)
            assert not (result.valid and result.state_valid), raw


class TestRTODistricts:
    """
    Real RTO district data, and the line between using it and abusing it.

    The table lets the recogniser report whether a district was ever issued and
    resolve a genuinely contested position toward one that was. It must never
    rewrite a character the reads agreed on.
    """

    def test_reports_real_districts(self):
        result = correct_plate("GJ18CD5678")
        assert result.rto_valid
        assert result.district == "Gandhinagar"

    def test_flags_unissued_districts(self):
        """Gujarat issues GJ-01 to GJ-39; GJ-99 has never existed."""
        result = correct_plate("GJ99AB1234")
        assert result.valid and result.state_valid
        assert not result.rto_valid

    def test_unissued_district_still_indexes(self):
        """
        The demonstration plates deliberately use unissuable districts so they
        cannot belong to a real person. Flagging them must not reject them.
        """
        result = correct_plate("GJ96XY4455")
        assert result.valid and result.state_valid

    def test_unrecognised_state_is_not_credited_with_a_district(self):
        """`GG` is not a state, so its district cannot be real."""
        result = correct_plate("GG02XX4499")
        assert not result.state_valid
        assert not result.rto_valid

    def test_contested_position_resolves_to_a_real_district(self):
        """
        Reads split between GJ88 (never issued) and GJ38 (Aravalli) should
        settle on the district that exists.
        """
        reads = [PlateRead(t, [0.6] * len(t)) for t in
                 ("GJ88AB1234", "GJ38AB1234", "GJ88AB1234", "GJ38AB1234", "GJ38AB1234")]
        plate, _, result = vote(reads)
        assert plate == "GJ38AB1234"
        assert result.district == "Aravalli"

    def test_unanimous_read_is_never_rewritten(self):
        """
        The regression that made this rule necessary: every frame read
        GJ96XY4455, and a district-repair step rewrote it to GJ06XY4455 because
        that district exists. Substituting one registration for another is the
        worst failure this system can produce.
        """
        reads = [PlateRead("GJ96XY4455", [1.0] * 10) for _ in range(6)]
        plate, _, _ = vote(reads)
        assert plate == "GJ96XY4455"


class TestRTOReference:
    """
    The published reference and the code must not drift apart.

    DOCS/RTO_CODES_INDIA.md is what a reviewer reads; app/rto_codes.py is what
    the recogniser obeys. If they disagree, the document is misleading about a
    system that identifies vehicles.
    """

    def _doc(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "DOCS" / "RTO_CODES_INDIA.md"
        return path.read_text(encoding="utf-8")

    def test_every_gujarat_district_is_documented_with_the_same_name(self):
        import re

        from app.rto_codes import GUJARAT_RTO

        doc = self._doc()
        found = {int(n): name.strip() for n, name
                 in re.findall(r"GJ-(\d{2}) \| ([^|]+?)\s*(?=\||$)", doc)}
        assert found == GUJARAT_RTO

    def test_every_state_code_appears_in_the_reference(self):
        from app.rto_codes import RTO_MAX

        doc = self._doc()
        for code in RTO_MAX:
            assert f"| {code} |" in doc or f"| {code} / " in doc \
                or f"/ {code} |" in doc or f"**{code}**" in doc, code

    def test_gujarat_upper_bound_matches_the_named_districts(self):
        """GJ-39 is the highest issued, and the table names exactly that many."""
        from app.rto_codes import GUJARAT_RTO, RTO_MAX

        assert RTO_MAX["GJ"] == max(GUJARAT_RTO)
        assert set(GUJARAT_RTO) == set(range(1, RTO_MAX["GJ"] + 1))


class TestMultiOfficeCities:
    """
    A city is not one RTO code.

    Ahmedabad is GJ-01 and GJ-27. An investigator filtering on GJ-01 alone
    silently misses every vehicle registered at the East office, and a missed
    vehicle in an investigation is not a small error.
    """

    def test_both_ahmedabad_codes_resolve_to_one_city(self):
        assert correct_plate("GJ01AB1234").city == "Ahmedabad"
        assert correct_plate("GJ27AB1234").city == "Ahmedabad"

    def test_districts_keep_their_own_names(self):
        """The city groups them; it does not flatten them."""
        assert correct_plate("GJ01AB1234").district == "Ahmedabad"
        assert correct_plate("GJ27AB1234").district == "Ahmedabad East"

    def test_single_office_district_has_no_city_group(self):
        result = correct_plate("GJ18CD5678")
        assert result.district == "Gandhinagar"
        assert result.city is None

    def test_sibling_codes_widen_a_district_search(self):
        from app.rto_codes import sibling_codes

        assert sibling_codes("GJ", 1) == (1, 27)
        assert sibling_codes("GJ", 27) == (1, 27)
        assert sibling_codes("GJ", 18) == (18,)

    def test_every_grouped_code_is_a_real_district(self):
        """A city group must never name a code the state never issued."""
        from app.rto_codes import CITY_RTO_GROUPS, GUJARAT_RTO

        for city, codes in CITY_RTO_GROUPS["GJ"].items():
            for code in codes:
                assert code in GUJARAT_RTO, f"{city} claims GJ-{code:02d}"


class TestLearnedPrior:
    """
    The learned prior settles ties. It must never do more than that.

    This is the same territory that made district rewriting unusable, so the
    boundary is asserted rather than assumed: an ambiguous read may be resolved,
    a unanimous one may not be touched, and a missing prior file must change
    nothing at all.
    """

    def test_resolves_a_split_between_two_real_districts(self):
        """
        Reads split evenly between GJ-01 Ahmedabad and GJ-30 Chhota Udaipur.
        A Gujarat deployment sees vastly more Ahmedabad vehicles.
        """
        reads = [PlateRead(t, [0.55] * len(t)) for t in
                 ("GJ01AB1234", "GJ30AB1234", "GJ01AB1234", "GJ30AB1234")]
        plate, _, _ = vote(reads)
        assert plate == "GJ01AB1234"

    def test_unanimous_unissued_district_is_left_alone(self):
        """
        The demonstration plates use unissued districts deliberately. The prior
        scores them impossibly low and must still not rewrite them, because no
        read disagreed.
        """
        for plate_text in ("GJ96XY4455", "GJ99AB1234"):
            reads = [PlateRead(plate_text, [1.0] * len(plate_text)) for _ in range(6)]
            plate, _, _ = vote(reads)
            assert plate == plate_text

    def test_prior_scores_impossible_districts_below_real_ones(self):
        from app.plate_prior import PlatePrior

        prior = PlatePrior()
        prior.observe_many(["GJ01AB1234"] * 10)
        assert prior.score("GJ99AB1234") < prior.score("GJ01AB1234")
        assert prior.score("GG02XX4499") < prior.score("GJ01AB1234")

    def test_empty_prior_has_no_opinion(self):
        """
        A deployment with no prior file must behave exactly as before. A
        recogniser that depends on a data file it may not have is one that
        fails in the field.
        """
        from app.plate_prior import PlatePrior

        prior = PlatePrior()
        assert prior.score("GJ01AB1234") == 0.0
        assert not prior.better("GJ01AB1234", "GJ30AB1234")

    def test_prior_learns_from_observations(self):
        from app.plate_prior import PlatePrior

        prior = PlatePrior()
        prior.observe_many(["GJ27AB1234"] * 20 + ["GJ30CD5678"])
        assert prior.score("GJ27AB1234") > prior.score("GJ30AB1234")
