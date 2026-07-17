from __future__ import annotations

import csv
import math
import shutil
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .geometry import Projector, centroid, distance_along_line_meters, distance_to_line_meters, project_point_on_polyline
from .kml_parser import (
    child_text,
    format_coordinate,
    kml_tag,
    line_coordinates,
    local_name,
    name_of,
    parent_map,
    path_names,
    point_coordinate,
    set_child_text,
)
from .kml_writer import STYLE_OUTBOUND, ensure_styles
from .kmz_io import read_kmz, write_kmz
from .models import Coordinate
from .report import STOP_ROUTE_EXCEL_LAYOUT, safe_excel_filename, write_route_excel

ARROW_ICON_HREF = "http://maps.google.com/mapfiles/kml/shapes/arrow.png"
BUS_ICON_HREF = "http://maps.google.com/mapfiles/kml/shapes/bus.png"
ARROW_BUS_SUFFIX = "_paradas_bus"
REPORT_NAME = "reporte_flechas_paradas.csv"
WARNINGS_NAME = "warnings.log"
ROUTE_EXCEL_DIR_NAME = "excel_uffizio"
STOP_ROUTE_OFFSET_METERS = 20.0


@dataclass
class ArrowStopResult:
    output_kmz_path: Path
    report_csv_path: Path
    warnings_log_path: Path
    bundle_zip_path: Path
    converted_count: int
    point_count: int
    route_count: int
    route_match_radius_meters: float
    route_excel_paths: list[Path]


@dataclass
class RouteLine:
    name: str
    folder: str
    coords: list[Coordinate]


@dataclass
class ConvertedArrowStop:
    name: str
    folder: str
    lon: float
    lat: float
    original_lon: float
    original_lat: float


@dataclass
class RouteStopCandidate:
    stop: ConvertedArrowStop
    distance_meters: float
    station_meters: float


def convert_arrow_points_to_bus_stops(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    route_match_radius_meters: float = 2000.0,
    create_bundle: bool = True,
) -> ArrowStopResult:
    kmz_path = Path(input_path)
    if kmz_path.suffix.lower() != ".kmz":
        raise ValueError("Solo se aceptan archivos .kmz")
    if route_match_radius_meters <= 0:
        raise ValueError("El radio de asociacion debe ser mayor que 0")

    parent_dir = Path(output_dir) if output_dir else kmz_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    output_stem = arrow_output_stem(kmz_path)
    output_kmz_path = parent_dir / f"{output_stem}.kmz"
    report_csv_path = parent_dir / REPORT_NAME
    warnings_log_path = parent_dir / WARNINGS_NAME
    bundle_zip_path = parent_dir / f"{output_stem}_resultados.zip"

    package = read_kmz(kmz_path)
    parents = parent_map(package.root)
    style_resolver = StyleResolver(package.root)
    route_lines = collect_route_lines(package.root, parents)
    warnings = list(package.warnings)

    rows: list[dict[str, str]] = []
    converted_stops: list[ConvertedArrowStop] = []
    point_count = 0
    converted_count = 0

    for placemark in package.root.findall(f".//{kml_tag('Placemark')}"):
        point = point_coordinate(placemark)
        if point is None:
            continue
        point_count += 1

        style_url = child_text(placemark, "styleUrl")
        icon_href = style_resolver.resolve(style_url)
        is_arrow_stop = is_arrow_icon(icon_href)
        is_existing_bus_stop = is_bus_stop_icon(icon_href) or style_id_from_url(style_url) == STYLE_OUTBOUND
        if not is_arrow_stop and not is_existing_bus_stop:
            continue

        document = nearest_document(placemark, parents)
        ensure_styles(document)
        set_child_text(placemark, "styleUrl", f"#{STYLE_OUTBOUND}")
        if is_arrow_stop:
            converted_count += 1

        lon, lat, alt = point
        nearest_line, nearest_distance = nearest_route(lon, lat, route_lines)
        nearest_name = nearest_line.name if nearest_line else ""
        final_lon, final_lat = lon, lat
        if nearest_line is not None:
            placed = place_point_at_route_offset(lon, lat, nearest_line.coords, STOP_ROUTE_OFFSET_METERS)
            if placed is not None:
                final_lon, final_lat = placed
                set_point_coordinate(placemark, final_lon, final_lat, alt)
            else:
                warnings.append(
                    f"No se pudo colocar a 20 m de la ruta la flecha '{name_of(placemark)}'; se mantuvo su coordenada original."
                )

        folder = " > ".join(path_names(placemark, parents))
        converted_stop = ConvertedArrowStop(
            name=name_of(placemark),
            folder=folder,
            lon=final_lon,
            lat=final_lat,
            original_lon=lon,
            original_lat=lat,
        )
        converted_stops.append(converted_stop)

        inside_radius = nearest_distance is not None and nearest_distance <= route_match_radius_meters
        rows.append(
            {
                "nombre": converted_stop.name,
                "carpeta": converted_stop.folder,
                "lat": f"{final_lat:.8f}",
                "lon": f"{final_lon:.8f}",
                "ruta_mas_cercana": nearest_name,
                "distancia_metros": "" if nearest_distance is None else f"{nearest_distance:.1f}",
                "dentro_radio": "si" if inside_radius else "no",
            }
        )

    if not route_lines:
        warnings.append("No se encontraron rutas LineString para asociar las flechas.")
    if converted_count == 0:
        warnings.append("No se encontraron puntos con icono arrow.png para convertir.")

    route_excel_paths = write_uffizio_route_excels(
        parent_dir / ROUTE_EXCEL_DIR_NAME,
        route_lines,
        converted_stops,
        route_match_radius_meters,
        warnings,
    )

    write_kmz(package.root, output_kmz_path, package.primary_kml_name, package.original_entries)
    write_report(report_csv_path, rows)
    write_warnings(warnings_log_path, warnings)
    if create_bundle:
        write_bundle(bundle_zip_path, [output_kmz_path, report_csv_path, warnings_log_path, *route_excel_paths], base_dir=parent_dir)

    return ArrowStopResult(
        output_kmz_path=output_kmz_path,
        report_csv_path=report_csv_path,
        warnings_log_path=warnings_log_path,
        bundle_zip_path=bundle_zip_path,
        converted_count=converted_count,
        point_count=point_count,
        route_count=len(route_lines),
        route_match_radius_meters=route_match_radius_meters,
        route_excel_paths=route_excel_paths,
    )


