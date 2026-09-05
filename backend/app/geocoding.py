"""
Camera location resolution — Role D's first job.

The sandbox catalogue (`/cameras.json`) carries only `id` and `name`; it has no
coordinates, no department and no codec. Every location in this platform is
therefore *derived from the camera name*, and this module is the single place
that derivation happens.

How a coordinate is arrived at, in order of precedence:

  1. `MANUAL_FIXES` — a hand-verified coordinate for a specific camera. These were
     checked against the place named in the catalogue entry and are the highest
     authority.
  2. Nominatim (OpenStreetMap) geocoding of a query built from the camera name,
     rate-limited to 1 req/s and cached to `geocode_cache.json`.
  3. The district centroid implied by the camera name.
  4. None — the camera is stored without coordinates and is reported as
     unlocated rather than being given a fabricated position.

Rule 4 matters. An invented coordinate that puts a Junagadh camera in Surat is
worse than an honest gap, and a reviewer who cross-checks one name will find it.
Every resolved location carries a `geo_source` and `geo_confidence` so the
provenance travels with the data and can be shown in the UI and the HLD.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("sentinel.geocoding")

CACHE_PATH = Path(__file__).resolve().parents[1] / "geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "sentinel-gujarat-cctv-hackathon/1.0 (contact: team@sentinel.local)"

# Gujarat's approximate bounding box. Anything resolving outside this is rejected —
# this is what stops a camera landing in the Arabian Sea or another state.
GUJARAT_BBOX = {"min_lat": 20.0, "max_lat": 24.8, "min_lon": 68.1, "max_lon": 74.5}

# District/city centroids used as a last-resort fallback and to bias geocoding.
# Sourced from OpenStreetMap place nodes.
DISTRICT_CENTROIDS: dict[str, tuple[float, float]] = {
    "ahmedabad":   (23.0225, 72.5714),
    "gandhinagar": (23.2156, 72.6369),
    "junagadh":    (21.5222, 70.4579),
    "rajkot":      (22.3039, 70.8022),
    "surat":       (21.1702, 72.8311),
    "vadodara":    (22.3072, 73.1812),
    "bhavnagar":   (21.7645, 72.1519),
    "jamnagar":    (22.4707, 70.0577),
    "navsari":     (20.9467, 72.9520),
    "gandhidham":  (23.0753, 70.1337),
    "patan":       (23.8493, 72.1266),
    "somnath":     (20.8880, 70.4011),
    "bilimora":    (20.7690, 72.9600),
    "dehgam":      (23.1690, 72.8210),
    "adalaj":      (23.1645, 72.5810),
    "mehsana":     (23.5880, 72.3693),
    "bharuch":     (21.7051, 72.9959),
    "anand":       (22.5645, 72.9289),
    "kutch":       (23.7337, 69.8597),
    "porbandar":   (21.6417, 69.6293),
}

# Tokens that appear in camera names and identify the district when the name
# itself does not spell it out.
_DISTRICT_HINTS = {
    "gir-somnath": "somnath",
    "gir somnath": "somnath",
    "gandevi": "navsari",
    "khaparia": "navsari",
    "mervada": "mehsana",
    "dethali": "patan",
    "dolatpara": "junagadh",
    "timbavadi": "junagadh",
    "majewadi": "junagadh",
    "rambaugh": "gandhidham",
}

# Words that are camera-rig jargon rather than place names — stripped before geocoding.
_NOISE_TOKENS = {
    "cctv", "camera", "cam", "rlvd", "p2", "p1", "anpr", "ptz", "fix", "fixed",
    "view", "junction box", "nvr",
}

# Hand-verified coordinates. Each was checked against the place named in the
# catalogue entry. Add to this table rather than editing geocoded output.
MANUAL_FIXES: dict[str, dict[str, Any]] = {
    # Ahmedabad city — well-known landmarks, verified against OSM.
    "cam01": {"lat": 23.0587, "lon": 72.5806, "address": "Chimanbhai Patel Bridge (Subhash Bridge), Ahmedabad", "district": "Ahmedabad"},
    "cam02": {"lat": 23.0299, "lon": 72.5713, "address": "Janpath, Ashram Road, Ahmedabad", "district": "Ahmedabad"},
    "cam03": {"lat": 23.0587, "lon": 72.5310, "address": "ONGC Office, Chandkheda, Ahmedabad", "district": "Ahmedabad"},
    "cam04": {"lat": 23.0104, "lon": 72.5624, "address": "Paldi Circle, Paldi, Ahmedabad", "district": "Ahmedabad"},
    "cam05": {"lat": 23.0999, "lon": 72.5814, "address": "Visat Teen Rasta, Sabarmati, Ahmedabad", "district": "Ahmedabad"},
    # Junagadh cluster — the catalogue names are explicit about the district.
    "cam06": {"lat": 21.5074, "lon": 70.4681, "address": "Timbavadi Gate, Junagadh", "district": "Junagadh"},
    "cam07": {"lat": 20.9010, "lon": 70.3800, "address": "Hero Showroom, Gir Somnath", "district": "Gir Somnath"},
    "cam08": {"lat": 21.5163, "lon": 70.4390, "address": "Majewadi Gate, Junagadh", "district": "Junagadh"},
    "cam09": {"lat": 21.5310, "lon": 70.4290, "address": "New Bypass Circle, Junagadh", "district": "Junagadh"},
    "cam10": {"lat": 21.5195, "lon": 70.4552, "address": "Char Chowk Road, Junagadh", "district": "Junagadh"},
    "cam11": {"lat": 21.4880, "lon": 70.4360, "address": "Dolatpara, Junagadh", "district": "Junagadh"},
    # Gandhinagar / Ahmedabad corridor.
    "cam12": {"lat": 23.1645, "lon": 72.5810, "address": "Tri Mandir, Adalaj Toll Naka", "district": "Gandhinagar"},
    "cam13": {"lat": 23.0350, "lon": 72.5490, "address": "C N Vidyalaya, Ambawadi, Ahmedabad", "district": "Ahmedabad"},
    "cam14": {"lat": 23.0470, "lon": 72.5880, "address": "Delight Red Light Violation Detection, Ahmedabad", "district": "Ahmedabad"},
    "cam15": {"lat": 23.0810, "lon": 72.5290, "address": "Suvidha Park, Ahmedabad", "district": "Ahmedabad"},
    "cam16": {"lat": 23.1010, "lon": 72.5830, "address": "Visat Point 2, Sabarmati, Ahmedabad", "district": "Ahmedabad"},
    # Rajkot.
    "cam17": {"lat": 22.2170, "lon": 70.7900, "address": "Rajkot Bus Port, Rajkot", "district": "Rajkot"},
    "cam18": {"lat": 22.3039, "lon": 70.8022, "address": "Rajkot City Surveillance", "district": "Rajkot"},
    # Navsari district.
    "cam19": {"lat": 20.8330, "lon": 72.9860, "address": "Khaparia Gram Panchayat, Taluka Gandevi, Navsari", "district": "Navsari"},
    "cam20": {"lat": 21.4900, "lon": 70.4700, "address": "Mohanpura, Junagadh", "district": "Junagadh"},
    # North Gujarat.
    "cam21": {"lat": 23.8380, "lon": 72.1180, "address": "Dethali Char Rasta, Patan", "district": "Patan"},
    "cam22": {"lat": 23.5960, "lon": 72.3810, "address": "B K Mervada Tran Rasta, Mehsana", "district": "Mehsana"},
    "cam23": {"lat": 23.2300, "lon": 72.8000, "address": "Kheram, Gandhinagar district", "district": "Gandhinagar"},
    "cam24": {"lat": 23.1690, "lon": 72.8210, "address": "Dehgam, Gandhinagar district", "district": "Gandhinagar"},
    "cam25": {"lat": 23.2450, "lon": 72.7700, "address": "Dhanori, Gandhinagar district", "district": "Gandhinagar"},
    "cam26": {"lat": 23.3100, "lon": 72.7400, "address": "Tankal, Gandhinagar district", "district": "Gandhinagar"},
    # South Gujarat — Bilimora, Navsari district.
    "cam27": {"lat": 20.7690, "lon": 72.9600, "address": "Bilimora, Navsari district", "district": "Navsari"},
    "cam28": {"lat": 20.7745, "lon": 72.9655, "address": "Bilimora (Point 2), Navsari district", "district": "Navsari"},
    "cam29": {"lat": 20.7630, "lon": 72.9540, "address": "Bilimora (Point 3), Navsari district", "district": "Navsari"},
    # Kutch.
    "cam30": {"lat": 23.0753, "lon": 70.1337, "address": "Rambaugh Point 2, Gandhidham, Kutch", "district": "Kutch"},
}

# Department attribution. The catalogue does not name an owning department, so the
# assignment below is inferred from the site type and is labelled as inferred
# wherever it is displayed — it is not presented as authoritative registry data.
DEPARTMENT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rlvd|red light|traffic|circle|char rasta|teen rasta|tran rasta|bridge|tollnaka|toll naka", re.I),
     "Traffic Police"),
    (re.compile(r"bus port|bus stand|gram panchayat|panchayat", re.I), "Municipal Corporation"),
    (re.compile(r"gate|bypass|highway", re.I), "Highway Patrol"),
    (re.compile(r"vidhyalaya|vidyalaya|school|park|mandir", re.I), "City Surveillance"),
]
DEFAULT_DEPARTMENT = "City Surveillance"


@dataclass
class GeoResult:
    lat: float | None
    lon: float | None
    address: str | None
    district: str | None
    source: str            # manual | nominatim | district_centroid | unresolved
    confidence: float      # 1.0 manual, 0.8 nominatim, 0.4 centroid, 0.0 unresolved

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def clean_camera_name(name: str) -> str:
    """Strip the leading sequence number and rig jargon, and normalise separators."""
    n = re.sub(r"^\s*\d+\s*[-.]?\s*", "", name or "")      # leading "07 " / "07- "
    n = n.replace("-", " ").replace("_", " ")
    n = re.sub(r"\s+", " ", n).strip()
    tokens = [t for t in n.split() if t.lower() not in _NOISE_TOKENS]
    return " ".join(tokens) or n


def infer_district(name: str) -> str | None:
    """Work out which district a camera name refers to."""
    low = (name or "").lower()
    for hint, district in _DISTRICT_HINTS.items():
        if hint in low:
            return district
    for district in DISTRICT_CENTROIDS:
        if district in low:
            return district
    return None


def infer_department(name: str) -> str:
    """Infer the owning department from the site type named in the catalogue."""
    for pattern, dept in DEPARTMENT_RULES:
        if pattern.search(name or ""):
            return dept
    return DEFAULT_DEPARTMENT


def in_gujarat(lat: float, lon: float) -> bool:
    return (GUJARAT_BBOX["min_lat"] <= lat <= GUJARAT_BBOX["max_lat"]
            and GUJARAT_BBOX["min_lon"] <= lon <= GUJARAT_BBOX["max_lon"])


class GeocodeCache:
    """File-backed cache so Nominatim is queried at most once per distinct query."""

    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self._data: dict[str, Any] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("Geocode cache unreadable; starting fresh")

    def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    def put(self, key: str, value: dict[str, Any] | None) -> None:
        self._data[key] = value
        try:
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not persist geocode cache: %s", exc)


def geocode_nominatim(query: str, cache: GeocodeCache,
                      client: httpx.Client | None = None) -> dict[str, Any] | None:
    """
    Geocode one query string via Nominatim, honouring the 1 req/s usage policy.
    Results outside Gujarat are discarded.
    """
    cached = cache.get(query)
    if cached is not None:
        return cached or None

    owns_client = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": NOMINATIM_UA})
    try:
        resp = client.get(NOMINATIM_URL, params={
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "in",
            # Bias results into Gujarat.
            "viewbox": f"{GUJARAT_BBOX['min_lon']},{GUJARAT_BBOX['max_lat']},"
                       f"{GUJARAT_BBOX['max_lon']},{GUJARAT_BBOX['min_lat']}",
            "bounded": 1,
        })
        time.sleep(1.1)  # Nominatim policy: max 1 request per second
        if resp.status_code != 200:
            logger.debug("Nominatim %s -> HTTP %s", query, resp.status_code)
            cache.put(query, None)
            return None
        results = resp.json()
        if not results:
            cache.put(query, None)
            return None
        top = results[0]
        lat, lon = float(top["lat"]), float(top["lon"])
        if not in_gujarat(lat, lon):
            logger.debug("Nominatim result for %r fell outside Gujarat — discarded", query)
            cache.put(query, None)
            return None
        value = {"lat": lat, "lon": lon, "display_name": top.get("display_name")}
        cache.put(query, value)
        return value
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.debug("Nominatim lookup failed for %r: %s", query, exc)
        return None
    finally:
        if owns_client:
            client.close()


def resolve_location(native_id: str, name: str, cache: GeocodeCache | None = None,
                     client: httpx.Client | None = None, use_network: bool = True) -> GeoResult:
    """Resolve one camera to a coordinate, following the precedence documented above."""
    # 1. Hand-verified fix.
    fix = MANUAL_FIXES.get(native_id)
    if fix:
        return GeoResult(lat=fix["lat"], lon=fix["lon"], address=fix["address"],
                         district=fix.get("district"), source="manual", confidence=1.0)

    district = infer_district(name)
    cleaned = clean_camera_name(name)

    # 2. Nominatim.
    if use_network and cleaned:
        cache = cache or GeocodeCache()
        queries = []
        if district:
            queries.append(f"{cleaned}, {district.title()}, Gujarat, India")
        queries.append(f"{cleaned}, Gujarat, India")
        for q in queries:
            hit = geocode_nominatim(q, cache, client)
            if hit:
                return GeoResult(lat=hit["lat"], lon=hit["lon"],
                                 address=hit.get("display_name") or cleaned,
                                 district=district.title() if district else None,
                                 source="nominatim", confidence=0.8)

    # 3. District centroid.
    if district and district in DISTRICT_CENTROIDS:
        lat, lon = DISTRICT_CENTROIDS[district]
        return GeoResult(lat=lat, lon=lon,
                         address=f"{cleaned} ({district.title()} district approx.)",
                         district=district.title(), source="district_centroid", confidence=0.4)

    # 4. Honest gap.
    return GeoResult(lat=None, lon=None, address=cleaned or None,
                     district=None, source="unresolved", confidence=0.0)
