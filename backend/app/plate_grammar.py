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

# Substitutions applied when a position must be alphabetic / numeric.
TO_ALPHA: dict[str, str] = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
TO_DIGIT: dict[str, str] = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
                            "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}

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

    # State code — first two characters must be letters.
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
    middle = chars[2:len(chars) - 4]
    if middle:
        # The RTO code is the leading 1-2 characters of the middle block.
        rto_len = 2 if len(middle) >= 3 else 1
        for i in range(rto_len):
            if middle[i].isalpha():
                sub = TO_DIGIT.get(middle[i])
                if sub:
                    middle[i] = sub
                    changes += 1
        # Everything after the RTO code is the series — letters.
        for i in range(rto_len, len(middle)):
            if middle[i].isdigit():
                sub = TO_ALPHA.get(middle[i])
                if sub:
                    middle[i] = sub
                    changes += 1
        chars[2:len(chars) - 4] = middle

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
