from __future__ import annotations

import os
import zipfile
from collections.abc import Callable
from pathlib import Path

from .geometry import (
    distance_along_line_meters,
    distance_to_line_meters,
    haversine_meters,
    line_length_meters,
    place_stop_on_route_side,
    point_at_distance_along_line,
)
from .google_places import GooglePlacesSchoolLookup
from .irregularity_report import write_irregularities_pdf
from .kml_writer import apply_corrections
from .kmz_io import make_output_paths, read_kmz, write_kml, write_kmz
from .models import CorrectedStop, Irregularity, ProcessResult, Route, RouteCorrection, School, SchoolMatch, Stop, Summary
from .osm_overpass import OpenStreetMapSchoolLookup
from .report import (
    ROUTE_EXCEL_TEMPLATE_BULK,
    build_bulk_trip_settings,
    normalize_route_excel_template,
    write_report,
    write_route_excels,
    write_route_flow_report,
    write_warnings,
)
from .route_detector import detect_routes
from .school_detector import detect_schools, match_school
from .stop_detector import order_stops


NEAR_CONSECUTIVE_STOP_METERS = 60.0
SAME_SCHOOL_DUPLICATE_STOP_METERS = 90.0
REPEATED_SCHOOL_LABEL_METERS = 150.0
FAR_REMOVED_STOP_ROUTE_METERS = 150.0
LONG_ROUTE_WITHOUT_STOPS_METERS = 1500.0
MIN_ROUTE_OFFSET_METERS = 10.0
DEFAULT_ROUTE_OFFSET_METERS = 10.0
DEFAULT_SCHOOL_RADIUS_METERS = 100.0
SchoolLookup = Callable[[float, float, float], SchoolMatch]


def process_kmz(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    output_dir: str | Path | None = None,
    offset_meters: float = DEFAULT_ROUTE_OFFSET_METERS,
    school_radius_meters: float = DEFAULT_SCHOOL_RADIUS_METERS,
    create_bundle: bool = False,
    google_places_api_key: str | None = None,
    google_places_monthly_limit: int | None = None,
    drivers_csv_path: str | Path | None = None,
    route_template_path: str | Path | None = None,
    route_excel_template: str | None = None,
    bulk_trip_type: str | None = None,
    bulk_consider_path: str | None = None,
    bulk_valid_from: str | None = None,
    bulk_valid_to: str | None = None,
    bulk_pickup_time: str | None = None,
    bulk_drop_time: str | None = None,
    bulk_add_as_address: str | None = None,
    bulk_schedule_days: str | list[str] | tuple[str, ...] | None = None,
    bulk_schedule_value: str | None = None,
    bulk_location: str | None = None,
) -> ProcessResult:
    input_file = Path(input_path)
    validate_options(input_file, offset_meters, school_radius_meters)

    kmz_path, kml_path, report_path, warnings_path = make_output_paths(input_file, output_path, output_dir)
    route_flow_path = report_path.parent / "recorrido_ruta.csv"
    irregularities_report_path = report_path.parent / "reporte_irregularidades.pdf"
    package = read_kmz(input_file)
    warnings = list(package.warnings)

    schools, school_warnings = detect_schools(package.root)
    warnings.extend(school_warnings)
    external_lookups = build_external_school_lookups(google_places_api_key, google_places_monthly_limit)
    external_school_lookup = build_chained_school_lookup(external_lookups)

    routes, route_warnings = detect_routes(package.root)
    warnings.extend(route_warnings)

    corrections: list[RouteCorrection] = []
    all_corrected_stops: list[CorrectedStop] = []
    all_irregularities: list[Irregularity] = []

    for route in routes:
        correction = correct_route(
            route,
            schools,
            offset_meters,
            school_radius_meters,
            external_school_lookup=external_school_lookup,
        )
        corrections.append(correction)
        all_corrected_stops.extend(correction.stops)
        all_irregularities.extend(correction.irregularities)
        for warning in correction.warnings:
            warnings.append(f"{route.name}: {warning}")
    for lookup in external_lookups:
        warnings.extend(lookup.warnings)

    apply_corrections(corrections)
    write_kml(package.root, kml_path)
    write_kmz(package.root, kmz_path, package.primary_kml_name, package.original_entries)
    write_report(report_path, all_corrected_stops)
    write_route_flow_report(route_flow_path, corrections)
    write_irregularities_pdf(irregularities_report_path, all_irregularities)
    route_excel_template = normalize_route_excel_template(route_excel_template, route_template_path)
    bulk_trip_settings = None
    if route_excel_template == ROUTE_EXCEL_TEMPLATE_BULK:
        bulk_trip_settings = build_bulk_trip_settings(
            trip_type=bulk_trip_type,
            consider_path=bulk_consider_path,
            valid_from=bulk_valid_from,
            valid_to=bulk_valid_to,
            pickup_time=bulk_pickup_time,
            drop_time=bulk_drop_time,
            add_as_address=bulk_add_as_address,
            schedule_days=bulk_schedule_days,
            schedule_value=bulk_schedule_value,
            location=bulk_location,
        )
    route_excel_paths = write_route_excels(
        report_path.parent / "excel_rutas",
        corrections,
        drivers_csv_path=drivers_csv_path,
        route_template_path=route_template_path,
        route_excel_template=route_excel_template,
        bulk_trip_settings=bulk_trip_settings,
        warnings=warnings,
    )
    write_warnings(warnings_path, warnings)

    bundle_path = make_bundle(
        kmz_path,
        kml_path,
        report_path,
        warnings_path,
        route_excel_paths,
        route_flow_path=route_flow_path,
        irregularities_report_path=irregularities_report_path,
    ) if create_bundle else None
    summary = build_summary(routes, schools, all_corrected_stops, warnings, all_irregularities)

    return ProcessResult(
        input_path=input_file,
        output_kmz_path=kmz_path,
        output_kml_path=kml_path,
        report_csv_path=report_path,
        route_flow_csv_path=route_flow_path,
        irregularities_report_pdf_path=irregularities_report_path,
        warnings_log_path=warnings_path,
        route_excel_paths=route_excel_paths,
        bundle_zip_path=bundle_path,
        summary=summary,
        warnings=warnings,
    )


