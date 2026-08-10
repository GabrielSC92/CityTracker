"""Feature search backed by OpenStreetMap.

Two free, key-less providers are queried and their results merged:

  * Photon (photon.komoot.io) -- forgiving fuzzy/prefix matching, which is what
    you want when you only half remember a name.
  * Nominatim (nominatim.openstreetmap.org) -- authoritative address breakdown,
    so a landmark like "Puy du Fou" resolves all the way down to the town it
    sits in (Les Epesses, Pays de la Loire, France).

Both are OpenStreetMap based, so results dedupe cleanly on (osm_type, osm_id)
and blank fields from one provider get filled in from the other. This makes the
search work equally well for world-famous landmarks and for small towns such as
Cachoeirinha in Rio Grande do Sul.
"""

from __future__ import annotations

import difflib
import math
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import requests

# Nominatim's usage policy requires an identifying User-Agent and at most one
# request per second. Both are honoured below.
USER_AGENT = "CityTracker/1.0 (personal offline travel map)"
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT = 12

_OSM_TYPE_LONG = {"N": "node", "W": "way", "R": "relation"}

# Address keys Nominatim may use for "the settlement this thing is in",
# most specific first.
_CITY_KEYS = (
    "city",
    "town",
    "village",
    "municipality",
    "hamlet",
    "borough",
    "suburb",
    "city_district",
    "county",
)
_STATE_KEYS = ("state", "province", "region", "state_district", "county")

# OSM place values that are themselves a settlement rather than something
# located inside one.
_SETTLEMENT_TYPES = {
    "city",
    "town",
    "village",
    "hamlet",
    "municipality",
    "borough",
    "suburb",
    "neighbourhood",
    "locality",
    "isolated_dwelling",
}

# Useless as a description: every city is a "boundary/administrative" and every
# untagged building is a "yes". Both get replaced by the provider's own
# higher-level classification when one is available.
_VAGUE_TYPES = {"administrative", "yes", "boundary"}

# The kind of thing you actually travel to, versus the street furniture that
# happens to carry the same name (Puy du Fou also names an information board).
_PREFERRED_TYPES = _SETTLEMENT_TYPES | {
    "aquarium", "archaeological_site", "artwork", "attraction", "beach",
    "castle", "cathedral", "church", "fort", "garden", "island", "memorial",
    "monastery", "monument", "mosque", "mountain_range", "museum",
    "national_park", "nature_reserve", "palace", "park", "peak", "region",
    "ruins", "stadium", "temple", "theme_park", "viewpoint", "volcano",
    "waterfall", "zoo",
}
_DEMOTED_TYPES = {
    "board", "bus_stop", "cafe", "construction", "footway", "guest_house",
    "hostel", "hotel", "house", "information", "parking", "path", "picnic_site",
    "platform", "primary", "residential", "restaurant", "secondary", "service",
    "street", "tertiary", "track", "unclassified", "yes",
}

# Two hits with the same name this close together are the same real place
# recorded twice in OSM (typically a place node plus its boundary relation).
_SAME_PLACE_KM = 15.0


class _Throttle:
    """Minimum-interval gate shared across Streamlit's script reruns."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last = time.monotonic()


_nominatim_gate = _Throttle(1.05)
_photon_gate = _Throttle(0.2)


@dataclass
class Place:
    """One search hit, normalised across providers."""

    name: str
    display_name: str = ""
    category: str = ""  # OSM key, e.g. "tourism"
    feature_type: str = ""  # OSM value, e.g. "theme_park"
    city: str = ""
    state: str = ""
    country: str = ""
    country_code: str = ""
    lat: float = 0.0
    lon: float = 0.0
    osm_type: str = ""
    osm_id: int | None = None
    sources: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, int | None]:
        return (self.osm_type, self.osm_id)

    @property
    def is_settlement(self) -> bool:
        return self.feature_type in _SETTLEMENT_TYPES

    @property
    def pretty_type(self) -> str:
        raw = self.feature_type or self.category
        return raw.replace("_", " ").title() if raw else "Place"

    @property
    def where(self) -> str:
        """"City, State, Country" with the redundant parts dropped."""
        parts: list[str] = []
        for part in (self.city, self.state, self.country):
            if part and part not in parts and part != self.name:
                parts.append(part)
        return ", ".join(parts)

    @property
    def label(self) -> str:
        where = self.where
        tail = f" — {where}" if where else ""
        return f"{self.name}{tail}  ·  {self.pretty_type}"


@dataclass
class SearchResponse:
    results: list[Place]
    warnings: list[str] = field(default_factory=list)


def _normalise(text: str) -> str:
    """Lowercase, strip accents, and reduce punctuation to spaces.

    Makes "Puy-du-Fou", "puy du fou" and "Puy du Fou" all compare equal.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() else " " for ch in stripped.lower())
    return " ".join(cleaned.split())


