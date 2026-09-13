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

# Make, model, class and fuel are chosen together, not independently.
#
# They used to be drawn from separate hash bytes, which produced records like
# "Eicher Pro 2049 · Light Goods Vehicle · Petrol" — a 4.9-tonne truck in the
# wrong class burning the wrong fuel. Nobody who knows Indian vehicles would
# read that as a real registry record, and a mock whose internal contradictions
# are visible undermines the parts of the system that are real.
#
# The fuels listed per entry are the ones actually sold for that model.
_VEHICLE_TYPES = (
    # (maker, model, class, plausible fuels)
    ("Maruti Suzuki", "Swift VXi", "Motor Car (LMV)", ("Petrol", "Petrol/CNG")),
    ("Hyundai", "Creta SX", "Motor Car (LMV)", ("Petrol", "Diesel")),
    ("Tata Motors", "Nexon XZ+", "Motor Car (LMV)", ("Petrol", "Diesel", "Electric")),
    ("Mahindra", "Bolero B6", "Motor Car (LMV)", ("Diesel",)),
    ("Honda", "City ZX", "Motor Car (LMV)", ("Petrol",)),
    ("Toyota", "Innova Crysta", "Motor Car (LMV)", ("Diesel", "Petrol")),
    ("Bajaj Auto", "Pulsar 150", "Motorcycle", ("Petrol",)),
    ("Hero MotoCorp", "Splendor Plus", "Motorcycle", ("Petrol",)),
    ("Ashok Leyland", "Dost+", "Light Goods Vehicle", ("Diesel", "Petrol/CNG")),
    ("Eicher", "Pro 2049", "Goods Carrier (HGV)", ("Diesel",)),
    ("Tata Motors", "Ace Gold", "Light Goods Vehicle", ("Diesel", "Petrol/CNG")),
    ("Force Motors", "Traveller 3350", "Omni Bus", ("Diesel",)),
)
_COLOURS = ("White", "Silver", "Grey", "Black", "Blue", "Red", "Brown", "Maroon")

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


_CUSTOM_VEHICLE_OVERRIDES: dict[str, dict[str, str]] = {
    "GJ18BF2855": {
        "owner_name": "Devam Shah",
        "maker_model": "Honda City ZX",
        "vehicle_class": "Motor Car (LMV)",
        "fuel_type": "Petrol",
        "colour": "White",
        "registering_authority": "RTO Gandhinagar",
    },
    "GJ18F2285": {
        "owner_name": "Devam Shah",
        "maker_model": "Honda City ZX",
        "vehicle_class": "Motor Car (LMV)",
        "fuel_type": "Petrol",
        "colour": "White",
        "registering_authority": "RTO Gandhinagar",
    },
    "GJ01RG1880": {
        "owner_name": "Ramesh Patel",
        "maker_model": "Hyundai Creta SX",
        "vehicle_class": "Motor Car (LMV)",
        "fuel_type": "Diesel",
        "colour": "Black",
        "registering_authority": "RTO Ahmedabad",
    },
}


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
        maker, model, vclass, fuels = _VEHICLE_TYPES[seed[0] % len(_VEHICLE_TYPES)]
        rto_code = plate[2:4] if plate[2:4].isdigit() else "01"

        registration_year = 2008 + (seed[3] % 18)
        registered = date(registration_year, 1 + seed[4] % 12, 1 + seed[5] % 28)

        def _validity(offset: int, span_days: int) -> date:
            base = date.today().toordinal() - span_days // 2 + (seed[offset] % span_days)
            return date.fromordinal(base)

        override = _CUSTOM_VEHICLE_OVERRIDES.get(plate)
        owner_name = override["owner_name"] if override else f"{_OWNER_FIRST[seed[1] % len(_OWNER_FIRST)]} {_OWNER_LAST[seed[2] % len(_OWNER_LAST)]}"
        maker_model = override["maker_model"] if override else f"{maker} {model}"
        vehicle_class = override["vehicle_class"] if override else vclass
        fuel_type = override["fuel_type"] if override else fuels[seed[7] % len(fuels)]
        colour = override["colour"] if override else _COLOURS[seed[8] % len(_COLOURS)]
        reg_auth = override["registering_authority"] if override else _RTO_AUTHORITIES.get(rto_code, f"RTO {rto_code}")

        is_blacklisted = plate in self.blacklisted
        return VehicleRecord(
            registration_number=plate,
            owner_name=owner_name,
            vehicle_class=vehicle_class,
            maker_model=maker_model,
            fuel_type=fuel_type,
            colour=colour,
            registration_date=registered,
            registering_authority=reg_auth,
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
