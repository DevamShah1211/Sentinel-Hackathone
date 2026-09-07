# Indian vehicle registration codes — reference

**What this is.** The registration-code data the Sentinel recogniser uses, with
its provenance stated per row, plus the format rules the plate grammar enforces.

**Read this first.** India has roughly one thousand RTO district codes across
thirty-six states and union territories, and they change: districts are created,
split and renumbered. This document does not claim to list them all. It states
what is verified, what is a range without enumerated districts, and what is not
covered — because in a system that will be used to identify vehicles, a
confidently wrong district name is worse than an admitted gap.

Section 5 explains how to load the complete official list when you need it.

---

## 1. The format

Since 1989, ordinary Indian registrations follow one shape:

```
  G J   0 1   A B   1 2 3 4
  └┬┘   └┬┘   └┬┘   └──┬──┘
State  RTO   Series  Serial
 (2A)  (1-2D) (0-3A)  (4D)
```

| Part | Width | Meaning |
|---|---|---|
| State code | 2 letters | State or union territory |
| RTO district | 1-2 digits | The registering office within that state |
| Series | 0-3 letters | Incremented as each serial range fills |
| Serial | 4 digits | The vehicle's number in that series |

Two variants the grammar also accepts:

**Bharat series**, for vehicles moved between states without re-registration:

```
  2 2   B H   1 2 3 4   A A
  Year   BH    Serial   Series
```

**Alphanumeric RTO codes.** Delhi issues codes such as `DL8C` and `DL3C`, where
the second character of the district block is a letter by design. The grammar
protects these explicitly — coercing that `C` into a `6` would destroy a valid
registration.

Knowing which positions must be alphabetic and which numeric is what turns the
classic confusions (O/0, I/1, S/5, B/8) into deterministic corrections rather
than guesses. That is where most of this project's ANPR accuracy comes from.

---

## 2. Gujarat — complete

All thirty-nine districts, verified against the Gujarat transport department
listing. This is the state the deployment covers, so it is the one enumerated in
full and the one the recogniser can name.

| Code | District | Code | District |
|---|---|---|---|
| GJ-01 | Ahmedabad | GJ-21 | Navsari |
| GJ-02 | Mehsana | GJ-22 | Rajpipla |
| GJ-03 | Rajkot | GJ-23 | Anand |
| GJ-04 | Bhavnagar | GJ-24 | Patan |
| GJ-05 | Surat | GJ-25 | Porbandar |
| GJ-06 | Vadodara | GJ-26 | Vyara |
| GJ-07 | Nadiad | GJ-27 | Ahmedabad East |
| GJ-08 | Palanpur | GJ-28 | Surat (Bardoli extension) |
| GJ-09 | Himmatnagar | GJ-29 | Vadodara Rural |
| GJ-10 | Jamnagar | GJ-30 | Chhota Udaipur |
| GJ-11 | Junagadh | GJ-31 | Veraval |
| GJ-12 | Bhuj | GJ-32 | Rajkot Rural |
| GJ-13 | Surendranagar | GJ-33 | Botad |
| GJ-14 | Amreli | GJ-34 | Morbi |
| GJ-15 | Valsad | GJ-35 | Gir Somnath |
| GJ-16 | Bharuch | GJ-36 | Devbhoomi Dwarka |
| GJ-17 | Godhra | GJ-37 | Mahisagar |
| GJ-18 | Gandhinagar | GJ-38 | Aravalli |
| GJ-19 | Bardoli | GJ-39 | Modasa |
| GJ-20 | Dahod | | |

### A city is not one code

Four Gujarat cities hold two RTO codes each, and the second is nowhere near the
first:

| City | Codes | Why |
|---|---|---|
| Ahmedabad | **GJ-01** and **GJ-27** | GJ-27 Ahmedabad East opened when GJ-01 filled |
| Rajkot | **GJ-03** and **GJ-32** | GJ-32 Rajkot Rural |
| Surat | **GJ-05** and **GJ-28** | GJ-28 Bardoli extension |
| Vadodara | **GJ-06** and **GJ-29** | GJ-29 Vadodara Rural |

When registrations in a district exhaust their series the state opens another
office, and it takes the next free number in the state rather than one adjacent
to the original. So Ahmedabad is GJ-01 and GJ-27, not GJ-01 and GJ-02.

**Why this matters here.** An investigator asking which Ahmedabad vehicles
passed a camera, and filtering on GJ-01, silently misses every vehicle
registered at the East office. Nothing in a plain district filter would tell
them so. `sibling_codes()` in `app/rto_codes.py` returns every code covering a
city, and the detail panel names the city beside the district, so GJ-01 and
GJ-27 do not read as unrelated places.

The same pattern exists in every large state — Mumbai, Delhi, Bengaluru,
Chennai and Hyderabad each hold several codes — but those groupings are not
enumerated here, for the reason in section 6.

**Anything above GJ-39 has never been issued.** That is why the demonstration
plates use GJ-96 to GJ-99: correctly formatted, indistinguishable to the
recogniser, and impossible to belong to a real person.

---

## 3. State and union territory codes, with issued ranges

Every code below is a real state or union territory. The **highest issued**
column is what the recogniser checks; individual district names are not
enumerated here except for Gujarat.