def _first(mapping: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = mapping.get(key)
        if value:
            return str(value)
    return ""


def _describe(osm_value: str, fallback: str) -> str:
    """Pick the more meaningful of the raw OSM value and the provider's own type."""
    if osm_value and osm_value not in _VAGUE_TYPES:
        return osm_value
    return fallback or osm_value


def _km_apart(a: Place, b: Place) -> float:
    """Equirectangular distance -- plenty accurate at the few-km scale used here."""
    mean_lat = math.radians((a.lat + b.lat) / 2)
    dx = math.radians(a.lon - b.lon) * math.cos(mean_lat)
    dy = math.radians(a.lat - b.lat)
    return 6371.0 * math.hypot(dx, dy)


def _search_nominatim(query: str, limit: int) -> list[Place]:
    _nominatim_gate.wait()
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": limit,
            "accept-language": "en",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    places: list[Place] = []
    for item in response.json():
        address = item.get("address") or {}
        name = item.get("name") or (item.get("display_name") or "").split(",")[0]
        # jsonv2's addresstype says "city"/"town" where type only says
        # "administrative", so it is the better label when both are present.
        feature_type = _describe(item.get("type") or "", item.get("addresstype") or "")
        city = _first(address, _CITY_KEYS)
        if not city and feature_type in _SETTLEMENT_TYPES:
            city = name
        places.append(
            Place(
                name=name.strip(),
                display_name=item.get("display_name", ""),
                category=item.get("category") or item.get("class") or "",
                feature_type=feature_type,
                city=city,
                state=_first(address, _STATE_KEYS),
                country=address.get("country", ""),
                country_code=(address.get("country_code") or "").upper(),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                osm_type=(item.get("osm_type") or "").lower(),
                osm_id=item.get("osm_id"),
                sources=["nominatim"],
            )
        )
    return places


def _search_photon(query: str, limit: int) -> list[Place]:
    _photon_gate.wait()
    response = requests.get(
        PHOTON_URL,
        params={"q": query, "limit": limit, "lang": "en"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    places: list[Place] = []
    for feature in response.json().get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue

        name = props.get("name") or ""
        feature_type = _describe(props.get("osm_value") or "", props.get("type") or "")
        city = props.get("city") or props.get("district") or props.get("county") or ""
        if not city and feature_type in _SETTLEMENT_TYPES:
            city = name

        bits = [name, city, props.get("state", ""), props.get("country", "")]
        display = ", ".join(dict.fromkeys(bit for bit in bits if bit))

        places.append(
            Place(
                name=name.strip(),
                display_name=display,
                category=props.get("osm_key") or "",
                feature_type=feature_type,
                city=city,
                state=props.get("state", ""),
                country=props.get("country", ""),
                country_code=(props.get("countrycode") or "").upper(),
                lat=float(coords[1]),
                lon=float(coords[0]),
                osm_type=_OSM_TYPE_LONG.get(props.get("osm_type", ""), ""),
                osm_id=props.get("osm_id"),
                sources=["photon"],
            )
        )
    return places


def _merge(base: Place, extra: Place) -> Place:
    """Fill blank fields on `base` from `extra` and record both sources."""
    for attr in (
        "display_name",
        "category",
        "feature_type",
        "city",
        "state",
        "country",
        "country_code",
    ):
        if not getattr(base, attr) and getattr(extra, attr):
            setattr(base, attr, getattr(extra, attr))
    for source in extra.sources:
        if source not in base.sources:
            base.sources.append(source)
    return base


def _score(query: str, place: Place, rank: int) -> float:
    """Rank hits by how well the name matches what was typed.

    Nominatim orders by its own importance metric, which buries a small town
    under a famous namesake. Weighting the literal name similarity puts
    "Cachoeirinha" the town above "Rua Cachoeirinha" again.
    """
    wanted = _normalise(query)
    found = _normalise(place.name)
    ratio = difflib.SequenceMatcher(None, wanted, found).ratio()

    score = 2.0 * ratio
    if found.startswith(wanted):
        score += 0.5
    if found == wanted:
        score += 0.5
    if len(place.sources) > 1:  # both providers agree it exists
        score += 0.3
    if place.feature_type in _PREFERRED_TYPES:
        score += 0.4
    elif place.feature_type in _DEMOTED_TYPES:
        score -= 1.0
    return score - 0.03 * rank


def search(query: str, limit: int = 10) -> SearchResponse:
    """Search both providers and return merged, ranked results.

    A provider that is unreachable degrades to a warning rather than an error,
    so the search still works if one of the two services is down.
    """
    query = query.strip()
    if not query:
        return SearchResponse(results=[])

    warnings: list[str] = []
    collected: list[Place] = []

    for label, fetch in (("Nominatim", _search_nominatim), ("Photon", _search_photon)):
        try:
            collected.extend(fetch(query, limit))
        except requests.RequestException as exc:
            warnings.append(f"{label} unavailable ({exc.__class__.__name__}).")

    # Pass 1: exact OSM identity, which is shared across the two providers.
    by_identity: dict[Any, Place] = {}
    identity_order: list[Any] = []
    for place in collected:
        if not place.name:
            continue
        # Results with no OSM id fall back to a coordinate key so they still dedupe.
        key = place.key if place.osm_id else ("coord", round(place.lat, 5), round(place.lon, 5))
        if key in by_identity:
            _merge(by_identity[key], place)
        else:
            by_identity[key] = place
            identity_order.append(key)

    # Pass 2: same name, same country, near-identical position. OSM records most
    # towns twice -- once as a place node, once as an administrative boundary --
    # and showing both just makes the user guess.
    unique: list[Place] = []
    for key in identity_order:
        place = by_identity[key]
        twin = next(
            (
                other
                for other in unique
                if _normalise(other.name) == _normalise(place.name)
                and other.country_code == place.country_code
                and _km_apart(other, place) <= _SAME_PLACE_KM
            ),
            None,
        )
        if twin is None:
            unique.append(place)
            continue
        # Keep whichever description is more useful, then fold the rest in.
        if twin.feature_type not in _PREFERRED_TYPES and place.feature_type in _PREFERRED_TYPES:
            twin.category, twin.feature_type = place.category, place.feature_type
        _merge(twin, place)

    ranked = sorted(
        enumerate(unique), key=lambda pair: -_score(query, pair[1], pair[0])
    )
    results = [place for _, place in ranked][:limit]

    if not results and not warnings:
        warnings.append("No matches. Try fewer words, or the local spelling.")

    return SearchResponse(results=results, warnings=warnings)
