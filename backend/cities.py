"""
cities.py
---------
The city layer: the main cities of every state and union territory, each a
fully selectable location with its own dashboard.

Coordinates are not hand-typed - they are resolved once through the Open-Meteo
geocoding API and pinned into data/cache/cities.json, with the returned admin1
checked against the state the city is listed under so a wrong match is caught
rather than silently plotted in the wrong place.  Once resolved, a city behaves
exactly like a state: regions.build_place_frame() pulls its 2019-2024 daily
archive into the dataset schema and the Exp 1-5 code runs on it unchanged.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "cache" / "cities.json"

#: state id (from regions.REGIONS) -> the cities listed under it.
#: An entry may be "City|Search term" when the plain name is ambiguous.
CITY_SEEDS = {
    "andhra-pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Tirupati"],
    "arunachal-pradesh": ["Itanagar", "Naharlagun", "Pasighat", "Tawang"],
    "assam": ["Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Tezpur"],
    "bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga"],
    "chhattisgarh": ["Raipur", "Bhilai", "Bilaspur", "Korba", "Durg"],
    "goa": ["Panaji", "Margao", "Vasco da Gama", "Mapusa"],
    "gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar", "Jamnagar"],
    "haryana": ["Faridabad", "Gurugram", "Panipat", "Ambala", "Hisar", "Karnal"],
    "himachal-pradesh": ["Shimla", "Manali", "Dharamshala", "Mandi", "Solan"],
    "jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad", "Bokaro Steel City", "Deoghar"],
    "karnataka": ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi", "Davangere"],
    "kerala": ["Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur", "Kollam", "Kannur"],
    "madhya-pradesh": ["Bhopal", "Indore", "Gwalior", "Jabalpur", "Ujjain", "Sagar"],
    "maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Navi Mumbai",
                    "Chhatrapati Sambhajinagar|Aurangabad", "Solapur", "Kolhapur"],
    "manipur": ["Imphal", "Thoubal", "Churachandpur"],
    "meghalaya": ["Shillong", "Tura", "Jowai"],
    "mizoram": ["Aizawl", "Lunglei", "Champhai"],
    "nagaland": ["Kohima", "Dimapur", "Mokokchung"],
    "odisha": ["Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur", "Puri"],
    "punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda", "Mohali"],
    "rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota", "Ajmer", "Bikaner", "Jaisalmer"],
    "sikkim": ["Gangtok", "Namchi", "Gyalshing", "Pelling"],
    "tamil-nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem",
                   "Tirunelveli", "Ooty|Udagamandalam", "Vellore"],
    "telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Khammam"],
    "tripura": ["Agartala", "Dharmanagar", "Udaipur Tripura|Udaipur"],
    "uttar-pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Prayagraj",
                      "Ghaziabad", "Noida", "Meerut", "Bareilly"],
    "uttarakhand": ["Dehradun", "Haridwar", "Nainital", "Rishikesh", "Haldwani", "Mussoorie"],
    "west-bengal": ["Kolkata", "Howrah", "Siliguri", "Durgapur", "Asansol", "Darjeeling"],
    # union territories
    "andaman-nicobar-islands": ["Port Blair"],
    "chandigarh": ["Chandigarh"],
    "daman-diu-dadra-nagar-haveli": ["Daman", "Silvassa", "Diu"],
    "delhi": ["New Delhi", "Rohini", "Dwarka Delhi|Dwarka"],
    "jammu-kashmir": ["Srinagar", "Jammu", "Anantnag", "Baramulla", "Gulmarg"],
    "ladakh": ["Leh", "Kargil"],
    "lakshadweep": ["Kavaratti"],
    "puducherry": ["Puducherry", "Karaikal", "Mahe", "Yanam"],
}

#: admin1 strings the geocoder may return for a given state id, used to verify
#: that a resolved city really sits in the state it is listed under.
ADMIN1_ALIASES = {
    "andaman-nicobar-islands": ["Andaman and Nicobar", "Andaman & Nicobar"],
    "daman-diu-dadra-nagar-haveli": ["Dadra and Nagar Haveli and Daman and Diu",
                                     "Daman and Diu", "Dadra and Nagar Haveli"],
    "delhi": ["Delhi", "NCT of Delhi", "National Capital Territory of Delhi"],
    "jammu-kashmir": ["Jammu and Kashmir", "Jammu & Kashmir"],
    "puducherry": ["Puducherry", "Pondicherry", "Tamil Nadu", "Kerala", "Andhra Pradesh"],
    "chandigarh": ["Chandigarh"],
    "uttarakhand": ["Uttarakhand", "Uttaranchal"],
    "odisha": ["Odisha", "Orissa"],
    "karnataka": ["Karnataka"],
    "tamil-nadu": ["Tamil Nadu"],
}

#: Where the geocoder fails or answers with the wrong place, pin the coordinates
#: by hand.  Each of these was checked against the audit in this module's
#: docstring: Panaji resolved into Gujarat and Dharamshala into Uttar Pradesh,
#: and the other four returned no Indian match at all.
MANUAL_COORDS = {
    "goa-panaji": (15.4989, 73.8278),
    "himachal-pradesh-dharamshala": (32.2190, 76.3234),
    "jharkhand-bokaro-steel-city": (23.6693, 86.1511),
    "mizoram-champhai": (23.4564, 93.3269),
    "tamil-nadu-ooty": (11.4102, 76.6950),
    "jammu-kashmir-baramulla": (34.1980, 74.3636),
}

MIN_SECONDS_BETWEEN_CALLS = 1.2
_last_call_at = 0.0
_cache: dict | None = None


def slug(text: str) -> str:
    import re
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def _geocode(name: str) -> list:
    global _last_call_at
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()

    res = requests.get(GEOCODE_URL, params={"name": name, "count": 10,
                                            "language": "en", "format": "json"},
                       timeout=60)
    res.raise_for_status()
    return res.json().get("results") or []


def _matches_state(admin1: str, state_id: str, state_name: str) -> bool:
    if not admin1:
        return False
    candidates = ADMIN1_ALIASES.get(state_id, []) + [state_name]
    return any(admin1.lower() == c.lower() for c in candidates)


def resolve_all(refresh: bool = False, verbose: bool = True) -> dict:
    """
    Resolve every seeded city to coordinates, pinned in data/cache/cities.json.

    Returns {city_id: record}.  Records already in the cache are kept as-is, so
    re-running only resolves what is new.
    """
    import regions

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    resolved = {}
    if CACHE_FILE.exists() and not refresh:
        resolved = json.loads(CACHE_FILE.read_text(encoding="utf-8"))

    unresolved = []
    for state_id, entries in CITY_SEEDS.items():
        state = regions.REGION_BY_ID[state_id]
        state_name = state[1]

        for entry in entries:
            display, _, search = entry.partition("|")
            search = search or display
            city_id = f"{state_id}-{slug(display)}"
            if city_id in resolved and city_id not in MANUAL_COORDS:
                continue

            if city_id in MANUAL_COORDS:
                lat, lon = MANUAL_COORDS[city_id]
                resolved[city_id] = {
                    "id": city_id, "name": display, "state_id": state_id,
                    "state_name": state_name, "zone": state[2],
                    "latitude": lat, "longitude": lon,
                    "admin1": state_name, "population": None,
                    "verified_state": True, "pinned": True,
                }
                if verbose:
                    print(f"  {display} ({state_name}) -> {lat}, {lon}  (pinned by hand)", flush=True)
                continue

            try:
                hits = _geocode(f"{search}, India") or _geocode(search)
            except Exception as exc:
                if verbose:
                    print(f"  !! {display} ({state_name}): geocode failed - {exc}", flush=True)
                unresolved.append(city_id)
                continue

            india = [h for h in hits if h.get("country_code") == "IN"]
            exact = [h for h in india if _matches_state(h.get("admin1", ""), state_id, state_name)]
            pick = (exact or india or [None])[0]

            if pick is None:
                if verbose:
                    print(f"  !! {display} ({state_name}): no Indian match", flush=True)
                unresolved.append(city_id)
                continue

            resolved[city_id] = {
                "id": city_id,
                "name": display,
                "state_id": state_id,
                "state_name": state_name,
                "zone": state[2],
                "latitude": round(float(pick["latitude"]), 4),
                "longitude": round(float(pick["longitude"]), 4),
                "admin1": pick.get("admin1", ""),
                "population": pick.get("population"),
                "verified_state": bool(exact),
            }
            if verbose:
                flag = "" if exact else "  (admin1 mismatch: " + str(pick.get("admin1")) + ")"
                print(f"  {display} ({state_name}) -> "
                      f"{resolved[city_id]['latitude']}, {resolved[city_id]['longitude']}{flag}",
                      flush=True)

    CACHE_FILE.write_text(json.dumps(resolved, indent=1, sort_keys=True), encoding="utf-8")
    if verbose:
        print(f"\nresolved {len(resolved)} cities; {len(unresolved)} unresolved", flush=True)
    return resolved


def catalogue() -> dict:
    """{city_id: record} straight from the pinned cache."""
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    return _cache


def get(city_id: str) -> dict | None:
    return catalogue().get(city_id)
