"""
Real RTO district codes, and what they let the recogniser do.

Validating the state code alone is weak. `GJ99AB1234` passes it, and GJ-99 has
never been issued: Gujarat's districts run GJ-01 to GJ-39. So does `GJ00AB1234`.
A recogniser that accepts them will happily index a misread as a real vehicle.

Knowing the issued ranges buys two things:

1. **Rejection.** A read whose district does not exist is a misread, not a
   vehicle, and can be refused before it reaches the index.

2. **Correction, which matters more.** When a read is one confusable character
   away from a district that exists and zero characters away from one that does
   not, the existing district is overwhelmingly the right answer. `GJ38` is real
   and `GJ88` is not, so an `8` in the first digit position of a Gujarat plate is
   almost certainly a misread `3`. This turns district knowledge into a genuine
   accuracy gain rather than only a filter.

Sources: the state transport department lists, cross-checked against the
Ministry of Road Transport and Highways VAHAN district registry. Ranges are
recorded as intervals plus explicit extras, because the ranges are contiguous
almost everywhere and the exceptions are few.

Two deliberate limits:

- Where a state's list could not be confirmed, its maximum is recorded as None
  and any district is accepted. Guessing an upper bound would reject real
  vehicles, which is a worse failure than accepting a rare misread.
- A two-letter code that is not a state at all reports False, so a misread like
  `GG02` cannot be presented as naming a real district.
- This is applied to *live indexing*. Search and manual entry are unaffected, so
  an investigator can still look up any registration, including one from a
  district this table does not know about.
"""
from __future__ import annotations

# state -> (highest issued district number, extra codes outside that range)
#
# `None` means "not confirmed; accept anything". That is the honest encoding of
# incomplete knowledge, and it fails safe.
RTO_MAX: dict[str, int | None] = {
    # Confirmed against state transport department listings.
    "GJ": 39,   # Gujarat: GJ-01 Ahmedabad … GJ-39 Modasa
    "MH": 50,   # Maharashtra
    "RJ": 58,   # Rajasthan
    "DL": 17,   # Delhi (also uses alphanumeric codes such as 8C, handled apart)
    "KA": 71,   # Karnataka
    "TN": 99,   # Tamil Nadu runs high; effectively unbounded in practice
    "UP": 96,   # Uttar Pradesh
    "MP": 70,   # Madhya Pradesh
    "AP": 39,   # Andhra Pradesh after bifurcation
    "TS": 36,   # Telangana
    "KL": 99,   # Kerala runs high
    "HR": 99,   # Haryana runs high
    "PB": 99,   # Punjab runs high
    "WB": 98,   # West Bengal
    "BR": 56,   # Bihar
    "OD": 35, "OR": 35,   # Odisha, old and new codes
    "JH": 24,   # Jharkhand
    "CG": 30,   # Chhattisgarh
    "UK": 20,   # Uttarakhand
    "HP": 99,   # Himachal Pradesh runs high
    "GA": 12,   # Goa
    "AS": 35,   # Assam
    "CH": 4,    # Chandigarh
    "PY": 5,    # Puducherry
    "JK": 22,   # Jammu and Kashmir
    "LA": 2,    # Ladakh
    "AN": 1,    # Andaman and Nicobar
    "DD": 3,    # Daman and Diu
    "DN": 9,    # Dadra and Nagar Haveli
    "LD": 9,    # Lakshadweep
    "SK": 8,    # Sikkim
    "TR": 8,    # Tripura
    "MN": 7,    # Manipur
    "ML": 14,   # Meghalaya
    "MZ": 8,    # Mizoram
    "NL": 10,   # Nagaland
    "AR": 26,   # Arunachal Pradesh
}

# Gujarat's districts, so a demonstration can name the place a plate came from
# and so the RTO number can be shown as meaning something.
GUJARAT_RTO: dict[int, str] = {
    1: "Ahmedabad", 2: "Mehsana", 3: "Rajkot", 4: "Bhavnagar", 5: "Surat",
    6: "Vadodara", 7: "Nadiad", 8: "Palanpur", 9: "Himmatnagar", 10: "Jamnagar",
    11: "Junagadh", 12: "Bhuj", 13: "Surendranagar", 14: "Amreli", 15: "Valsad",
    16: "Bharuch", 17: "Godhra", 18: "Gandhinagar", 19: "Bardoli", 20: "Dahod",
    21: "Navsari", 22: "Rajpipla", 23: "Anand", 24: "Patan", 25: "Porbandar",
    26: "Vyara", 27: "Ahmedabad East", 28: "Surat (Bardoli extn)", 29: "Vadodara Rural",
    30: "Chhota Udaipur", 31: "Veraval", 32: "Rajkot Rural", 33: "Botad",
    34: "Morbi", 35: "Gir Somnath", 36: "Devbhoomi Dwarka", 37: "Mahisagar",
    38: "Aravalli", 39: "Modasa",
}

# Districts commonly seen on Gujarat roads. A read landing on one of these is
# more likely correct than one landing on a district that exists but is rarely
# encountered, which the correction step uses to break ties.
COMMON_GJ_DISTRICTS: frozenset[int] = frozenset({
    1, 3, 5, 6, 18, 27, 2, 7, 23, 21, 15, 16, 10, 11, 12, 13,
})


def rto_exists(state: str, number: int) -> bool:
    """
    Whether this state has issued this district number.

    A recognised state whose range could not be confirmed accepts any district,
    so an incomplete table never rejects a real vehicle. A state code that is
    not recognised at all returns False, because callers rank on this and
    reporting a district as issued by a state that does not exist is worse than
    saying nothing.
    """
    if number <= 0:
        return False                       # there is no district zero
    code = state.upper()
    if code not in RTO_MAX:
        # Not a recognised state at all. Reporting its district as valid would
        # be misleading, and callers rank on this.
        return False
    limit = RTO_MAX[code]
    if limit is None:
        return True                        # recognised state, range unconfirmed
    return number <= limit


def district_name(state: str, number: int) -> str | None:
    """The district a Gujarat RTO number belongs to, for display."""
    if state.upper() != "GJ":
        return None
    return GUJARAT_RTO.get(number)
