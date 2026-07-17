from __future__ import annotations

import csv
import math
import shutil
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .geometry import Projector, centroid, line_length_meters
from .kml_parser import (
    direct_folders,
    format_coordinate,
    kml_tag,
    line_coordinates,
    local_name,
    name_of,
    normalize_text,
    parent_map,
    path_names,
    remove_child,
)
from .kml_writer import STYLE_OUTBOUND, ensure_styles
from .kmz_io import read_kmz, write_kmz
from .models import Coordinate
from .report import STOP_ROUTE_EXCEL_LAYOUT, safe_excel_filename, write_route_excel

RECREATE_SUFFIX = "_ruta_recreada"
REPORT_NAME = "reporte_ruta_recreada.csv"
WARNINGS_NAME = "warnings.log"
ROUTE_EXCEL_DIR_NAME = "excel_uffizio"
GENERATED_ROOT_FOLDER_NAME = "Paradas recreadas"


@dataclass
class RouteLine:
    name: str
    folder: str
    coords: list[Coordinate]
    placemark: ET.Element


@dataclass
class RecreatedStop:
    route_name: str
    route_folder: str
    name: str
    lon: float
    lat: float
    station_meters: float
    route_length_meters: float


@dataclass
class RecreateRouteResult:
    output_kmz_path: Path
    report_csv_path: Path
    warnings_log_path: Path
    bundle_zip_path: Path
    route_count: int
    stops_created: int
    simplification_tolerance_meters: float
    min_stop_distance_meters: float
    route_excel_paths: list[Path]


def recreate_routes_with_stops(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    simplification_tolerance_meters: float = 80.0,
    min_stop_distance_meters: float = 200.0,
    create_bundle: bool = True,
) -> RecreateRouteResult:
    kmz_path = Path(input_path)
    if kmz_path.suffix.lower() != ".kmz":
        raise ValueError("Solo se aceptan archivos .kmz")
    if simplification_tolerance_meters <= 0:
        raise ValueError("La tolerancia de ruta debe ser mayor que 0")
    if min_stop_distance_meters <= 0:
        raise ValueError("La distancia minima entre paradas debe ser mayor que 0")

    parent_dir = Path(output_dir) if output_dir else kmz_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    output_stem = recreate_output_stem(kmz_path)
    output_kmz_path = parent_dir / f"{output_stem}.kmz"
    report_csv_path = parent_dir / REPORT_NAME
    warnings_log_path = parent_dir / WARNINGS_NAME
    bundle_zip_path = parent_dir / f"{output_stem}_resultados.zip"

    package = read_kmz(kmz_path)
    parents = parent_map(package.root)
    routes = collect_route_lines(package.root, parents)
    warnings = list(package.warnings)

    clear_generated_folders(package.root)
    stops_by_route: list[list[RecreatedStop]] = []
    generated_roots: dict[ET.Element, ET.Element] = {}
    all_stops: list[RecreatedStop] = []

    for route in routes:
        document = nearest_document(route.placemark, parents)
        ensure_styles(document)
        root_folder = generated_roots.get(document)
        if root_folder is None:
            root_folder = add_generated_root_folder(document)
            generated_roots[document] = root_folder

        route_stops, route_warnings = recreate_route_stops(
            route,
            simplification_tolerance_meters,
            min_stop_distance_meters,
        )
        warnings.extend(f"{route.name}: {warning}" for warning in route_warnings)
        stops_by_route.append(route_stops)
        if not route_stops:
            continue
        add_route_stop_folder(root_folder, route, route_stops)
        all_stops.extend(route_stops)

    if not routes:
        warnings.append("No se encontraron rutas LineString para recrear.")

    route_excel_paths = write_uffizio_excels(parent_dir / ROUTE_EXCEL_DIR_NAME, routes, stops_by_route, warnings)
    write_kmz(package.root, output_kmz_path, package.primary_kml_name, package.original_entries)
    write_report(report_csv_path, all_stops)
    write_warnings(warnings_log_path, warnings)
    if create_bundle:
        write_bundle(bundle_zip_path, [output_kmz_path, report_csv_path, warnings_log_path, *route_excel_paths], parent_dir)

    return RecreateRouteResult(
        output_kmz_path=output_kmz_path,
        report_csv_path=report_csv_path,
        warnings_log_path=warnings_log_path,
        bundle_zip_path=bundle_zip_path,
        route_count=len(routes),
        stops_created=len(all_stops),
        simplification_tolerance_meters=simplification_tolerance_meters,
        min_stop_distance_meters=min_stop_distance_meters,
        route_excel_paths=route_excel_paths,
    )