Confidence is stated per row, because it varies and pretending otherwise would
be misleading:

- **Verified** — small enough to confirm completely, or checked against the state listing.
- **Range** — the state is certain and the upper bound is believed current, but districts are not enumerated and the bound may lag recent reorganisation.

| Code | State / UT | Highest issued | Confidence |
|---|---|---|---|
| AN | Andaman and Nicobar Islands | 1 | Verified |
| AP | Andhra Pradesh (post-bifurcation) | 39 | Range |
| AR | Arunachal Pradesh | 26 | Range |
| AS | Assam | 35 | Range |
| BR | Bihar | 56 | Range |
| CG | Chhattisgarh | 30 | Range |
| CH | Chandigarh | 4 | Verified |
| DD | Daman and Diu | 3 | Verified |
| DL | Delhi | 17 | Verified (plus alphanumeric codes) |
| DN | Dadra and Nagar Haveli | 9 | Verified |
| GA | Goa | 12 | Verified |
| **GJ** | **Gujarat** | **39** | **Verified — see section 2** |
| HP | Himachal Pradesh | high | Range unconfirmed |
| HR | Haryana | high | Range unconfirmed |
| JH | Jharkhand | 24 | Range |
| JK | Jammu and Kashmir | 22 | Range |
| KA | Karnataka | 71 | Range |
| KL | Kerala | high | Range unconfirmed |
| LA | Ladakh | 2 | Verified |
| LD | Lakshadweep | 9 | Verified |
| MH | Maharashtra | 50 | Verified |
| ML | Meghalaya | 14 | Range |
| MN | Manipur | 7 | Verified |
| MP | Madhya Pradesh | 70 | Range |
| MZ | Mizoram | 8 | Verified |
| NL | Nagaland | 10 | Verified |
| OD / OR | Odisha (new / old code) | 35 | Range |
| PB | Punjab | high | Range unconfirmed |
| PY | Puducherry | 5 | Verified |
| RJ | Rajasthan | 58 | Verified |
| SK | Sikkim | 8 | Verified |
| TN | Tamil Nadu | high | Range unconfirmed |
| TR | Tripura | 8 | Verified |
| TS | Telangana | 36 | Range |
| UK | Uttarakhand | 20 | Range |
| UP | Uttar Pradesh | 96 | Range |
| WB | West Bengal | 98 | Range |
| BH | Bharat series | n/a | Different format entirely |

**"Range unconfirmed" fails open.** Those states accept any district number, so
the recogniser never rejects a genuine vehicle because our table is incomplete.
A state code that is not in this list at all reports its district as not
issued — `GG` is not a state, so `GG02` cannot name a real district.

---

## 4. How the recogniser uses this

Three distinct uses, and the boundary between them matters:

**It reports.** Every detection carries the district when we can name it, so an
investigator sees "GJ-18 Gandhinagar" rather than four characters.

**It breaks ties.** When a vehicle track's reads genuinely disagree at one
character position, the reading that lands on a district that exists wins. Reads
split between `GJ88` and `GJ38` settle on GJ-38 Aravalli.

**It does not rewrite.** An earlier version corrected an unissued district onto
the nearest real one. Measured on the ground-truth clip, it turned `GJ96XY4455`
into `GJ06XY4455` and `GJ97JV7219` into `GJ07JV7219` — plates every frame had
read correctly and unanimously — and accuracy fell from 6/6 to 4/6 with two
convincing false positives. Substituting one plausible registration for another
is the worst failure this system can produce, so the step was removed. See
`MEASUREMENTS.md` section 2d.

An unissued district is therefore **flagged, never corrected, and still
indexed**. Search and manual entry are unaffected: an investigator can look up
any registration, including one this table does not know.

---

## 5. Loading the complete official list

For a real deployment the table above should be replaced with the authoritative
district list, not extended by hand.

**Source.** The Ministry of Road Transport and Highways publishes RTO office
listings through the VAHAN portal at `vahan.parivahan.gov.in`, and each state
transport department publishes its own district codes. A state's own listing is
the authority for that state.

**Loading it.** `app/rto_codes.py` reads two structures: `RTO_MAX`, mapping a
state code to its highest issued district, and `GUJARAT_RTO`, mapping a district
number to its name. Extend the second pattern per state:

```python
DISTRICTS: dict[str, dict[int, str]] = {
    "GJ": {1: "Ahmedabad", ...},
    "MH": {1: "Mumbai Central", ...},
}
```

`district_name()` and `rto_exists()` are the only two functions that read this
data, so nothing else changes.

**What to preserve when you do.** Keep the fail-open rule: a state whose range
is not confirmed must accept any district. Rejecting a real vehicle because a
reference table is out of date is a worse failure than accepting a rare misread,
and district reorganisation makes any static table wrong eventually.

---

## 6. Why this document says "not verified" so often

Every claim in a submission reviewed by a forensic sciences institution should be
one the team can defend. A complete-looking table of a thousand district codes
would be more impressive than this and less honest, because the long tail is
exactly where errors hide and a reviewer who finds one wrong district reasonably
doubts the measurements too.

The data that matters for a Gujarat deployment — Gujarat's own thirty-nine
districts — is complete and verified. The rest is marked for what it is.
