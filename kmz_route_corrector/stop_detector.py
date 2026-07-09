from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .geometry import order_stops_by_line
from .kml_parser import (
    direct_folders,
    direct_placemarks,
    has_geometry,
    name_of,
    normalize_text,
    point_coordinate,
)
from .models import Route, Stop

P_NUMBER_RE = re.compile(r"^\s*P\s*(\d+)\b", re.IGNORECASE)


def is_paradas_folder(folder: ET.Element) -> bool:
    return normalize_text(name_of(folder)).lower() == "paradas"


def is_corrected_folder(folder: ET.Element) -> bool:
    return normalize_text(name_of(folder)).lower() == "paradas corregidas"


def is_waypoints_folder(folder: ET.Element) -> bool:
    return normalize_text(name_of(folder)).lower() == "waypoints"


def extract_stops_from_route(route: Route) -> list[Stop]:
    stops: list[Stop] = []
    source_index = 0

    source_folders = [node for node in route.stop_source_nodes if getattr(node, "tag", "").endswith("Folder")]
    if source_folders:
        for folder in source_folders:
            for placemark in direct_placemarks(folder):
                coord = point_coordinate(placemark)
                if coord is None:
                    continue
                lon, lat, alt = coord
                stops.append(
                    Stop(
                        name=name_of(placemark),
                        lon=lon,
                        lat=lat,
                        alt=alt,
                        element=placemark,
                        parent=folder,
                        original_index=source_index,
                        source=name_of(folder),
                    )
                )
                source_index += 1
    else:
        for placemark in route.stop_source_nodes:
            coord = point_coordinate(placemark)
            if coord is None:
                continue
            lon, lat, alt = coord
            parent = route.stop_source_parents[0] if route.stop_source_parents else route.container
            stops.append(
                Stop(
                    name=name_of(placemark),
                    lon=lon,
                    lat=lat,
                    alt=alt,
                    element=placemark,
                    parent=parent,
                    original_index=source_index,
                    source="direct",
                )
            )
            source_index += 1

    return dedupe_stops(stops, route.warnings)


def dedupe_stops(stops: list[Stop], warnings: list[str]) -> list[Stop]:
    seen: set[tuple[float, float, str]] = set()
    unique: list[Stop] = []
    for stop in stops:
        key = (round(stop.lat, 7), round(stop.lon, 7), normalize_text(stop.name).lower())
        if key in seen:
            warnings.append(f"Parada duplicada omitida: {stop.name or '(sin nombre)'}")
            continue
        seen.add(key)
        unique.append(stop)
    return unique


def order_stops(route: Route) -> tuple[list[Stop], str, list[str]]:
    stops = route.stops
    if not stops:
        return [], "sin_paradas", ["La ruta no tiene paradas detectables."]

    if route.line_coords:
        return order_stops_by_line(stops, route.line_coords)

    p_numbers: list[tuple[int, int, Stop]] = []
    all_have_p_number = True
    for idx, stop in enumerate(stops):
        match = P_NUMBER_RE.match(normalize_text(stop.name))
        if not match:
            all_have_p_number = False
            break
        p_numbers.append((int(match.group(1)), idx, stop))

    if all_have_p_number:
        p_numbers.sort(key=lambda item: (item[0], item[1]))
        return [stop for _, _, stop in p_numbers], "p_numero", []

    return stops, "orden_kml", ["No hay patron P# ni LineString; se mantuvo el orden KML."]


def direct_point_placemarks(folder: ET.Element) -> list[ET.Element]:
    return [pm for pm in direct_placemarks(folder) if has_geometry(pm, "Point")]
