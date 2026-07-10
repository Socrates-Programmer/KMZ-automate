from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .geometry import haversine_meters
from .models import School, SchoolMatch
from .school_detector import clean_school_name, has_school_hint


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_SCHOOL_AMENITIES = "school|college|university|kindergarten"
OSM_SCHOOL_NAME_PATTERN = "escuela|liceo|centro educativo|instituto|colegio|plantel|politecnico|polit.cnic"


class OpenStreetMapSchoolLookup:
    def __init__(
        self,
        *,
        endpoint: str = OVERPASS_URL,
        timeout_seconds: float = 8.0,
        max_failures: int = 3,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_failures = max_failures
        self.failures = 0
        self.disabled = False
        self.cache: dict[tuple[float, float, float], SchoolMatch] = {}
        self.warnings: list[str] = []
        self._warning_keys: set[str] = set()

    def match_school(self, lon: float, lat: float, radius_meters: float) -> SchoolMatch:
        if self.disabled:
            return SchoolMatch(school=None, distance_meters=None)

        radius_meters = max(1.0, min(float(radius_meters), 1000.0))
        cache_key = (round(lon, 5), round(lat, 5), round(radius_meters, 1))
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            payload = self._nearby_search(lon, lat, radius_meters)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            self.failures += 1
            self._warn_once(f"OpenStreetMap/Overpass no pudo consultar centros educativos: {short_error(exc)}")
            if self.failures >= self.max_failures:
                self.disabled = True
                self._warn_once("OpenStreetMap/Overpass fue desactivado temporalmente por errores repetidos.")
            match = SchoolMatch(school=None, distance_meters=None)
            self.cache[cache_key] = match
            return match

        matches: list[tuple[float, School]] = []
        for element in payload.get("elements", []):
            school = school_from_osm_element(element)
            if school is None:
                continue
            distance = haversine_meters(lon, lat, school.lon, school.lat)
            if distance <= radius_meters:
                matches.append((distance, school))

        if not matches:
            match = SchoolMatch(school=None, distance_meters=None)
        else:
            matches.sort(key=lambda item: item[0])
            match = SchoolMatch(
                school=matches[0][1],
                distance_meters=matches[0][0],
                multiple_matches=len(matches) > 1,
            )
        self.cache[cache_key] = match
        return match

    def _nearby_search(self, lon: float, lat: float, radius_meters: float) -> dict:
        query = overpass_query(lon, lat, radius_meters)
        request = Request(
            self.endpoint,
            data=urlencode({"data": query}).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "KMZ-Route-Corrector/1.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _warn_once(self, warning: str) -> None:
        if warning in self._warning_keys:
            return
        self._warning_keys.add(warning)
        self.warnings.append(warning)


def overpass_query(lon: float, lat: float, radius_meters: float) -> str:
    radius = f"{radius_meters:.1f}"
    return f"""
[out:json][timeout:8];
(
  node(around:{radius},{lat:.8f},{lon:.8f})["amenity"~"^({OSM_SCHOOL_AMENITIES})$"];
  way(around:{radius},{lat:.8f},{lon:.8f})["amenity"~"^({OSM_SCHOOL_AMENITIES})$"];
  relation(around:{radius},{lat:.8f},{lon:.8f})["amenity"~"^({OSM_SCHOOL_AMENITIES})$"];
  node(around:{radius},{lat:.8f},{lon:.8f})["name"~"{OSM_SCHOOL_NAME_PATTERN}",i];
  way(around:{radius},{lat:.8f},{lon:.8f})["name"~"{OSM_SCHOOL_NAME_PATTERN}",i];
  relation(around:{radius},{lat:.8f},{lon:.8f})["name"~"{OSM_SCHOOL_NAME_PATTERN}",i];
);
out center tags;
"""


def school_from_osm_element(element: dict) -> School | None:
    lon, lat = element_coordinates(element)
    if lon is None or lat is None:
        return None

    tags = element.get("tags") or {}
    raw_name = first_present(tags, "name", "official_name", "short_name", "operator")
    if not raw_name:
        return None

    clean_name = clean_school_name(raw_name)
    if not clean_name:
        return None

    amenity = str(tags.get("amenity") or "")
    if not has_school_hint(clean_name) and amenity in OSM_SCHOOL_AMENITIES.split("|"):
        clean_name = f"CENTRO EDUCATIVO {clean_name}"

    return School(
        name=clean_name,
        lon=lon,
        lat=lat,
        raw_name=raw_name,
        source="OpenStreetMap",
    )


def element_coordinates(element: dict) -> tuple[float | None, float | None]:
    if "lon" in element and "lat" in element:
        return float(element["lon"]), float(element["lat"])
    center = element.get("center") or {}
    if "lon" in center and "lat" in center:
        return float(center["lon"]), float(center["lat"])
    return None, None


def first_present(values: dict, *keys: str) -> str:
    for key in keys:
        value = str(values.get(key) or "").strip()
        if value:
            return value
    return ""


def short_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    return str(exc)[:180]