def recreate_output_stem(kmz_path: Path) -> str:
    stem = kmz_path.stem
    return stem if stem.lower().endswith(RECREATE_SUFFIX) else f"{stem}{RECREATE_SUFFIX}"


def collect_route_lines(root: ET.Element, parents: dict[ET.Element, ET.Element]) -> list[RouteLine]:
    routes: list[RouteLine] = []
    for placemark in root.findall(f".//{kml_tag('Placemark')}"):
        coords = line_coordinates(placemark)
        if len(coords) < 2:
            continue
        folder = " > ".join(path_names(placemark, parents))
        routes.append(
            RouteLine(
                name=name_of(placemark) or folder or "Ruta sin nombre",
                folder=folder,
                coords=coords,
                placemark=placemark,
            )
        )
    return routes


def clear_generated_folders(root: ET.Element) -> None:
    for document in root.findall(f".//{kml_tag('Document')}"):
        for folder in list(direct_folders(document)):
            if normalize_text(name_of(folder)).casefold() == GENERATED_ROOT_FOLDER_NAME.casefold():
                remove_child(document, folder)


def add_generated_root_folder(document: ET.Element) -> ET.Element:
    folder = ET.SubElement(document, kml_tag("Folder"))
    ET.SubElement(folder, kml_tag("name")).text = GENERATED_ROOT_FOLDER_NAME
    ET.SubElement(folder, kml_tag("open")).text = "1"
    return folder


def add_route_stop_folder(parent: ET.Element, route: RouteLine, stops: list[RecreatedStop]) -> None:
    route_folder = ET.SubElement(parent, kml_tag("Folder"))
    ET.SubElement(route_folder, kml_tag("name")).text = route.name
    ET.SubElement(route_folder, kml_tag("open")).text = "1"
    for stop in stops:
        placemark = ET.SubElement(route_folder, kml_tag("Placemark"))
        ET.SubElement(placemark, kml_tag("name")).text = stop.name
        ET.SubElement(placemark, kml_tag("styleUrl")).text = f"#{STYLE_OUTBOUND}"
        point = ET.SubElement(placemark, kml_tag("Point"))
        ET.SubElement(point, kml_tag("coordinates")).text = format_coordinate(stop.lon, stop.lat)


def recreate_route_stops(
    route: RouteLine,
    simplification_tolerance_meters: float,
    min_stop_distance_meters: float,
) -> tuple[list[RecreatedStop], list[str]]:
    route_length = line_length_meters(route.coords)
    if route_length <= 0:
        return [], ["La ruta no tiene longitud suficiente para generar paradas."]

    key_points = simplify_route_key_points(
        route.coords,
        simplification_tolerance_meters,
        min_stop_distance_meters,
    )
    warnings: list[str] = []
    if len(key_points) < 2:
        warnings.append("La ruta es muy corta; se genero una sola parada.")

    stops: list[RecreatedStop] = []
    for index, (lon, lat, station) in enumerate(key_points, start=1):
        stops.append(
            RecreatedStop(
                route_name=route.name,
                route_folder=route.folder,
                name=f"P{index}",
                lon=lon,
                lat=lat,
                station_meters=station,
                route_length_meters=route_length,
            )
        )
    return stops, warnings


def simplify_route_key_points(
    coords: list[Coordinate],
    simplification_tolerance_meters: float,
    min_stop_distance_meters: float,
) -> list[tuple[float, float, float]]:
    if len(coords) < 2:
        return []

    metric_points, cumulative = route_metric_points(coords)
    if len(metric_points) < 2:
        return []

    keep_indexes = {0, len(metric_points) - 1}
    collect_rdp_indexes(metric_points, 0, len(metric_points) - 1, simplification_tolerance_meters, keep_indexes)
    indexes = filter_close_indexes(sorted(keep_indexes), cumulative, min_stop_distance_meters)
    return [(coords[index][0], coords[index][1], cumulative[index]) for index in indexes]


