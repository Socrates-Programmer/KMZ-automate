from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from .models import Coordinate

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"
NS = {"k": KML_NS, "gx": GX_NS}

ET.register_namespace("", KML_NS)
ET.register_namespace("gx", GX_NS)


def kml_tag(local_name: str) -> str:
    return f"{{{KML_NS}}}{local_name}"


def gx_tag(local_name: str) -> str:
    return f"{{{GX_NS}}}{local_name}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", value).strip()


def child_text(element: ET.Element, name: str, default: str = "") -> str:
    child = element.find(kml_tag(name))
    if child is None:
        return default
    return normalize_text(child.text)


def set_child_text(element: ET.Element, name: str, value: str) -> ET.Element:
    child = element.find(kml_tag(name))
    if child is None:
        child = ET.SubElement(element, kml_tag(name))
    child.text = value
    return child


def direct_children(element: ET.Element, local: str) -> list[ET.Element]:
    return [child for child in list(element) if local_name(child.tag) == local]


def direct_folders(element: ET.Element) -> list[ET.Element]:
    return direct_children(element, "Folder")


def direct_placemarks(element: ET.Element) -> list[ET.Element]:
    return direct_children(element, "Placemark")


def name_of(element: ET.Element) -> str:
    return child_text(element, "name")


def has_geometry(placemark: ET.Element, geometry_name: str) -> bool:
    return placemark.find(f".//{kml_tag(geometry_name)}") is not None


def point_coordinate(placemark: ET.Element) -> Coordinate | None:
    point = placemark.find(f".//{kml_tag('Point')}")
    if point is None:
        return None
    coord_el = point.find(kml_tag("coordinates"))
    if coord_el is None or not coord_el.text:
        return None
    coords = parse_coordinates(coord_el.text)
    return coords[0] if coords else None


def line_coordinates(placemark: ET.Element) -> list[Coordinate]:
    line = placemark.find(f".//{kml_tag('LineString')}")
    if line is None:
        return []
    coord_el = line.find(kml_tag("coordinates"))
    if coord_el is None or not coord_el.text:
        return []
    return parse_coordinates(coord_el.text)


def parse_coordinates(raw: str) -> list[Coordinate]:
    coords: list[Coordinate] = []
    for token in re.split(r"\s+", raw.strip()):
        if not token:
            continue
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 and parts[2] != "" else None
        except ValueError:
            continue
        coords.append((lon, lat, alt))
    return coords


def format_coordinate(lon: float, lat: float, alt: float | None = None) -> str:
    if alt is None:
        alt = 0.0
    return f"{lon:.8f},{lat:.8f},{alt:.2f}"


def simple_data(placemark: ET.Element) -> dict[str, str]:
    data: dict[str, str] = {}
    for node in placemark.findall(f".//{kml_tag('SimpleData')}"):
        key = normalize_text(node.attrib.get("name"))
        if key:
            data[key] = normalize_text(node.text)
    return data


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def path_names(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> list[str]:
    names: list[str] = []
    current: ET.Element | None = element
    while current is not None:
        if local_name(current.tag) in {"Document", "Folder"}:
            value = name_of(current)
            if value:
                names.append(value)
        current = parents.get(current)
    names.reverse()
    return names


def iter_documents(root: ET.Element) -> Iterable[ET.Element]:
    yield from root.findall(f".//{kml_tag('Document')}")


def remove_child(parent: ET.Element, child: ET.Element) -> bool:
    try:
        parent.remove(child)
        return True
    except ValueError:
        return False
