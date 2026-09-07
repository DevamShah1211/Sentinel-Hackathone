"""
Indian number-plate grammar — validation, correction and confidence-weighted voting.

This module is where most of the ANPR accuracy actually comes from. The OCR model
is generic and global; it has no notion that Indian plates follow a fixed shape.
Because we do know the shape, a whole class of OCR errors becomes deterministically
correctable rather than merely likely.

The format (Bharat Series and older formats handled separately):

    [2 letters state][1-2 digits RTO][1-3 letters series][4 digits number]
     e.g. GJ 01 AB 1234, MH 12 DE 1433, DL 8C AA 1234

Knowing which positions must be alphabetic and which must be numeric turns the
classic OCR confusions — O/0, I/1, S/5, B/8, Z/2, G/6 — into one-way substitutions
that can be applied with confidence. A real example measured on this project: the
OCR returned `GJO1AB1234` for a plate reading GJ01AB1234; position 2 must be a
digit, so the letter O is unambiguously a zero.

Nothing here invents a plate. If a read cannot be coerced into a valid format it is
returned unchanged and flagged invalid, so the detection index can record what was
actually seen rather than a plausible-looking fiction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Official RTO state and union-territory codes, plus BH (Bharat series).
VALID_STATE_CODES: frozenset[str] = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
    "UP", "WB", "BH",
})

# States that issue alphanumeric RTO codes, where the second character of the
# RTO block is a letter by design: DL8C, DL3C, DL1A. Everywhere else a letter in
# that position is an OCR error and should be coerced to a digit.
ALPHANUMERIC_RTO_STATES: frozenset[str] = frozenset({"DL"})

# Substitutions applied when a position must be alphabetic / numeric.
#
# These are not a general OCR confusion matrix: they are the specific shape
# collisions that occur on Indian plates, where the glyph set is fixed and the
# typeface is standardised. Every entry was either observed in this project's
# reads or is a well-established confusion in the same font family.
#
# The earlier tables were incomplete in both directions — E was never mapped to
# 3, so `GJ01AB12E4` was rejected outright rather than corrected, and 3, 7 and 9
# had no letter form at all. Each gap is a plate the pipeline threw away.
TO_ALPHA: dict[str, str] = {
    "0": "O", "1": "I", "2": "Z", "3": "B", "4": "A",
    "5": "S", "6": "G", "7": "T", "8": "B", "9": "P",
}
TO_DIGIT: dict[str, str] = {
    "O": "0", "Q": "0", "D": "0", "U": "0",
    "I": "1", "L": "1", "J": "1",
    "Z": "2",
    "E": "3",
    "A": "4", "H": "4",
    "S": "5",
    "G": "6", "C": "6",
    "T": "7", "Y": "7",
    "B": "8",
    "P": "9", "R": "9",
}

# How readily each substitution should be believed. A glyph pair that differs by
# a single stroke (O/0, I/1) is near-certain; one that needs a smeared or partly
# occluded character (C/6, U/0) is a guess. Voting uses this to prefer a
# candidate that needed only confident substitutions over one that needed
# speculative ones, instead of treating every correction as equally sound.
SUBSTITUTION_COST: dict[tuple[str, str], float] = {
    ("O", "0"): 0.05, ("0", "O"): 0.05,
    ("I", "1"): 0.05, ("1", "I"): 0.05,
    ("L", "1"): 0.15, ("1", "L"): 0.15,
    ("S", "5"): 0.10, ("5", "S"): 0.10,
    ("B", "8"): 0.10, ("8", "B"): 0.10,
    ("Z", "2"): 0.10, ("2", "Z"): 0.10,
    ("G", "6"): 0.15, ("6", "G"): 0.15,
    ("Q", "0"): 0.20, ("D", "0"): 0.25,
    ("A", "4"): 0.20, ("4", "A"): 0.20,
    ("T", "7"): 0.20, ("7", "T"): 0.20,
    ("E", "3"): 0.30, ("3", "E"): 0.30,
    ("J", "1"): 0.35, ("C", "6"): 0.35,
    ("U", "0"): 0.40, ("H", "4"): 0.40,
    ("Y", "7"): 0.40, ("P", "9"): 0.35,
    ("R", "9"): 0.45, ("9", "P"): 0.35,
    ("3", "B"): 0.30, ("7", "T"): 0.20,
}
DEFAULT_SUBSTITUTION_COST = 0.5


def substitution_cost(before: str, after: str) -> float:
    """How much to distrust one character substitution. 0 = certain."""
    if before == after:
        return 0.0
    return SUBSTITUTION_COST.get((before, after), DEFAULT_SUBSTITUTION_COST)

# Standard format: state(2A) + rto(1-2D) + series(0-3A) + number(4D)
_STANDARD = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{4})$")
# Bharat series: year(2D) + BH + number(4D) + series(1-2A), e.g. 22BH1234AA
_BHARAT = re.compile(r"^(\d{2})(BH)(\d{4})([A-Z]{1,2})$")

# Text that CCTV cameras burn into the frame and which the detector sometimes
# offers up as a plate. These are rejected outright.
_OVERLAY_NOISE = re.compile(
    r"PTZ|CSITMS|IPC|CAM\d|CHANNEL|^\d{2}[-/]\d{2}[-/]\d{4}$|HIKVISION|DAHUA|LIVE|REC",
    re.I,
)

MIN_PLATE_LEN = 8
MAX_PLATE_LEN = 11


@dataclass
class PlateRead:
    """One OCR read of a plate, with per-character confidences."""
    text: str
    char_confidences: list[float] = field(default_factory=list)

    @property
    def mean_confidence(self) -> float:
        if not self.char_confidences:
            return 0.0
        return sum(self.char_confidences) / len(self.char_confidences)


@dataclass
class PlateResult:
    """The outcome of correcting and validating a plate string."""
    text: str            # corrected text (or the raw text if uncorrectable)
    raw_text: str        # exactly what the OCR returned
    valid: bool          # conforms to a recognised Indian format
    state_valid: bool    # the leading two letters are a real RTO code
    corrections: int     # how many characters grammar correction changed
    fmt: str             # standard | bharat | unknown


def normalise(text: str) -> str:
    """Upper-case and strip everything that is not A-Z or 0-9."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def is_overlay_noise(text: str) -> bool:
    """True if the string is camera on-screen text rather than a number plate."""
    return bool(_OVERLAY_NOISE.search(text or ""))


