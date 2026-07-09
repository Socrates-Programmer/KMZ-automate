from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .geometry import haversine_meters
from .kml_parser import name_of, parent_map, path_names, point_coordinate, simple_data
from .models import School, SchoolMatch


SCHOOL_KEYS = {"Centro educativo", "Plantel"}
SCHOOL_NAME_HINTS = ("ESCUELA", "CENTRO EDUCATIVO")


def clean_school_name(value: str) -> str:
    value = value or ""
    value = re.sub(r"^\s*\d+\s*[-:]\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.upper()


def full_school_name(placemark_name: str, data: dict[str, str]) -> tuple[str, str]:
    candidates = [
        placemark_name,
        data.get("Centro educativo", ""),
        data.get("Plantel", ""),
    ]
    cleaned = [clean_school_name(candidate) for candidate in candidates if clean_school_name(candidate)]
    if not cleaned:
        return "", ""

    selected = next((name for name in cleaned if any(hint in name for hint in SCHOOL_NAME_HINTS)), cleaned[0])
    if not any(hint in selected for hint in SCHOOL_NAME_HINTS):
        selected = f"CENTRO EDUCATIVO {selected}"
    return selected, selected


def detect_schools(root: ET.Element) -> tuple[list[School], list[str]]:
    warnings: list[str] = []
    parents = parent_map(root)
    schools_by_key: dict[tuple[float, float, str], School] = {}

    for placemark in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark"):
        coord = point_coordinate(placemark)
        if coord is None:
            continue
        data = simple_data(placemark)
        folders = [part.lower() for part in path_names(placemark, parents)]
        in_school_folder = any("escuela" in part or "centro educativo" in part for part in folders)
        has_school_data = any(key in data for key in SCHOOL_KEYS)
        if not in_school_folder and not has_school_data:
            continue

        raw_name = name_of(placemark) or data.get("Centro educativo") or data.get("Plantel") or ""
        clean_name, display_name = full_school_name(name_of(placemark), data)
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