def validate_options(input_file: Path, offset_meters: float, school_radius_meters: float) -> None:
    if input_file.suffix.lower() != ".kmz":
        raise ValueError("El archivo de entrada debe ser .kmz")
    if not input_file.exists():
        raise FileNotFoundError(f"No existe el archivo: {input_file}")
    if offset_meters < MIN_ROUTE_OFFSET_METERS:
        raise ValueError("--offset-meters debe ser mayor o igual a 10")
    if school_radius_meters <= 0:
        raise ValueError("--school-radius-meters debe ser mayor que 0")


def build_external_school_lookups(
    api_key: str | None,
    google_places_monthly_limit: int | None = None,
) -> list[OpenStreetMapSchoolLookup | GooglePlacesSchoolLookup]:
    lookups: list[OpenStreetMapSchoolLookup | GooglePlacesSchoolLookup] = [OpenStreetMapSchoolLookup()]
    google_lookup = build_google_places_lookup(api_key, google_places_monthly_limit)
    if google_lookup:
        lookups.append(google_lookup)
    return lookups


def build_google_places_lookup(
    api_key: str | None,
    monthly_limit: int | None = None,
) -> GooglePlacesSchoolLookup | None:
    api_key = api_key if api_key is not None else os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None
    if monthly_limit is None:
        monthly_limit = parse_int_env("GOOGLE_PLACES_MONTHLY_LIMIT", 5000)
    return GooglePlacesSchoolLookup(api_key, monthly_limit=monthly_limit)


def parse_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def build_chained_school_lookup(
    lookups: list[OpenStreetMapSchoolLookup | GooglePlacesSchoolLookup],
) -> SchoolLookup | None:
    if not lookups:
        return None

    def lookup(lon: float, lat: float, radius_meters: float) -> SchoolMatch:
        for provider in lookups:
            match = provider.match_school(lon, lat, radius_meters)
            if match and match.school:
                return match
        return SchoolMatch(school=None, distance_meters=None)

    return lookup


