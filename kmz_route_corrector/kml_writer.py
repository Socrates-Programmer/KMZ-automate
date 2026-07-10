from __future__ import annotations

import xml.etree.ElementTree as ET

from .kml_parser import direct_folders, format_coordinate, kml_tag, normalize_text, remove_child
from .models import CorrectedStop, RouteCorrection
from .stop_detector import is_corrected_folder

STYLE_OUTBOUND = "kmzrc_stop_outbound"


def apply_corrections(corrections: list[RouteCorrection]) -> None:
    for correction in corrections:
        ensure_styles(correction.route.document)
        remove_old_stop_nodes(correction)
        if correction.stops:
            add_corrected_stop_folders(correction)


def ensure_styles(document: ET.Element) -> None:
    existing = {child.attrib.get("id") for child in list(document) if child.tag == kml_tag("Style")}
    styles = [
        (STYLE_OUTBOUND, "http://maps.google.com/mapfiles/kml/shapes/bus.png", "ffffffff", "1.1"),
    ]
    insert_at = 0
    for style_id, icon_href, color, scale in styles:
        if style_id in existing:
            continue
        style = ET.Element(kml_tag("Style"), {"id": style_id})
        icon_style = ET.SubElement(style, kml_tag("IconStyle"))
        ET.SubElement(icon_style, kml_tag("color")).text = color
        ET.SubElement(icon_style, kml_tag("scale")).text = scale
        icon = ET.SubElement(icon_style, kml_tag("Icon"))
        ET.SubElement(icon, kml_tag("href")).text = icon_href
        label_style = ET.SubElement(style, kml_tag("LabelStyle"))
        ET.SubElement(label_style, kml_tag("scale")).text = "0.8"
        document.insert(insert_at, style)
        insert_at += 1


def remove_old_stop_nodes(correction: RouteCorrection) -> None:
    route = correction.route
    for folder in list(direct_folders(route.container)):
        if is_corrected_folder(folder):
            remove_child(route.container, folder)

    for node in list(route.stop_source_nodes):
        if node not in list(route.container):
            continue
        remove_child(route.container, node)


def add_corrected_stop_folders(correction: RouteCorrection) -> None:
    route = correction.route
    root_folder = ET.SubElement(route.container, kml_tag("Folder"))
    ET.SubElement(root_folder, kml_tag("name")).text = "Paradas corregidas"
    ET.SubElement(root_folder, kml_tag("open")).text = "1"

    for stop in correction.stops:
        add_stop_placemark(root_folder, stop)


def add_stop_placemark(parent: ET.Element, stop: CorrectedStop) -> None:
    placemark = ET.SubElement(parent, kml_tag("Placemark"))
    ET.SubElement(placemark, kml_tag("name")).text = normalize_text(stop.new_name)
    ET.SubElement(placemark, kml_tag("styleUrl")).text = f"#{STYLE_OUTBOUND}"
    if stop.school_name:
        description = f"Centro educativo detectado: {stop.school_name}"
        if stop.school_distance_meters is not None:
            description += f" ({stop.school_distance_meters:.1f} m)"
        if stop.school_source in {"OpenStreetMap", "Google Places"}:
            description += f"\nFuente: {stop.school_source}"
        ET.SubElement(placemark, kml_tag("description")).text = description
    point = ET.SubElement(placemark, kml_tag("Point"))
    ET.SubElement(point, kml_tag("coordinates")).text = format_coordinate(stop.new_lon, stop.new_lat)