def route_metric_points(coords: list[Coordinate]) -> tuple[list[tuple[float, float]], list[float]]:
    lon0, lat0 = centroid(coords)
    projector = Projector(lon0, lat0)
    points = [projector.project(lon, lat) for lon, lat, _ in coords]
    cumulative = [0.0]
    for start, end in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + math.hypot(end[0] - start[0], end[1] - start[1]))
    return points, cumulative


def collect_rdp_indexes(
    points: list[tuple[float, float]],
    start_index: int,
    end_index: int,
    tolerance_meters: float,
    keep_indexes: set[int],
) -> None:
    if end_index <= start_index + 1:
        return

    max_distance = -1.0
    max_index: int | None = None
    start = points[start_index]
    end = points[end_index]
    for index in range(start_index + 1, end_index):
        distance = point_segment_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            max_index = index

    if max_index is not None and max_distance > tolerance_meters:
        keep_indexes.add(max_index)
        collect_rdp_indexes(points, start_index, max_index, tolerance_meters, keep_indexes)
        collect_rdp_indexes(points, max_index, end_index, tolerance_meters, keep_indexes)


def point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.hypot(px - qx, py - qy)


def filter_close_indexes(indexes: list[int], cumulative: list[float], min_stop_distance_meters: float) -> list[int]:
    if len(indexes) <= 2:
        return indexes

    filtered = [indexes[0]]
    last_index = indexes[-1]
    for index in indexes[1:-1]:
        if cumulative[index] - cumulative[filtered[-1]] >= min_stop_distance_meters:
            filtered.append(index)

    if cumulative[last_index] - cumulative[filtered[-1]] < min_stop_distance_meters and len(filtered) > 1:
        filtered[-1] = last_index
    elif filtered[-1] != last_index:
        filtered.append(last_index)
    return filtered


def write_uffizio_excels(
    excel_dir: Path,
    routes: list[RouteLine],
    stops_by_route: list[list[RecreatedStop]],
    warnings: list[str],
) -> list[Path]:
    if excel_dir.exists():
        shutil.rmtree(excel_dir)
    excel_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for route_index, (route, stops) in enumerate(zip(routes, stops_by_route), start=1):
        if not stops:
            continue
        rows = [
            [
                stop.name,
                "",
                "",
                route.name,
                stop.name,
                f"{stop.lat:.8f}",
                f"{stop.lon:.8f}",
            ]
            for stop in stops
        ]
        path = excel_dir / f"{route_index:03d}_{safe_excel_filename(route.name)}.xlsx"
        write_route_excel(path, rows, layout=STOP_ROUTE_EXCEL_LAYOUT, warnings=warnings)
        paths.append(path)
    return paths


def write_report(path: Path, stops: list[RecreatedStop]) -> None:
    fieldnames = [
        "ruta",
        "carpeta",
        "parada",
        "lat",
        "lon",
        "distancia_acumulada_metros",
        "longitud_ruta_metros",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for stop in stops:
            writer.writerow(
                {
                    "ruta": stop.route_name,
                    "carpeta": stop.route_folder,
                    "parada": stop.name,
                    "lat": f"{stop.lat:.8f}",
                    "lon": f"{stop.lon:.8f}",
                    "distancia_acumulada_metros": f"{stop.station_meters:.1f}",
                    "longitud_ruta_metros": f"{stop.route_length_meters:.1f}",
                }
            )


def write_warnings(path: Path, warnings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(warnings) if warnings else "Sin advertencias."
    path.write_text(content + "\n", encoding="utf-8")


def write_bundle(path: Path, files: list[Path], base_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, arcname=bundle_arcname(file_path, base_dir))


def bundle_arcname(path: Path, base_dir: Path) -> str:
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.name


def nearest_document(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> ET.Element:
    current: ET.Element | None = element
    while current is not None:
        if local_name(current.tag) == "Document":
            return current
        current = parents.get(current)
    raise ValueError("El KML no contiene Document para agregar el estilo de bus.")