def correct_route(
    route: Route,
    schools,
    offset_meters: float,
    school_radius_meters: float,
    external_school_lookup: SchoolLookup | None = None,
) -> RouteCorrection:
    offset_meters = max(offset_meters, MIN_ROUTE_OFFSET_METERS)
    ordered_stops, ordering_method, ordering_warnings = order_stops(route)
    route_warnings = [*route.warnings, *ordering_warnings]
    corrected: list[CorrectedStop] = []
    irregularities: list[Irregularity] = []
    labeled_school_positions: list[tuple[str, float, float]] = []
    outbound_school_labels: list[tuple[str, float | None, str]] = []

    if not ordered_stops:
        irregularities.extend(find_route_gap_irregularities(route, []))
        return RouteCorrection(
            route=route,
            ordering_method=ordering_method,
            stops=[],
            warnings=route_warnings,
            irregularities=irregularities,
        )

    ordered_stops, dedupe_warnings, dedupe_irregularities = dedupe_ordered_stops(
        route.name,
        ordered_stops,
        route.line_coords,
        schools,
        school_radius_meters,
        offset_meters,
    )
    route_warnings.extend(dedupe_warnings)
    irregularities.extend(dedupe_irregularities)
    irregularities.extend(find_route_gap_irregularities(route, ordered_stops))

    for idx, stop in enumerate(ordered_stops, start=1):
        base_name = f"P{idx}"
        new_lon, new_lat, side_warnings = place_stop_on_route_side(
            stop.lon,
            stop.lat,
            route.line_coords,
            ordered_stops,
            idx - 1,
            offset_meters,
            "right",
        )
        corrected_stop = build_corrected_stop(
            route_name=route.name,
            original_name=stop.name,
            base_name=base_name,
            tipo="ida",
            original_lon=stop.lon,
            original_lat=stop.lat,
            new_lon=new_lon,
            new_lat=new_lat,
            offset_meters=offset_meters,
            is_pf=False,
            ordering_method=ordering_method,
            schools=schools,
            school_radius_meters=school_radius_meters,
            allow_school_label=True,
            labeled_school_positions=labeled_school_positions,
            external_school_lookup=external_school_lookup,
            warnings=side_warnings,
        )
        corrected.append(corrected_stop)
        outbound_school_labels.append(
            (corrected_stop.school_name, corrected_stop.school_distance_meters, corrected_stop.school_source)
        )
        if corrected_stop.school_name:
            labeled_school_positions.append(
                (corrected_stop.school_name, corrected_stop.new_lon, corrected_stop.new_lat)
            )

    for idx, (stop_index, stop) in enumerate(reversed(list(enumerate(ordered_stops))), start=len(ordered_stops) + 1):
        base_name = f"P{idx}"
        new_lon, new_lat, side_warnings = place_stop_on_route_side(
            stop.lon,
            stop.lat,
            route.line_coords,
            ordered_stops,
            stop_index,
            offset_meters,
            "left",
        )
        inherited_school_name, inherited_school_distance, inherited_school_source = outbound_school_labels[stop_index]
        corrected_stop = build_corrected_stop(
            route_name=route.name,
            original_name=stop.name,
            base_name=base_name,
            tipo="regreso",
            original_lon=stop.lon,
            original_lat=stop.lat,
            new_lon=new_lon,
            new_lat=new_lat,
            offset_meters=offset_meters,
            is_pf=False,
            ordering_method=ordering_method,
            schools=schools,
            school_radius_meters=school_radius_meters,
            allow_school_label=False,
            labeled_school_positions=None,
            forced_school_name=inherited_school_name,
            forced_school_distance_meters=inherited_school_distance,
            forced_school_source=inherited_school_source,
            warnings=side_warnings,
        )
        corrected.append(corrected_stop)

    return RouteCorrection(
        route=route,
        ordering_method=ordering_method,
        stops=corrected,
        warnings=route_warnings,
        irregularities=irregularities,
    )


