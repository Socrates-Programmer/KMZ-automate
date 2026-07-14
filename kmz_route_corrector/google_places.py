from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .geometry import haversine_meters
from .models import School, SchoolMatch
from .school_detector import clean_school_name, has_disallowed_school_hint


GOOGLE_PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
GOOGLE_PLACES_FIELD_MASK = "places.displayName,places.location,places.types"
SCHOOL_PLACE_TYPES = ["school", "primary_school", "secondary_school"]
DEFAULT_MONTHLY_LIMIT = 5000
DEFAULT_USAGE_FILE = Path(__file__).resolve().parents[1] / "outputs" / "google_places_usage.json"


class GooglePlacesSchoolLookup:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 6.0,
        monthly_limit: int = DEFAULT_MONTHLY_LIMIT,
        usage_file: str | Path | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.monthly_budget = MonthlyRequestBudget(
            monthly_limit=monthly_limit,
            usage_file=Path(usage_file) if usage_file else DEFAULT_USAGE_FILE,
        )
        self.cache: dict[tuple[float, float, float], SchoolMatch] = {}
        self.warnings: list[str] = []
        self._warning_keys: set[str] = set()

    def match_school(self, lon: float, lat: float, radius_meters: float) -> SchoolMatch:
        if not self.api_key:
            return SchoolMatch(school=None, distance_meters=None)

        radius_meters = max(1.0, min(float(radius_meters), 50000.0))
        cache_key = (round(lon, 6), round(lat, 6), round(radius_meters, 1))
        if cache_key in self.cache:
            return self.cache[cache_key]

        allowed, budget_warning = self.monthly_budget.try_consume()
        if budget_warning:
            self._warn_once(budget_warning)
        if not allowed:
            match = SchoolMatch(school=None, distance_meters=None)
            self.cache[cache_key] = match
            return match

        try:
            payload = self._nearby_search(lon, lat, radius_meters)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            self._warn_once(f"Google Places no pudo consultar centros educativos: {short_error(exc)}")
            match = SchoolMatch(school=None, distance_meters=None)
            self.cache[cache_key] = match
            return match

        matches: list[tuple[float, School]] = []
        for place in payload.get("places", []):
            school = school_from_place(place)
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
        body = {
            "includedTypes": SCHOOL_PLACE_TYPES,
            "maxResultCount": 10,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": radius_meters,
                }
            },
        }
        request = Request(
            GOOGLE_PLACES_NEARBY_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
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


class MonthlyRequestBudget:
    def __init__(self, *, monthly_limit: int, usage_file: Path) -> None:
        self.monthly_limit = max(0, int(monthly_limit))
        self.usage_file = usage_file

    def try_consume(self) -> tuple[bool, str]:
        if self.monthly_limit <= 0:
            return False, "Google Places desactivado porque GOOGLE_PLACES_MONTHLY_LIMIT es 0."

        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            usage = self._read_usage()
            current_count = int(usage.get(month_key, 0))
            if current_count >= self.monthly_limit:
                return (
                    False,
                    f"Google Places no se consulto porque alcanzo el limite mensual local "
                    f"de {self.monthly_limit} requests.",
                )
            usage = {month_key: current_count + 1}
            self._write_usage(usage)
        except (OSError, ValueError, TypeError) as exc:
            return False, f"Google Places no se consulto porque no se pudo actualizar el contador local: {short_error(exc)}"
        return True, ""

    def _read_usage(self) -> dict[str, int]:
        if not self.usage_file.exists():
            return {}
        with self.usage_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return {}
        return {str(key): int(value) for key, value in payload.items()}

    def _write_usage(self, usage: dict[str, int]) -> None:
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_file.open("w", encoding="utf-8") as handle:
            json.dump(usage, handle, indent=2, sort_keys=True)


def school_from_place(place: dict) -> School | None:
    location = place.get("location") or {}
    lat = location.get("latitude")
    lon = location.get("longitude")
    raw_name = display_name_of(place)
    if lat is None or lon is None or not raw_name:
        return None

    clean_name = clean_school_name(raw_name)
    if not clean_name:
        return None
    if has_disallowed_school_hint(clean_name):
        return None
    return School(
        name=clean_name,
        lon=float(lon),
        lat=float(lat),
        raw_name=raw_name,
        source="Google Places",
    )


def display_name_of(place: dict) -> str:
    display_name = place.get("displayName")
    if isinstance(display_name, dict):
        return str(display_name.get("text") or "").strip()
    return ""


def short_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        details = ""
        try:
            details = exc.read().decode("utf-8", errors="replace")
        except OSError:
            details = ""
        details = details.replace("\n", " ").strip()
        if details:
            return f"HTTP {exc.code}: {details[:180]}"
        return f"HTTP {exc.code}"
    return str(exc)[:180]
