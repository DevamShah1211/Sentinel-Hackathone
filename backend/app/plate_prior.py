"""
A statistical prior over Indian registrations, learned from data rather than
guessed, and used to settle reads the OCR itself cannot decide.

**This is calibration, not training.** No network weights change. The recogniser
is the same pretrained ONNX model; what changes is how its output is scored when
two readings are genuinely tied. Training the OCR would need thousands of
annotated Indian plate crops and a GPU; this needs a table of registrations and
runs in microseconds.

The distinction matters for a submission. "We trained a model" invites the
question of what data, labelled by whom, validated how. "We measured which
character combinations occur and used that to break ties" is a claim that can be
checked against the code in an afternoon.

Three priors, all derived from real registration structure:

1. **Series letters.** Series are issued alphabetically from AA, so a vehicle
   registered in an early series is far commoner than one in a late series, and
   some combinations do not occur at all in a district that has not filled them.

2. **District frequency.** A camera in Ahmedabad sees GJ-01 and GJ-27 constantly
   and GJ-30 Chhota Udaipur rarely. Where a read is split between the two, the
   local district is the better answer.

3. **Observed pairs.** What this deployment has actually indexed. A district and
   series combination seen a hundred times before is more likely than one never
   seen, and this is the only prior that improves as the system runs.

Every prior only ever **breaks a tie**. None can overturn a confident read, and
a test asserts that a unanimous read is never rewritten — the failure mode that
made district rewriting unusable (see MEASUREMENTS section 2d).
"""
from __future__ import annotations

import json
import logging
import math
from collections import Counter
from pathlib import Path

from app.rto_codes import CITY_RTO_GROUPS, rto_exists

logger = logging.getLogger("sentinel.prior")

# Where the learned counts are persisted between runs.
DEFAULT_PRIOR_PATH = Path(__file__).resolve().parent.parent / "data" / "plate_prior.json"


class PlatePrior:
    """
    Counts of what has actually been seen, with a smoothed score per plate.

    Kept deliberately simple: three Counters and additive smoothing. A heavier
    model would be harder to justify to a reviewer and would not obviously do
    better on the quantity of data a hackathon deployment produces.
    """

    def __init__(self) -> None:
        self.districts: Counter[str] = Counter()      # "GJ01"
        self.series: Counter[str] = Counter()         # "GJ01:AB"
        self.series_any: Counter[str] = Counter()     # "AB", across all districts
        self.total = 0

    # ── learning ──────────────────────────────────────────────────────────

    def observe(self, plate: str) -> None:
        """Record one confirmed registration."""
        parsed = _split(plate)
        if parsed is None:
            return
        state, rto, series, _serial = parsed
        key = f"{state}{rto:02d}"
        self.districts[key] += 1
        if series:
            self.series[f"{key}:{series}"] += 1
            self.series_any[series] += 1
        self.total += 1

    def observe_many(self, plates: list[str]) -> int:
        before = self.total
        for plate in plates:
            self.observe(plate)
        return self.total - before

    # ── scoring ───────────────────────────────────────────────────────────

    def score(self, plate: str) -> float:
        """
        How plausible this registration is, as a log score. Higher is better.

        Zero means "no opinion", which is what an empty prior returns for
        everything — so a fresh deployment behaves exactly as it did before this
        module existed, and improves only as it observes real registrations.
        """
        parsed = _split(plate)
        if parsed is None:
            return 0.0
        state, rto, series, _serial = parsed

        # A district that was never issued is not a registration at all. The
        # penalty must sit below every plausible score rather than at a fixed
        # value: log probabilities here run to -12 or worse, so an earlier flat
        # -4.0 made impossible plates outscore real ones.
        if not rto_exists(state, rto):
            return _IMPOSSIBLE

        if self.total == 0:
            return 0.0

        key = f"{state}{rto:02d}"
        score = 0.0

        # District frequency, smoothed so an unseen district is unlikely rather
        # than impossible. A camera sees its own city constantly and distant
        # districts rarely, and that is real evidence.
        district_p = (self.districts[key] + 0.5) / (self.total + 0.5 * _DISTRICT_SPACE)
        score += math.log(district_p)

        if series:
            # Series within this district, backing off to the series across all
            # districts when this district has not been seen with it.
            local = self.series[f"{key}:{series}"]
            globally = self.series_any[series]
            series_p = (local + 0.3 * globally + 0.2) / (self.districts[key] + 1.0 + 0.2 * _SERIES_SPACE)
            score += math.log(series_p)

            # Series are issued alphabetically from AA, so an early series is
            # commoner than a late one. Weak, but free, and it is real.
            score += _series_recency_bonus(series)

        return score

    def better(self, candidate: str, incumbent: str, margin: float = 0.75) -> bool:
        """
        Whether `candidate` is enough better than `incumbent` to prefer it.

        The margin is what keeps this from being a rewriting engine: a candidate
        must be meaningfully more plausible, not merely fractionally, before it
        displaces a reading the OCR actually produced.
        """
        if candidate == incumbent:
            return False
        return self.score(candidate) - self.score(incumbent) > margin

    # ── persistence ───────────────────────────────────────────────────────

    def save(self, path: Path = DEFAULT_PRIOR_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "districts": dict(self.districts),
            "series": dict(self.series),
            "series_any": dict(self.series_any),
            "total": self.total,
        }, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = DEFAULT_PRIOR_PATH) -> "PlatePrior":
        prior = cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return prior                       # no prior yet; scores are all 0.0
        prior.districts = Counter(raw.get("districts", {}))
        prior.series = Counter(raw.get("series", {}))
        prior.series_any = Counter(raw.get("series_any", {}))
        prior.total = int(raw.get("total", 0))
        return prior


# Rough sizes of the spaces being smoothed over. Exactness does not matter; they
# only set how strongly an unseen combination is penalised.
_DISTRICT_SPACE = 1000        # RTO districts across India
_SERIES_SPACE = 676           # AA..ZZ

# Below any score a real registration can reach, so an unissued district always
# loses to one that exists, whatever the observed frequencies say.
_IMPOSSIBLE = -40.0


def _series_recency_bonus(series: str) -> float:
    """
    Series are issued alphabetically, so earlier ones cover more vehicles.

    Deliberately small — at most a fifth of the tie-break margin — because the
    effect is real but weak, and a vehicle in a late series is perfectly
    ordinary in a district that has been registering for decades.
    """
    if len(series) != 2 or not series.isalpha():
        return 0.0
    position = (ord(series[0]) - 65) * 26 + (ord(series[1]) - 65)
    return 0.15 * (1.0 - position / 676.0)


def _split(plate: str) -> tuple[str, int, str, str] | None:
    """Break a standard registration into state, RTO number, series, serial."""
    import re

    m = re.match(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{4})$", (plate or "").upper())
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3), m.group(4)


def local_districts(camera_state: str = "GJ") -> set[str]:
    """
    District keys a camera in this state is most likely to see.

    Used to seed a prior before any detections exist, so a fresh deployment is
    not completely uninformed on its first day.
    """
    keys: set[str] = set()
    for codes in CITY_RTO_GROUPS.get(camera_state, {}).values():
        keys.update(f"{camera_state}{c:02d}" for c in codes)
    return keys