def dedupe_ordered_stops(
    route_name: str,
    ordered_stops: list[Stop],
    line_coords,
    schools: list[School],
    school_radius_meters: float,
    offset_meters: float,
) -> tuple[list[Stop], list[str], list[Irregularity]]:
    kept: list[Stop] = []
    kept_meta: list[dict] = []
    warnings: list[str] = []
    irregularities: list[Irregularity] = []

    for index, stop in enumerate(ordered_stops):
        meta = stop_dedupe_meta(stop, line_coords, ordered_stops, index, schools, school_radius_meters, offset_meters)
        if kept and should_merge_stop(kept_meta[-1], meta):
            school_name = meta["school"].name if meta["school"] else "sin centro educativo"
            warnings.append(
                f"Parada duplicada consolidada cerca de {school_name}: "
                f"{stop.name or '(sin nombre)'} se unio a {kept[-1].name or '(sin nombre)'}."
            )
            irregularity = removed_stop_irregularity(route_name, stop, kept[-1], line_coords, meta)
            if irregularity:
                irregularities.append(irregularity)
            continue
        kept.append(stop)
        kept_meta.append(meta)

    return kept, warnings, irregularities


def removed_stop_irregularity(
    route_name: str,
    removed_stop: Stop,
    kept_stop: Stop,
    line_coords,
    meta: dict,
) -> Irregularity | None:
    distance_meters = meta.get("route_distance")
    if distance_meters is None or distance_meters <= FAR_REMOVED_STOP_ROUTE_METERS:
        return None
    return Irregularity(
        route_name=route_name,
        kind="removed_far_stop",
        title="Parada eliminada lejos de la ruta",
        description=(
            f"La parada {removed_stop.name or '(sin nombre)'} fue consolidada con "
            f"{kept_stop.name or '(sin nombre)'}, pero estaba a {distance_meters:.1f} m "
            f"de la linea de ruta. Umbral: {FAR_REMOVED_STOP_ROUTE_METERS:.0f} m."
        ),
        lon=removed_stop.lon,
        lat=removed_stop.lat,
        line_coords=list(line_coords or []),
        points=[
            ("Eliminada", removed_stop.lon, removed_stop.lat),
            ("Conservada", kept_stop.lon, kept_stop.lat),
        ],
        distance_meters=distance_meters,
    )


def find_route_gap_irregularities(route: Route, ordered_stops: list[Stop]) -> list[Irregularity]:
    route_length = line_length_meters(route.line_coords)
    if route_length <= LONG_ROUTE_WITHOUT_STOPS_METERS:
        return []

    if not ordered_stops:
        midpoint = point_at_distance_along_line(route.line_coords, route_length / 2)
        if midpoint is None:
            return []
        lon, lat = midpoint
        return [
            Irregularity(
                route_name=route.name,
                kind="route_gap",
                title="Ruta sin paradas detectadas",
                description=(
                    f"La ruta mide {route_length:.1f} m y no tiene paradas detectadas. "
                    f"Umbral de tramo sin paradas: {LONG_ROUTE_WITHOUT_STOPS_METERS:.0f} m."
                ),
                lon=lon,
                lat=lat,
                line_coords=list(route.line_coords),
                points=[("Ruta", lon, lat)],
                distance_meters=route_length,
            )
        ]

    ranked: list[tuple[float, Stop]] = []
    for stop in ordered_stops:
        station = distance_along_line_meters(stop.lon, stop.lat, route.line_coords)
        if station is not None:
            ranked.append((station, stop))
    if not ranked:
        return []

    ranked.sort(key=lambda item: item[0])
    anchors: list[tuple[float, str, float, float]] = [(0.0, "Inicio ruta", route.line_coords[0][0], route.line_coords[0][1])]
    anchors.extend((station, stop.name or "Parada", stop.lon, stop.lat) for station, stop in ranked)
    anchors.append((route_length, "Fin ruta", route.line_coords[-1][0], route.line_coords[-1][1]))

    irregularities: list[Irregularity] = []
    for previous, current in zip(anchors, anchors[1:]):
        previous_station, previous_label, previous_lon, previous_lat = previous
        current_station, current_label, current_lon, current_lat = current
        gap = current_station - previous_station
        if gap <= LONG_ROUTE_WITHOUT_STOPS_METERS:
            continue
        midpoint = point_at_distance_along_line(route.line_coords, previous_station + gap / 2)
        if midpoint is None:
            continue
        lon, lat = midpoint
        irregularities.append(
            Irregularity(
                route_name=route.name,
                kind="route_gap",
                title="Tramo largo sin paradas",
                description=(
                    f"Hay {gap:.1f} m de recorrido sin paradas entre {previous_label} y {current_label}. "
                    f"Umbral: {LONG_ROUTE_WITHOUT_STOPS_METERS:.0f} m."
                ),
                lon=lon,
                lat=lat,
                line_coords=list(route.line_coords),
                points=[
                    (previous_label, previous_lon, previous_lat),
                    (current_label, current_lon, current_lat),
                ],
                distance_meters=gap,
            )
        )
    return irregularities