class StyleResolver:
    def __init__(self, root: ET.Element):
        self.style_hrefs: dict[str, str] = {}
        self.style_map_refs: dict[str, str] = {}
        self._load(root)

    def _load(self, root: ET.Element) -> None:
        for style in root.findall(f".//{kml_tag('Style')}"):
            style_id = style.attrib.get("id")
            if not style_id:
                continue
            icon = style.find(f".//{kml_tag('Icon')}")
            href = icon.find(kml_tag("href")) if icon is not None else None
            if href is not None and href.text:
                self.style_hrefs[style_id] = href.text.strip()

        for style_map in root.findall(f".//{kml_tag('StyleMap')}"):
            map_id = style_map.attrib.get("id")
            if not map_id:
                continue
            pairs = list(style_map.findall(kml_tag("Pair")))
            selected = self._normal_pair(pairs)
            if selected is None and pairs:
                selected = pairs[0]
            if selected is None:
                continue
            style_url = selected.find(kml_tag("styleUrl"))
            if style_url is not None and style_url.text:
                self.style_map_refs[map_id] = style_url.text.strip()

    @staticmethod
    def _normal_pair(pairs: list[ET.Element]) -> ET.Element | None:
        for pair in pairs:
            if child_text(pair, "key").lower() == "normal":
                return pair
        return None

    def resolve(self, style_url: str) -> str:
        current = (style_url or "").strip()
        seen: set[str] = set()
        for _ in range(10):
            if not current:
                return ""
            if is_icon_url(current):
                return current
            style_id = style_id_from_url(current)
            if not style_id or style_id in seen:
                return ""
            seen.add(style_id)
            if style_id in self.style_hrefs:
                return self.style_hrefs[style_id]
            current = self.style_map_refs.get(style_id, "")
        return ""


def arrow_output_stem(kmz_path: Path) -> str:
    stem = kmz_path.stem
    return stem if stem.lower().endswith(ARROW_BUS_SUFFIX) else f"{stem}{ARROW_BUS_SUFFIX}"

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
            )
        )
    return routes


def nearest_route(lon: float, lat: float, route_lines: list[RouteLine]) -> tuple[RouteLine | None, float | None]:
    best_route: RouteLine | None = None
    best_distance: float | None = None
    for route in route_lines:
        distance = distance_to_line_meters(lon, lat, route.coords)
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_route = route
            best_distance = distance
    return best_route, best_distance


def place_point_at_route_offset(
    lon: float,
    lat: float,
    line_coords: list[Coordinate],
    offset_meters: float,
) -> tuple[float, float] | None:
    if len(line_coords) < 2:
        return None

    lon0, lat0 = centroid(line_coords + [(lon, lat, None)])
    projector = Projector(lon0, lat0)
    line_xy = [projector.project(route_lon, route_lat) for route_lon, route_lat, _ in line_coords]
    point_xy = projector.project(lon, lat)
    projected = project_point_on_polyline(point_xy, line_xy)
    if projected is None:
        return None

    _, projected_xy, tangent = projected
    dx = point_xy[0] - projected_xy[0]
    dy = point_xy[1] - projected_xy[1]
    vector_length = math.hypot(dx, dy)
    if vector_length > 0.01:
        unit_x = dx / vector_length
        unit_y = dy / vector_length
    else:
        tx, ty = tangent
        unit_x = ty
        unit_y = -tx

    return projector.unproject(
        projected_xy[0] + unit_x * offset_meters,
        projected_xy[1] + unit_y * offset_meters,
    )


