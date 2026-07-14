from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET

from .geometry import haversine_meters
from .kml_parser import name_of, parent_map, path_names, point_coordinate, simple_data
from .models import School, SchoolMatch


SCHOOL_KEYS = {"centro educativo", "centros educativos", "escuela", "escuelas", "liceo", "liceos", "instituto", "institutos", "plantel"}
SCHOOL_HINT_PATTERNS = (
    re.compile(r"\bESCUELAS?\b"),
    re.compile(r"\bCENTROS?\s+EDUCATIVOS?\b"),
    re.compile(r"\bLICEOS?\b"),
    re.compile(r"\bINSTITUTOS?\b"),
    re.compile(r"\bPLANTELES?\b"),
    re.compile(r"\bPLANTEL\b"),
)
DISALLOWED_SCHOOL_HINT_PATTERNS = (
    re.compile(r"\bCOLEGIOS?\b"),
)


def clean_school_name(value: str) -> str:
    value = value or ""
    value = re.sub(r"^\s*\d+\s*[-:]\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.upper()


def school_match_text(value: str) -> str:
    value = clean_school_name(value)
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def has_school_hint(value: str) -> bool:
    clean_value = school_match_text(value)
    return any(pattern.search(clean_value) for pattern in SCHOOL_HINT_PATTERNS)


def has_disallowed_school_hint(value: str) -> bool:
    clean_value = school_match_text(value)
    return any(pattern.search(clean_value) for pattern in DISALLOWED_SCHOOL_HINT_PATTERNS)


def school_data_values(data: dict[str, str]) -> list[str]:
    return [value for key, value in data.items() if school_match_text(key).lower() in SCHOOL_KEYS and value]


def full_school_name(placemark_name: str, data: dict[str, str]) -> tuple[str, str]:
    candidates = [placemark_name, *school_data_values(data)]
    cleaned = [
        clean_school_name(candidate)
        for candidate in candidates
        if clean_school_name(candidate) and not has_disallowed_school_hint(candidate)
    ]
    if not cleaned:
        return "", ""

    selected = next((name for name in cleaned if has_school_hint(name)), cleaned[0])
    return selected, selected


def in_corrected_stops_folder(folders: list[str]) -> bool:
    return any(school_match_text(folder) == "PARADAS CORREGIDAS" for folder in folders)


def detect_schools(root: ET.Element) -> tuple[list[School], list[str]]:
    warnings: list[str] = []
    parents = parent_map(root)
    schools_by_key: dict[tuple[float, float, str], School] = {}

    for placemark in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark"):
        coord = point_coordinate(placemark)
        if coord is None:
            continue
        placemark_name = name_of(placemark)
        data = simple_data(placemark)
        folders = path_names(placemark, parents)
        if in_corrected_stops_folder(folders):
            continue
        in_school_folder = any(has_school_hint(part) for part in folders)
        has_school_data = bool(school_data_values(data))
        has_school_name = has_school_hint(placemark_name)
        if not in_school_folder and not has_school_data and not has_school_name:
            continue

        raw_name = placemark_name or next(iter(school_data_values(data)), "")
        clean_name, display_name = full_school_name(placemark_name, data)
        if not clean_name:
            warnings.append("Se encontro un posible centro educativo sin nombre; fue omitido.")
            continue

        lon, lat, _ = coord
        key = (round(lat, 6), round(lon, 6), clean_name)
        schools_by_key.setdefault(
            key,
            School(name=display_name, lon=lon, lat=lat, raw_name=raw_name, source=" / ".join(path_names(placemark, parents))),
        )

    return list(schools_by_key.values()), warnings


def match_school(lon: float, lat: float, schools: list[School], radius_meters: float) -> SchoolMatch:
    matches: list[tuple[float, School]] = []
    for school in schools:
        distance = haversine_meters(lon, lat, school.lon, school.lat)
        if distance <= radius_meters:
            matches.append((distance, school))
    if not matches:
        return SchoolMatch(school=None, distance_meters=None)
    matches.sort(key=lambda item: item[0])
    return SchoolMatch(school=matches[0][1], distance_meters=matches[0][0], multiple_matches=len(matches) > 1)