def stop_dedupe_meta(
    stop: Stop,
    line_coords,
    ordered_stops: list[Stop],
    stop_index: int,
    schools: list[School],
    school_radius_meters: float,
    offset_meters: float,
) -> dict:
    placed_lon, placed_lat, _ = place_stop_on_route_side(
        stop.lon,
        stop.lat,
        line_coords,
        ordered_stops,
        stop_index,
        offset_meters,
        "right",
    )
    match = match_school(placed_lon, placed_lat, schools, school_radius_meters)
    return {
        "lon": stop.lon,
        "lat": stop.lat,
        "placed_lon": placed_lon,
        "placed_lat": placed_lat,
        "station": distance_along_line_meters(stop.lon, stop.lat, line_coords),
        "route_distance": distance_to_line_meters(stop.lon, stop.lat, line_coords),
        "school": match.school if match and match.school else None,
    }


def should_merge_stop(previous: dict, current: dict) -> bool:
    map_distance = haversine_meters(previous["lon"], previous["lat"], current["lon"], current["lat"])
    placed_distance = haversine_meters(
        previous["placed_lon"],
        previous["placed_lat"],
        current["placed_lon"],
        current["placed_lat"],
    )
    if min(map_distance, placed_distance) <= NEAR_CONSECUTIVE_STOP_METERS:
        return True

    if not is_same_school(previous["school"], current["school"]):
        return False

    station_gap = None
    if previous["station"] is not None and current["station"] is not None:
        station_gap = abs(previous["station"] - current["station"])

    return map_distance <= SAME_SCHOOL_DUPLICATE_STOP_METERS or placed_distance <= SAME_SCHOOL_DUPLICATE_STOP_METERS or (
        station_gap is not None and station_gap <= SAME_SCHOOL_DUPLICATE_STOP_METERS
    )


def is_same_school(first: School | None, second: School | None) -> bool:
    if first is None or second is None:
        return False
    return (
        first.name == second.name
        and round(first.lon, 6) == round(second.lon, 6)
        and round(first.lat, 6) == round(second.lat, 6)
    )


def build_corrected_stop(
    *,
    route_name: str,
    original_name: str,
    base_name: str,
    tipo: str,
    original_lon: float,
    original_lat: float,
    new_lon: float,
    new_lat: float,
    offset_meters: float,
    is_pf: bool,
    ordering_method: str,
    schools,
    school_radius_meters: float,
    allow_school_label: bool,
    labeled_school_positions: list[tuple[str, float, float]] | None,
    warnings: list[str],
    external_school_lookup: SchoolLookup | None = None,
    forced_school_name: str = "",
    forced_school_distance_meters: float | None = None,
    forced_school_source: str = "",
) -> CorrectedStop:
    match = match_school(new_lon, new_lat, schools, school_radius_meters)
    stop_warnings = list(dict.fromkeys(warnings))
    school_name = forced_school_name
    school_distance_meters = forced_school_distance_meters
    school_source = forced_school_source
    used_external_match = False

    if allow_school_label and (not match or not match.school) and external_school_lookup:
        external_match = external_school_lookup(new_lon, new_lat, school_radius_meters)
        if external_match and external_match.school:
            match = external_match
            used_external_match = True

    if allow_school_label and match and match.school:
        detected_school_name = match.school.name
        repeated_label = repeated_school_label(
            detected_school_name,
            new_lon,
            new_lat,
            labeled_school_positions or [],
        )
        if repeated_label:
            stop_warnings.append(
                f"Nombre de centro educativo omitido por repetirse a {REPEATED_SCHOOL_LABEL_METERS:.0f} m o menos."
            )
        else:
            school_name = detected_school_name
            school_distance_meters = match.distance_meters
            school_source = match.school.source
            if used_external_match:
                source = school_source or "fuente externa"
                stop_warnings.append(f"Centro educativo asignado desde {source}; no se encontro dentro del KMZ.")

    if allow_school_label and school_name and match and match.multiple_matches:
        stop_warnings.append("Multiples centros educativos dentro del radio; se uso el mas cercano.")
    new_name = f"{base_name} - {school_name}" if school_name else base_name

    return CorrectedStop(
        route_name=route_name,
        original_name=original_name,
        new_name=new_name,
        tipo=tipo,
        original_lon=original_lon,
        original_lat=original_lat,
        new_lon=new_lon,
        new_lat=new_lat,
        offset_meters=offset_meters,
        school_name=school_name,
        school_distance_meters=school_distance_meters,
        school_source=school_source,
        is_pf=is_pf,
        ordering_method=ordering_method,
        warnings=stop_warnings,
    )


