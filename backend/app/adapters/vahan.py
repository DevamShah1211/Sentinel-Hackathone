"""
VAHAN adapter — vehicle registration lookup, contract-first.

VAHAN is a closed system. There is no access route for a hackathon team, and
pretending otherwise would collapse under one question. The defensible posture is
contract-first integration: define the request and response contract, implement
the adapter against it, run it against a mock that returns realistic synthetic
records, and document exactly what changes when real credentials arrive.

What changes on the day access is granted:

  * `VahanSettings.base_url` points at the real endpoint instead of the mock
  * `VahanSettings.api_key` / client certificate is supplied
  * `LiveVahanClient` replaces `MockVahanClient` in `get_vahan_client()`
  * rate limiting and response caching are switched on (both stubbed here)

Nothing above this module changes — callers depend on `VehicleRecord`, not on
where it came from. Every lookup is audited, because enriching a plate with owner
details is access to personal data and must carry a stated purpose.

The synthetic records below are clearly fictional and are labelled as such in the
`source` field of every response, so a mock result can never be mistaken for an
authoritative one.
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Protocol

logger = logging.getLogger("sentinel.vahan")


# ─── Contract ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VehicleRecord:
    """
    The response contract. Field names follow VAHAN's published vocabulary so the
    live implementation is a mapping exercise rather than a redesign.
    """
    registration_number: str
    owner_name: str
    vehicle_class: str          # motorcycle / lmv / hgv / …
    maker_model: str
    fuel_type: str
    colour: str
    registration_date: date | None
    registering_authority: str
    chassis_number_masked: str
    engine_number_masked: str
    insurance_valid_upto: date | None
    puc_valid_upto: date | None
    fitness_valid_upto: date | None
    is_blacklisted: bool
    blacklist_reason: str | None
    source: str                 # "mock" | "vahan-live"
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_mock(self) -> bool:
        return self.source == "mock"

    @property
    def insurance_expired(self) -> bool:
        return bool(self.insurance_valid_upto and self.insurance_valid_upto < date.today())

    @property
    def puc_expired(self) -> bool:
        return bool(self.puc_valid_upto and self.puc_valid_upto < date.today())


class VahanLookupError(Exception):
    """Raised when a lookup cannot be completed."""


class VehicleNotFound(VahanLookupError):
    """The registration number is not present in the register."""


class VahanClient(Protocol):
    """The interface every implementation satisfies."""

    async def lookup(self, registration_number: str) -> VehicleRecord: ...


# ─── Settings ─────────────────────────────────────────────────────────────────

@dataclass
class VahanSettings:
    """
    Configuration for the live client. Every field is unset in this prototype;
    they document what a real deployment must supply.
    """
    base_url: str = ""
    api_key: str = ""
    client_cert_path: str = ""
    client_key_path: str = ""
    timeout_seconds: float = 10.0
    # VAHAN enforces per-agency quotas. The live client must respect them or the
    # agency's access is withdrawn.
    max_requests_per_minute: int = 60
    cache_ttl_seconds: int = 86_400

    @property
    def configured(self) -> bool:
        return bool(self.base_url and (self.api_key or self.client_cert_path))


# ─── Mock implementation ──────────────────────────────────────────────────────

_MAKER_MODELS = (
    ("Maruti Suzuki", "Swift VXi"), ("Hyundai", "Creta SX"), ("Tata Motors", "Nexon XZ+"),
    ("Mahindra", "Bolero B6"), ("Honda", "City ZX"), ("Toyota", "Innova Crysta"),
    ("Bajaj Auto", "Pulsar 150"), ("Hero MotoCorp", "Splendor Plus"),
    ("Ashok Leyland", "Dost+"), ("Eicher", "Pro 2049"),
)
_COLOURS = ("White", "Silver", "Grey", "Black", "Blue", "Red", "Brown", "Maroon")
_FUELS = ("Petrol", "Diesel", "CNG", "Electric", "Petrol/CNG")
_CLASSES = ("Motor Car (LMV)", "Motorcycle", "Goods Carrier (HGV)",
            "Light Goods Vehicle", "Omni Bus")

# Gujarat RTO codes mapped to their registering authority.
_RTO_AUTHORITIES = {
    "01": "RTO Ahmedabad", "02": "RTO Mehsana", "03": "RTO Rajkot",
    "04": "RTO Bhavnagar", "05": "RTO Surat", "06": "RTO Vadodara",
    "07": "RTO Nadiad", "08": "RTO Palanpur", "09": "RTO Himmatnagar",
    "10": "RTO Jamnagar", "11": "RTO Junagadh", "12": "RTO Bhuj",
    "15": "RTO Godhra", "16": "RTO Bharuch", "18": "RTO Gandhinagar",
    "27": "RTO Ahmedabad East",
}

# Fictional names for synthetic records. Deliberately generic so no real person
# is implied by a mock lookup.
_OWNER_FIRST = ("Ramesh", "Priya", "Anil", "Meera", "Kiran", "Sunita",
                "Vijay", "Nisha", "Harsh", "Divya")
_OWNER_LAST = ("Patel", "Shah", "Desai", "Joshi", "Mehta", "Trivedi",
               "Chauhan", "Parmar", "Solanki", "Vyas")


class MockVahanClient:
    """
    Deterministic synthetic register.

    The same registration number always returns the same record, so demonstrations
    are repeatable and a route reconstruction shows consistent vehicle details at
    every sighting. Values are derived from a hash of the plate rather than stored,
    so no lookup table has to be maintained.
    """

    def __init__(self, blacklisted: set[str] | None = None):
        # Plates the mock reports as blacklisted, for demonstrating enrichment of
        # a watchlist hit. Callers may add to this.
        self.blacklisted = {p.upper() for p in (blacklisted or set())}

    @staticmethod
    def _digest(registration_number: str) -> list[int]:
        raw = hashlib.sha256(registration_number.upper().encode()).digest()
        return list(raw)

    async def lookup(self, registration_number: str) -> VehicleRecord:
        plate = registration_number.upper().replace(" ", "").replace("-", "")
        if len(plate) < 6:
            raise VehicleNotFound(f"'{registration_number}' is not a valid registration number")

        seed = self._digest(plate)
        maker, model = _MAKER_MODELS[seed[0] % len(_MAKER_MODELS)]
        rto_code = plate[2:4] if plate[2:4].isdigit() else "01"

        registration_year = 2008 + (seed[3] % 18)
        registered = date(registration_year, 1 + seed[4] % 12, 1 + seed[5] % 28)

        def _validity(offset: int, span_days: int) -> date:
            base = date.today().toordinal() - span_days // 2 + (seed[offset] % span_days)
            return date.fromordinal(base)

        is_blacklisted = plate in self.blacklisted
        return VehicleRecord(
            registration_number=plate,
            owner_name=(f"{_OWNER_FIRST[seed[1] % len(_OWNER_FIRST)]} "
                        f"{_OWNER_LAST[seed[2] % len(_OWNER_LAST)]}"),
            vehicle_class=_CLASSES[seed[6] % len(_CLASSES)],
            maker_model=f"{maker} {model}",
            fuel_type=_FUELS[seed[7] % len(_FUELS)],
            colour=_COLOURS[seed[8] % len(_COLOURS)],
            registration_date=registered,
            registering_authority=_RTO_AUTHORITIES.get(rto_code, f"RTO {rto_code}"),
            # Never synthesise a full chassis or engine number, even fictionally.
            chassis_number_masked=f"MA{seed[9]:02X}****{seed[10]:02X}{seed[11]:02X}",
            engine_number_masked=f"{seed[12]:02X}****{seed[13]:02X}",
            insurance_valid_upto=_validity(14, 730),
            puc_valid_upto=_validity(15, 365),
            fitness_valid_upto=_validity(16, 1095),
            is_blacklisted=is_blacklisted,
            blacklist_reason="Reported stolen — mock record" if is_blacklisted else None,
            source="mock",
        )


# ─── Live implementation (not activated) ──────────────────────────────────────

class LiveVahanClient:
    """
    Real VAHAN client. Deliberately not implemented against a guessed API shape —
    inventing endpoint paths and payloads would be fiction dressed as integration.

    On credential grant this class needs: the authenticated request against
    `settings.base_url`, a mapping from VAHAN's response fields to `VehicleRecord`,
    a token-bucket rate limiter honouring `max_requests_per_minute`, and a response
    cache honouring `cache_ttl_seconds`. The surrounding platform does not change.
    """

    def __init__(self, settings: VahanSettings):
        self.settings = settings

    async def lookup(self, registration_number: str) -> VehicleRecord:
        if not self.settings.configured:
            raise VahanLookupError(
                "VAHAN credentials are not configured. This deployment uses the "
                "documented mock adapter; see DOCS/HLD.md §10."
            )
        raise NotImplementedError(
            "The live VAHAN endpoint contract is not public. Implement the request "
            "and field mapping against the agency's integration specification once "
            "credentials are issued."
        )


# ─── Factory ──────────────────────────────────────────────────────────────────

_settings = VahanSettings()


def get_vahan_client() -> VahanClient:
    """
    Return the active client.

    The mock is returned unless real credentials are configured — and the returned
    records say `source="mock"` so a caller can never present one as authoritative.
    """
    if _settings.configured:
        logger.info("VAHAN: using live client")
        return LiveVahanClient(_settings)
    logger.debug("VAHAN: credentials not configured, using documented mock adapter")
    return MockVahanClient()
