from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .kml_parser import (
    direct_folders,
    direct_placemarks,
    has_geometry,
    iter_documents,
    line_coordinates,
    name_of,
    normalize_text,
    parent_map,
)
from .models import Route
from .stop_detector import direct_point_placemarks, extract_stops_from_route, is_corrected_folder, is_paradas_folder, is_waypoints_folder


def detect_routes(root: ET.Element) -> tuple[list[Route], list[str]]:
    warnings: list[str] = []
    parents = parent_map(root)
    routes: list[Route] = []
    candidate_folders: set[ET.Element] = set()

    for document in iter_documents(root):
        for folder in document.findall(".//{http://www.opengis.net/kml/2.2}Folder"):
            if is_route_folder(folder):
                candidate_folders.add(folder)

    for folder in list(candidate_folders):
        if has_route_ancestor_with_stops(folder, candidate_folders, parents):
            continue
        document = nearest_document(folder, parents)
        if document is None:
            continue
        route = build_folder_route(folder, document, parents)
        if route is not None:
            routes.append(route)

    routes.extend(detect_document_level_routes(root, candidate_folders))

    for route in routes:
        route.stops = extract_stops_from_route(route)
        if route.is_no_operar:
            route.warnings.append("Ruta marcada como 'no operar'; fue procesada de todos modos.")
        if not route.stops:
            route.warnings.append("No se detectaron paradas para esta ruta.")

    return routes, warnings


def is_route_folder(folder: ET.Element) -> bool:
    lname = normalize_text(name_of(folder)).lower()
    if lname in {"paradas", "escuelas", "waypoints", "paradas corregidas"}:
        return False

    direct_lines = direct_line_placemarks(folder)
    direct_stops = direct_point_placemarks(folder)
    stop_folders = direct_stop_folders(folder)
    nested_line = first_line_in_direct_child(folder) is not None
    nested_route_child = has_direct_route_child(folder)
    has_route_name = "ruta" in lname

    if has_route_name and (direct_lines or direct_stops or stop_folders or (nested_line and not nested_route_child)):
        return True
    if direct_lines and (direct_stops or stop_folders):
        return True
    return False


def has_route_ancestor_with_stops(
    folder: ET.Element,
    candidates: set[ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> bool:
    parent = parents.get(folder)
    while parent is not None:
        if parent in candidates and direct_stop_folders(parent):
            return True
        parent = parents.get(parent)
    return False


def nearest_document(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> ET.Element | None:
    current = element
    while current is not None:
        if current.tag.endswith("Document"):
            return current
        current = parents.get(current)
    return None


def build_folder_route(folder: ET.Element, document: ET.Element, parents: dict[ET.Element, ET.Element]) -> Route | None:
    name = name_of(folder) or "Ruta sin nombre"
    line_pm = first_direct_line(folder)
    if line_pm is None:
        line_pm = first_line_in_direct_child(folder)
    line_coords = line_coordinates(line_pm) if line_pm is not None else []

    paradas_folders = [child for child in direct_folders(folder) if is_paradas_folder(child)]
    corrected_folders = [child for child in direct_folders(folder) if is_corrected_folder(child)]
    stop_folders = paradas_folders or corrected_folders
    warnings: list[str] = []
    if len(stop_folders) > 1:
        warnings.append("La ruta tiene multiples carpetas de paradas; se unieron y deduplicaron.")

    if stop_folders:
        stop_nodes = [*stop_folders]
        stop_parents = [folder]
    else:
        stop_nodes = direct_point_placemarks(folder)
        stop_parents = [folder]

    return Route(
        name=name,
        container=folder,
        document=document,
        line_placemark=line_pm,
        line_coords=line_coords,
        stop_source_nodes=stop_nodes,
        stop_source_parents=stop_parents,
        warnings=warnings,
        is_no_operar="no operar" in name.lower(),
        source_kind="folder",
        district_name=nearest_parent_folder_name(folder, parents) or name_of(document) or "Sin distrito",
    )


def detect_document_level_routes(root: ET.Element, folder_routes: set[ET.Element]) -> list[Route]:
    routes: list[Route] = []
    for document in iter_documents(root):
        direct_lines = direct_line_placemarks(document)
        if not direct_lines:
            continue
        stop_folders = [
            child for child in direct_folders(document)
            if (is_waypoints_folder(child) or is_paradas_folder(child) or is_corrected_folder(child)) and child not in folder_routes
        ]
        if not stop_folders:
            continue
        line_pm = direct_lines[0]
        name = name_of(line_pm) or name_of(document) or "Ruta sin nombre"
        route = Route(
            name=name,
            container=document,
            document=document,
            line_placemark=line_pm,
            line_coords=line_coordinates(line_pm),
            stop_source_nodes=stop_folders,
            stop_source_parents=[document],
            warnings=[],
            is_no_operar="no operar" in name.lower(),
            source_kind="document",
            district_name=name_of(document) or "Sin distrito",
        )
        routes.append(route)
    return routes


def nearest_parent_folder_name(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    current = parents.get(element)
    fallback = ""
    while current is not None:
        if current.tag.endswith("Folder"):
            name = name_of(current)
            if name and not fallback:
                fallback = name
            if name and not is_route_like_folder_name(name):
                return name
        current = parents.get(current)
    return fallback


def is_route_like_folder_name(name: str) -> bool:
    lname = normalize_text(name).lower()
    return bool(re.search(r"\bruta\s*[_#:\-]*\s*\d+\b", lname))


def has_direct_route_child(folder: ET.Element) -> bool:
    return any(is_route_like_folder_name(name_of(child)) for child in direct_folders(folder))


def direct_stop_folders(folder: ET.Element) -> list[ET.Element]:
    paradas_folders = [child for child in direct_folders(folder) if is_paradas_folder(child)]
    if paradas_folders:
        return paradas_folders
    return [child for child in direct_folders(folder) if is_corrected_folder(child)]


def direct_line_placemarks(element: ET.Element) -> list[ET.Element]:
    return [pm for pm in direct_placemarks(element) if has_geometry(pm, "LineString")]


def first_direct_line(folder: ET.Element) -> ET.Element | None:
    lines = direct_line_placemarks(folder)
    return lines[0] if lines else None


def first_line_in_direct_child(folder: ET.Element) -> ET.Element | None:
    for child in direct_folders(folder):
        lines = direct_line_placemarks(child)
        if lines:
            return lines[0]
    return None