def set_point_coordinate(placemark: ET.Element, lon: float, lat: float, alt: float | None) -> None:
    point = placemark.find(f".//{kml_tag('Point')}")
    if point is None:
        return
    coordinates = point.find(kml_tag("coordinates"))
    if coordinates is None:
        coordinates = ET.SubElement(point, kml_tag("coordinates"))
    coordinates.text = format_coordinate(lon, lat, alt)


def write_uffizio_route_excels(
    excel_dir: Path,
    route_lines: list[RouteLine],
    stops: list[ConvertedArrowStop],
    route_match_radius_meters: float,
    warnings: list[str],
) -> list[Path]:
    if excel_dir.exists():
        shutil.rmtree(excel_dir)
    excel_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for route_index, route in enumerate(route_lines, start=1):
        candidates = route_stop_candidates(route, stops, route_match_radius_meters)
        if not candidates:
            continue
        if len(candidates) < 2:
            warnings.append(f"{route.name}: solo tiene {len(candidates)} parada asociada para Uffizio.")

        rows: list[list[str | float]] = []
        route_label = route.name
        for stop_index, candidate in enumerate(candidates, start=1):
            stop = candidate.stop
            rows.append(
                [
                    f"P{stop_index}",
                    "",
                    "",
                    route_label,
                    stop.name,
                    f"{stop.lat:.8f}",
                    f"{stop.lon:.8f}",
                ]
            )

        path = excel_dir / f"{route_index:03d}_{safe_excel_filename(route.name)}.xlsx"
        write_route_excel(path, rows, layout=STOP_ROUTE_EXCEL_LAYOUT, warnings=warnings)
        paths.append(path)

    if stops and route_lines and not paths:
        warnings.append("No se genero ningun Excel Uffizio porque ninguna flecha quedo dentro del radio de asociacion de una ruta.")
    return paths


def route_stop_candidates(
    route: RouteLine,
    stops: list[ConvertedArrowStop],
    route_match_radius_meters: float,
) -> list[RouteStopCandidate]:
    candidates: list[RouteStopCandidate] = []
    for stop in stops:
        distance = distance_to_line_meters(stop.lon, stop.lat, route.coords)
        station = distance_along_line_meters(stop.lon, stop.lat, route.coords)
        if distance is None or station is None or distance > route_match_radius_meters:
            continue
        candidates.append(RouteStopCandidate(stop=stop, distance_meters=distance, station_meters=station))

    candidates.sort(key=lambda candidate: (candidate.station_meters, candidate.distance_meters, candidate.stop.name))
    unique: list[RouteStopCandidate] = []
    seen: set[tuple[str, float, float]] = set()
    for candidate in candidates:
        stop = candidate.stop
        key = (stop.name.casefold(), round(stop.lat, 7), round(stop.lon, 7))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def nearest_document(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> ET.Element:
    current: ET.Element | None = element
    while current is not None:
        if local_name(current.tag) == "Document":
            return current
        current = parents.get(current)
    raise ValueError("El KML no contiene Document para agregar el estilo de bus.")


def style_id_from_url(style_url: str) -> str:
    if "#" in style_url:
        return style_url.rsplit("#", 1)[-1].strip()
    return style_url.strip()


def is_icon_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def is_arrow_icon(icon_href: str) -> bool:
    href = (icon_href or "").strip().lower()
    return href == ARROW_ICON_HREF or href.endswith("/mapfiles/kml/shapes/arrow.png")


def is_bus_stop_icon(icon_href: str) -> bool:
    href = (icon_href or "").strip().lower()
    return href == BUS_ICON_HREF or href.endswith("/mapfiles/kml/shapes/bus.png")

def write_report(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "nombre",
        "carpeta",
        "lat",
        "lon",
        "ruta_mas_cercana",
        "distancia_metros",
        "dentro_radio",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_warnings(path: Path, warnings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(warnings) if warnings else "Sin advertencias."
    path.write_text(content + "\n", encoding="utf-8")


def write_bundle(path: Path, files: list[Path], base_dir: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base_dir = base_dir or path.parent
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, arcname=bundle_arcname(file_path, base_dir))


def bundle_arcname(path: Path, base_dir: Path) -> str:
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.name
