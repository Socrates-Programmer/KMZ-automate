from __future__ import annotations

import zipfile
from pathlib import Path

from .geometry import distance_along_line_meters, haversine_meters, place_stop_on_route_side
from .kml_writer import apply_corrections
from .kmz_io import make_output_paths, read_kmz, write_kml, write_kmz
from .models import CorrectedStop, ProcessResult, Route, RouteCorrection, School, Stop, Summary
from .report import write_report, write_route_excels, write_warnings
from .route_detector import detect_routes
from .school_detector import detect_schools, match_school
from .stop_detector import order_stops


NEAR_CONSECUTIVE_STOP_METERS = 60.0
SAME_SCHOOL_DUPLICATE_STOP_METERS = 90.0
REPEATED_SCHOOL_LABEL_METERS = 150.0
MIN_ROUTE_OFFSET_METERS = 10.0
DEFAULT_ROUTE_OFFSET_METERS = 10.0
DEFAULT_SCHOOL_RADIUS_METERS = 100.0


def process_kmz(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    output_dir: str | Path | None = None,
    offset_meters: float = DEFAULT_ROUTE_OFFSET_METERS,
    school_radius_meters: float = DEFAULT_SCHOOL_RADIUS_METERS,
    create_bundle: bool = False,
) -> ProcessResult:
    input_file = Path(input_path)
    validate_options(input_file, offset_meters, school_radius_meters)

    kmz_path, kml_path, report_path, warnings_path = make_output_paths(input_file, output_path, output_dir)
    package = read_kmz(input_file)
    warnings = list(package.warnings)

    schools, school_warnings = detect_schools(package.root)
    warnings.extend(school_warnings)

    routes, route_warnings = detect_routes(package.root)
    warnings.extend(route_warnings)

    corrections: list[RouteCorrection] = []
    all_corrected_stops: list[CorrectedStop] = []

    for route in routes:
        correction = correct_route(route, schools, offset_meters, school_radius_meters)
        corrections.append(correction)
        all_corrected_stops.extend(correction.stops)
        for warning in correction.warnings:
            warnings.append(f"{route.name}: {warning}")

    apply_corrections(corrections)
    write_kml(package.root, kml_path)
    write_kmz(package.root, kmz_path, package.primary_kml_name, package.original_entries)
    write_report(report_path, all_corrected_stops)
    route_excel_paths = write_route_excels(report_path.parent / "excel_rutas", corrections)
    write_warnings(warnings_path, warnings)

    bundle_path = make_bundle(kmz_path, kml_path, report_path, warnings_path, route_excel_paths) if create_bundle else None
    summary = build_summary(routes, schools, all_corrected_stops, warnings)

    return ProcessResult(
        input_path=input_file,
        output_kmz_path=kmz_path,
        output_kml_path=kml_path,
        report_csv_path=report_path,
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


def correct_route(
    route: Route,
    schools,
    offset_meters: float,
    school_radius_meters: float,
) -> RouteCorrection:
    offset_meters = max(offset_meters, MIN_ROUTE_OFFSET_METERS)
    ordered_stops, ordering_method, ordering_warnings = order_stops(route)
    route_warnings = [*route.warnings, *ordering_warnings]
    corrected: list[CorrectedStop] = []
    labeled_school_positions: list[tuple[str, float, float]] = []

    if not ordered_stops:
        return RouteCorrection(route=route, ordering_method=ordering_method, stops=[], warnings=route_warnings)

    ordered_stops, dedupe_warnings = dedupe_ordered_stops(
        ordered_stops,
        route.line_coords,
        schools,
        school_radius_meters,
        offset_meters,
    )
    route_warnings.extend(dedupe_warnings)

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
            warnings=side_warnings,
        )
        corrected.append(corrected_stop)
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
            warnings=side_warnings,
        )
        corrected.append(corrected_stop)

    return RouteCorrection(route=route, ordering_method=ordering_method, stops=corrected, warnings=route_warnings)


def dedupe_ordered_stops(
    ordered_stops: list[Stop],
    line_coords,
    schools: list[School],
    school_radius_meters: float,
    offset_meters: float,
) -> tuple[list[Stop], list[str]]:
    kept: list[Stop] = []
    kept_meta: list[dict] = []
    warnings: list[str] = []

    for index, stop in enumerate(ordered_stops):
        meta = stop_dedupe_meta(stop, line_coords, ordered_stops, index, schools, school_radius_meters, offset_meters)
        if kept and should_merge_stop(kept_meta[-1], meta):
            school_name = meta["school"].name if meta["school"] else "sin centro educativo"
            warnings.append(
                f"Parada duplicada consolidada cerca de {school_name}: "
                f"{stop.name or '(sin nombre)'} se unio a {kept[-1].name or '(sin nombre)'}."
            )
            continue
        kept.append(stop)
        kept_meta.append(meta)

    return kept, warnings


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
) -> CorrectedStop:
    match = match_school(new_lon, new_lat, schools, school_radius_meters)
    stop_warnings = list(dict.fromkeys(warnings))
    school_name = ""
    school_distance_meters = None

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

    if school_name and match and match.multiple_matches:
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


def build_summary(routes: list[Route], schools, stops: list[CorrectedStop], warnings: list[str]) -> Summary:
    return Summary(
        routes_processed=len(routes),
        original_stops_detected=sum(len(route.stops) for route in routes),
        new_stops_created=len(stops),
        pf_stops_created=0,
        schools_detected=len(schools),
        stops_with_school=sum(1 for stop in stops if stop.school_name),
        warnings_count=len(warnings) + sum(len(stop.warnings) for stop in stops),
    )


def make_bundle(
    kmz_path: Path,
    kml_path: Path,
    report_path: Path,
    warnings_path: Path,
    route_excel_paths: list[Path] | None = None,
) -> Path:
    bundle_path = kmz_path.with_name(f"{kmz_path.stem}_resultados.zip")
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [kmz_path, report_path, warnings_path]:
            if path.exists():
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
    print(f"Advertencias: {summary.warnings_count}")
    print()
    print("KMZ generado:")
    print(result.output_kmz_path)