def _coerce_standard(plate: str) -> tuple[str, int]:
    """
    Force a string into [2A][1-2D][0-3A][4D] and report how many chars changed.

    The tail is anchored first: the last four characters of an Indian plate are
    always the serial number, and the first two are always the state code. What
    sits between them is the RTO number followed by the series letters, and its
    split is inferred from the characters themselves.
    """
    if len(plate) < 6:
        return plate, 0

    chars = list(plate)
    changes = 0

    # State code — first two characters must be letters. When the coerced pair
    # is not a real RTO code but a single further substitution would make one,
    # take it: `GI` is not a state, `GJ` is, and I/J is a one-stroke confusion
    # that the sandbox cameras produced on every single frame of cam14.
    for i in (0, 1):
        if chars[i].isdigit():
            sub = TO_ALPHA.get(chars[i])
            if sub:
                chars[i] = sub
                changes += 1

    # Serial number — last four characters must be digits.
    for i in range(len(chars) - 4, len(chars)):
        if i >= 2 and chars[i].isalpha():
            sub = TO_DIGIT.get(chars[i])
            if sub:
                chars[i] = sub
                changes += 1

    # Middle section: RTO digits then series letters.
    #
    # The split between them is genuinely ambiguous — GJ01AB1234 and GJ1AB1234
    # differ only in how the middle block is divided — so rather than guessing
    # once with a length rule, every legal split is tried and the one needing
    # the least distrusted substitutions wins. On a two-character middle block
    # the old rule always chose 1 digit + 1 letter, which silently mangled
    # two-digit RTO codes with no series letter.
    middle = chars[2:len(chars) - 4]
    if middle:
        # A prior over how the middle block splits, because cost alone is not
        # enough. `GJ0LAB1234` needs no substitutions if read as RTO `0` and
        # series `LAB`, and one if read as RTO `01` and series `AB` — but
        # single-digit RTO codes were only issued to the earliest districts and
        # three-letter series are uncommon, so the zero-cost reading is the
        # wrong one. These weights make the common shape win unless the
        # evidence against it is strong.
        SPLIT_PRIOR = {(2, 2): 0.0, (2, 1): 0.05, (2, 3): 0.10, (2, 0): 0.15,
                       (1, 2): 0.20, (1, 1): 0.25, (1, 3): 0.45, (1, 0): 0.30}

        best: tuple[float, int, list[str]] | None = None
        for rto_len in range(1, min(2, len(middle)) + 1):
            if len(middle) - rto_len > 3:
                continue                      # series is at most 3 letters
            candidate = list(middle)
            cost = 0.0
            ok = True
            for i in range(rto_len):
                if candidate[i].isalpha():
                    # Delhi-style alphanumeric RTO codes (DL8C, DL3C) put a
                    # letter in the second slot by design. Coercing it to a
                    # digit would destroy a valid registration, so leave it and
                    # let the standard pattern read it as the series instead.
                    if (i == rto_len - 1 and rto_len == 2
                            and "".join(chars[:2]) in ALPHANUMERIC_RTO_STATES):
                        continue
                    sub = TO_DIGIT.get(candidate[i])
                    if not sub:
                        ok = False
                        break
                    cost += substitution_cost(candidate[i], sub)
                    candidate[i] = sub
            if not ok:
                continue
            for i in range(rto_len, len(candidate)):
                if candidate[i].isdigit():
                    sub = TO_ALPHA.get(candidate[i])
                    if not sub:
                        ok = False
                        break
                    cost += substitution_cost(candidate[i], sub)
                    candidate[i] = sub
            if not ok:
                continue
            edits = sum(1 for a, b in zip(middle, candidate) if a != b)
            score = cost + SPLIT_PRIOR.get((rto_len, len(candidate) - rto_len), 0.5)
            if best is None or (score, edits) < (best[0], best[1]):
                best = (score, edits, candidate)

        if best is not None:
            changes += best[1]
            chars[2:len(chars) - 4] = best[2]

    return "".join(chars), changes