def repeated_school_label(
    school_name: str,
    lon: float,
    lat: float,
    labeled_school_positions: list[tuple[str, float, float]],
) -> bool:
    for previous_school_name, previous_lon, previous_lat in labeled_school_positions:
        if previous_school_name != school_name:
            continue
        distance = haversine_meters(lon, lat, previous_lon, previous_lat)
        if distance <= REPEATED_SCHOOL_LABEL_METERS:
            return True
    return False


def build_summary(
    routes: list[Route],
    schools,
    stops: list[CorrectedStop],
    warnings: list[str],
    irregularities: list[Irregularity],
) -> Summary:
    return Summary(
        routes_processed=len(routes),
        original_stops_detected=sum(len(route.stops) for route in routes),
        new_stops_created=len(stops),
        pf_stops_created=0,
        schools_detected=len(schools),
        stops_with_school=sum(1 for stop in stops if stop.school_name),
        irregularities_count=len(irregularities),
        warnings_count=len(warnings) + sum(len(stop.warnings) for stop in stops),
    )


def make_bundle(
    kmz_path: Path,
    kml_path: Path,
    report_path: Path,
    warnings_path: Path,
    route_excel_paths: list[Path] | None = None,
    route_flow_path: Path | None = None,
    irregularities_report_path: Path | None = None,
) -> Path:
    bundle_path = kmz_path.with_name(f"{kmz_path.stem}_resultados.zip")
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [kmz_path, report_path, route_flow_path, irregularities_report_path, warnings_path]:
            if path and path.exists():
                archive.write(path, arcname=path.name)
        for path in route_excel_paths or []:
            if path.exists():
                archive.write(path, arcname=route_excel_arcname(path))
    return bundle_path


def route_excel_arcname(path: Path) -> str:
    parts = list(path.parts)
    if "excel_rutas" in parts:
        start = parts.index("excel_rutas")
        return "/".join(parts[start:])
    return f"excel_rutas/{path.name}"


def print_summary(result: ProcessResult) -> None:
    summary = result.summary
    print(f"Rutas procesadas: {summary.routes_processed}")
    print(f"Paradas originales detectadas: {summary.original_stops_detected}")
    print(f"Paradas nuevas creadas: {summary.new_stops_created}")
    print(f"Centros educativos detectados: {summary.schools_detected}")
    print(f"Paradas con centro educativo asignado: {summary.stops_with_school}")
    print(f"Excel por ruta generados: {len(result.route_excel_paths)}")
    print(f"Irregularidades detectadas: {summary.irregularities_count}")
    print(f"Advertencias: {summary.warnings_count}")
    print()
    print("KMZ generado:")
    print(result.output_kmz_path)
    print()
    print("Recorrido de rutas:")
    print(result.route_flow_csv_path)
    print()
    print("Reporte de irregularidades:")
    print(result.irregularities_report_pdf_path)