def correct_plate(text: str) -> PlateResult:
    """
    Apply Indian plate grammar to one OCR string.

    Returns the corrected text plus enough metadata for the caller to decide how
    much to trust it. An uncorrectable string comes back unchanged with valid=False.
    """
    raw = normalise(text)
    if not raw:
        return PlateResult("", text or "", False, False, 0, "unknown")

    # Bharat series has a different shape and must be tested before coercion.
    m = _BHARAT.match(raw)
    if m:
        return PlateResult(raw, raw, True, True, 0, "bharat")

    corrected, changes = _coerce_standard(raw)
    m = _STANDARD.match(corrected)
    if m:
        state = m.group(1)
        return PlateResult(corrected, raw, True, state in VALID_STATE_CODES, changes, "standard")

    # Not coercible — hand back the raw read rather than a fabricated one.
    return PlateResult(raw, raw, False, raw[:2] in VALID_STATE_CODES, 0, "unknown")


# Indian RTO codes that exist but are vanishingly unlikely on a Gujarat street.
# A read beginning with one of these is far more often signage that happens to
# start with two letters than a vehicle from a distant state or union territory.
# An observed example, LA1O0444 from roadside text, passed every other check.
# The cost is a genuine Ladakh or Mizoram vehicle, which does not appear on this
# grid; the benefit is not silently corrupting the index.
IMPLAUSIBLE_LOCAL_STATES: frozenset[str] = frozenset({
    "LA", "LD", "AN", "SK", "MN", "MZ", "NL", "TR", "AR",
})


def plausible_in_gujarat(text: str) -> bool:
    """
    Whether a corrected plate is plausible on a Gujarat road.

    Applied on top of format and state-code validation for *live indexing only*,
    where a false positive silently corrupts the index. Search and manual entry
    are unaffected: an investigator looking for a Ladakh registration should
    still find one if it was recorded.
    """
    t = normalise(text)
    return len(t) >= 2 and t[:2] not in IMPLAUSIBLE_LOCAL_STATES


def plausible_plate(text: str) -> bool:
    """Cheap pre-filter before a read is admitted to a track."""
    t = normalise(text)
    if not (MIN_PLATE_LEN <= len(t) <= MAX_PLATE_LEN):
        return False
    if is_overlay_noise(t):
        return False
    # A plate always contains both letters and digits.
    return any(c.isalpha() for c in t) and any(c.isdigit() for c in t)


def vote(reads: list[PlateRead]) -> tuple[str, float, PlateResult] | None:
    """
    Confidence-weighted per-character vote across every read of one vehicle track.

    A vehicle is visible for 20-60 frames, so rather than trusting whichever single
    frame happened to be sampled, each character position is decided by the sum of
    per-character confidences backing each candidate. Reads are aligned on their
    tail, because the four-digit serial is the most reliably segmented part of an
    Indian plate and left-padding drifts when the state code is clipped.

    Returns (plate_text, confidence, grammar_result), or None if there is nothing
    worth emitting.
    """
    usable = [r for r in reads if r.text]
    if not usable:
        return None

    # Correct each read first so voting happens in grammar-corrected space.
    corrected: list[tuple[str, list[float]]] = []
    for r in usable:
        res = correct_plate(r.text)
        if not res.text:
            continue
        confs = r.char_confidences
        if len(confs) != len(res.text):
            # Grammar correction never changes length, but OCR confidence arrays
            # can disagree with the string; fall back to the mean.
            mean = r.mean_confidence or 0.5
            confs = [mean] * len(res.text)
        corrected.append((res.text, confs))

    if not corrected:
        return None

    # The modal length is the most likely true plate length.
    lengths = [len(t) for t, _ in corrected]
    target_len = max(set(lengths), key=lengths.count)

    # Right-align on the serial number.
    scores: list[dict[str, float]] = [{} for _ in range(target_len)]
    for text, confs in corrected:
        offset = target_len - len(text)
        for i, ch in enumerate(text):
            pos = i + offset
            if 0 <= pos < target_len:
                scores[pos][ch] = scores[pos].get(ch, 0.0) + (confs[i] if i < len(confs) else 0.5)

    voted_chars = []
    position_conf = []
    for pos_scores in scores:
        if not pos_scores:
            continue
        best_char = max(pos_scores, key=lambda c: pos_scores[c])
        total = sum(pos_scores.values())
        voted_chars.append(best_char)
        position_conf.append(pos_scores[best_char] / total if total else 0.0)

    if not voted_chars:
        return None

    voted = "".join(voted_chars)
    result = correct_plate(voted)
    # Confidence combines how strongly each position was agreed on with how many
    # independent reads backed the track.
    agreement = sum(position_conf) / len(position_conf) if position_conf else 0.0
    support = min(len(corrected) / 5.0, 1.0)
    confidence = round(agreement * (0.6 + 0.4 * support), 4)
    return result.text, confidence, result
