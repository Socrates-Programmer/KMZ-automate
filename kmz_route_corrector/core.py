from __future__ import annotations

import os
import re
import zipfile
from collections import Counter
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
from .school_detector import detect_schools, has_school_hint, match_school, school_match_text
from .stop_detector import order_stops


NEAR_CONSECUTIVE_STOP_METERS = 60.0
NEAR_CONSECUTIVE_STOP_FLOW_METERS = 85.0
SAME_SCHOOL_DUPLICATE_STOP_METERS = 90.0
GENERATED_PARALLEL_DUPLICATE_STOP_METERS = 30.0
GENERATED_ROUTE_OVERLAP_DUPLICATE_STOP_METERS = 100.0
SCHOOL_CLUSTER_DUPLICATE_STOP_METERS = 180.0
FAR_REMOVED_STOP_ROUTE_METERS = 150.0
LONG_ROUTE_WITHOUT_STOPS_METERS = 1500.0
MIN_ROUTE_OFFSET_METERS = 10.0
DEFAULT_ROUTE_OFFSET_METERS = 10.0
DEFAULT_SCHOOL_RADIUS_METERS = 400.0
SchoolLookup = Callable[[float, float, float], SchoolMatch]
EXTERNAL_SCHOOL_SOURCES = {"OpenStreetMap", "Google Places"}
SCHOOL_NAME_REFINEMENT_STOPWORDS = {
    "CENTRO",
    "EDUCATIVO",
    "ESCUELA",
    "ESCUELAS",
    "BASICA",
    "BASICAS",
    "PRIMARIA",
    "PRIMARIAS",
    "RURAL",
    "LICEO",
    "LICEOS",
    "INSTITUTO",
    "INSTITUTOS",
    "PLANTEL",
    "PLANTELES",
}


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

    if not ordered_stops:
        irregularities.extend(find_route_gap_irregularities(route, []))
        irregularities.extend(find_schools_near_route_without_stops(route, schools, [], school_radius_meters))
        return RouteCorrection(
            route=route,
            ordering_method=ordering_method,
            stops=[],
            warnings=route_warnings,
            irregularities=irregularities,
        )

    original_ordered_stops = list(ordered_stops)
    irregularities.extend(find_route_gap_irregularities(route, original_ordered_stops))

    ordered_stops, dedupe_warnings, dedupe_irregularities = dedupe_ordered_stops(
        route.name,
        route.district_name,
        ordered_stops,
        route.line_coords,
        schools,
        school_radius_meters,
        offset_meters,
    )
    route_warnings.extend(dedupe_warnings)
    irregularities.extend(dedupe_irregularities)

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
            allow_school_label=False,
            labeled_school_positions=None,
            warnings=side_warnings,
        )
        corrected.append(corrected_stop)

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

    corrected, generated_warnings, generated_irregularities = prune_generated_duplicate_stops(route, corrected)
    route_warnings.extend(generated_warnings)
    irregularities.extend(generated_irregularities)
    corrected, school_cluster_warnings, school_cluster_irregularities = prune_school_cluster_duplicate_stops(
        route,
        corrected,
        schools,
        school_radius_meters,
    )
    route_warnings.extend(school_cluster_warnings)
    irregularities.extend(school_cluster_irregularities)
    school_label_warnings = assign_school_labels_to_corrected_stops(
        route,
        corrected,
        schools,
        school_radius_meters,
        external_school_lookup,
    )
    route_warnings.extend(school_label_warnings)
    irregularities.extend(find_created_stop_mismatch_irregularities(route, ordered_stops, corrected))
    irregularities.extend(find_schools_near_route_without_stops(route, schools, corrected, school_radius_meters))

    return RouteCorrection(
        route=route,
        ordering_method=ordering_method,
        stops=corrected,
        warnings=route_warnings,
        irregularities=irregularities,
    )


def dedupe_ordered_stops(
    route_name: str,
    district_name: str,
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
            irregularity = removed_stop_irregularity(route_name, district_name, stop, kept[-1], line_coords, meta)
            if irregularity:
                irregularities.append(irregularity)
            continue
        kept.append(stop)
        kept_meta.append(meta)

    return kept, warnings, irregularities


def prune_generated_duplicate_stops(
    route: Route,
    corrected_stops: list[CorrectedStop],
) -> tuple[list[CorrectedStop], list[str], list[Irregularity]]:
    warnings: list[str] = []
    irregularities: list[Irregularity] = []
    kept_by_type: dict[str, list[CorrectedStop]] = {}
    removed_pair_keys: set[tuple[str, float, float]] = set()

    for stop in corrected_stops:
        pair_key = corrected_stop_pair_key(stop)
        if pair_key in removed_pair_keys:
            continue
        previous_same_type = kept_by_type.setdefault(stop.tipo, [])
        duplicate_of: CorrectedStop | None = None
        duplicate_distance: float | None = None
        duplicate_reason = ""

        if previous_same_type:
            previous = previous_same_type[-1]
            distance = haversine_meters(previous.new_lon, previous.new_lat, stop.new_lon, stop.new_lat)
            if distance <= GENERATED_PARALLEL_DUPLICATE_STOP_METERS:
                duplicate_of = previous
                duplicate_distance = distance
                duplicate_reason = "ida/vuelta paralela"

        if duplicate_of is None and len(previous_same_type) > 1:
            closest_previous, closest_distance = closest_generated_stop(stop, previous_same_type[:-1])
            if closest_previous and closest_distance <= GENERATED_ROUTE_OVERLAP_DUPLICATE_STOP_METERS:
                duplicate_of = closest_previous
                duplicate_distance = closest_distance
                duplicate_reason = "la ruta vuelve a pasar por el mismo lugar"

        if duplicate_of is not None and duplicate_distance is not None:
            warnings.append(
                f"Parada corregida duplicada omitida por {duplicate_reason}: "
                f"{stop.new_name} quedo a {duplicate_distance:.1f} m de {duplicate_of.new_name}."
            )
            irregularities.append(generated_duplicate_stop_irregularity(route, stop, duplicate_of, duplicate_distance))
            removed_pair_keys.add(pair_key)
            continue

        previous_same_type.append(stop)

    if not removed_pair_keys:
        return corrected_stops, warnings, irregularities

    kept = [stop for stop in corrected_stops if corrected_stop_pair_key(stop) not in removed_pair_keys]
    if len(kept) != len(corrected_stops):
        renumber_corrected_stops(kept)
    return kept, warnings, irregularities


def closest_generated_stop(
    stop: CorrectedStop,
    candidates: list[CorrectedStop],
) -> tuple[CorrectedStop | None, float]:
    closest: CorrectedStop | None = None
    closest_distance = float("inf")
    for candidate in candidates:
        distance = haversine_meters(candidate.new_lon, candidate.new_lat, stop.new_lon, stop.new_lat)
        if distance < closest_distance:
            closest = candidate
            closest_distance = distance
    return closest, closest_distance


def generated_duplicate_stop_irregularity(
    route: Route,
    removed_stop: CorrectedStop,
    kept_stop: CorrectedStop,
    distance_meters: float,
) -> Irregularity:
    return Irregularity(
        route_name=route.name,
        district_name=route.district_name or "Sin distrito",
        kind="generated_duplicate_stop",
        title="Parada corregida duplicada por ida/vuelta paralela",
        description=(
            f"La parada corregida {removed_stop.new_name} fue omitida porque quedo a "
            f"{distance_meters:.1f} m de {kept_stop.new_name} en el mismo sentido. "
            f"Cuando la ruta vuelve a pasar por la misma calle, no se duplica esa parada."
        ),
        lon=removed_stop.new_lon,
        lat=removed_stop.new_lat,
        line_coords=list(route.line_coords),
        points=[
            (f"Omitida {removed_stop.new_name}", removed_stop.new_lon, removed_stop.new_lat),
            (f"Conservada {kept_stop.new_name}", kept_stop.new_lon, kept_stop.new_lat),
        ],
        distance_meters=distance_meters,
    )


def renumber_corrected_stops(stops: list[CorrectedStop]) -> None:
    for index, stop in enumerate(stops, start=1):
        base_name = f"P{index}"
        stop.new_name = f"{base_name} - {stop.school_name}" if stop.school_name else base_name


def corrected_stop_pair_key(stop: CorrectedStop) -> tuple[str, float, float]:
    return (stop.original_name, round(stop.original_lon, 7), round(stop.original_lat, 7))


def prune_school_cluster_duplicate_stops(
    route: Route,
    corrected_stops: list[CorrectedStop],
    schools: list[School],
    school_radius_meters: float,
) -> tuple[list[CorrectedStop], list[str], list[Irregularity]]:
    if not schools or not corrected_stops:
        return corrected_stops, [], []

    removed_pair_keys: set[tuple[str, float, float]] = set()
    warnings: list[str] = []
    irregularities: list[Irregularity] = []

    for school in schools:
        for tipo in ("ida", "regreso"):
            candidates = school_cluster_candidates(
                corrected_stops,
                removed_pair_keys,
                schools,
                school,
                tipo,
                school_radius_meters,
            )
            if len(candidates) < 2:
                continue

            kept_distance, kept_index, kept_stop = candidates[0]
            for distance, index, stop in candidates[1:]:
                pair_key = corrected_stop_pair_key(stop)
                if pair_key in removed_pair_keys:
                    continue
                stop_gap = haversine_meters(kept_stop.new_lon, kept_stop.new_lat, stop.new_lon, stop.new_lat)
                if stop_gap > SCHOOL_CLUSTER_DUPLICATE_STOP_METERS:
                    continue
                removed_pair_keys.add(pair_key)
                warnings.append(
                    f"Parada duplicada omitida cerca de {school.name}: "
                    f"{stop.new_name} quedo a {stop_gap:.1f} m de {kept_stop.new_name}; "
                    f"se conservo la parada mas cercana al centro ({kept_distance:.1f} m)."
                )
                irregularities.append(school_cluster_duplicate_irregularity(route, stop, kept_stop, stop_gap, school))

    if not removed_pair_keys:
        return corrected_stops, warnings, irregularities

    kept = [stop for stop in corrected_stops if corrected_stop_pair_key(stop) not in removed_pair_keys]
    renumber_corrected_stops(kept)
    return kept, warnings, irregularities


def school_cluster_candidates(
    stops: list[CorrectedStop],
    removed_pair_keys: set[tuple[str, float, float]],
    schools: list[School],
    school: School,
    tipo: str,
    school_radius_meters: float,
) -> list[tuple[float, int, CorrectedStop]]:
    candidates: list[tuple[float, int, CorrectedStop]] = []
    for index, stop in enumerate(stops):
        if corrected_stop_pair_key(stop) in removed_pair_keys or stop.tipo != tipo:
            continue
        if nearest_school_for_stop(stop, schools, school_radius_meters) is not school:
            continue
        distance = haversine_meters(stop.new_lon, stop.new_lat, school.lon, school.lat)
        if distance <= school_radius_meters:
            candidates.append((distance, index, stop))
    candidates.sort(key=lambda item: item[0])
    return candidates


def nearest_school_for_stop(
    stop: CorrectedStop,
    schools: list[School],
    school_radius_meters: float,
) -> School | None:
    nearest_school: School | None = None
    nearest_distance = float("inf")
    for school in schools:
        distance = haversine_meters(stop.new_lon, stop.new_lat, school.lon, school.lat)
        if distance <= school_radius_meters and distance < nearest_distance:
            nearest_school = school
            nearest_distance = distance
    return nearest_school


def school_cluster_duplicate_irregularity(
    route: Route,
    removed_stop: CorrectedStop,
    kept_stop: CorrectedStop,
    distance_meters: float,
    school: School,
) -> Irregularity:
    return Irregularity(
        route_name=route.name,
        district_name=route.district_name or "Sin distrito",
        kind="school_cluster_duplicate_stop",
        title="Parada duplicada cerca de centro educativo",
        description=(
            f"La parada corregida {removed_stop.new_name} fue omitida porque quedo a "
            f"{distance_meters:.1f} m de {kept_stop.new_name} cerca de {school.name}. "
            f"Para un mismo centro se conserva solo la parada mas cercana por sentido."
        ),
        lon=removed_stop.new_lon,
        lat=removed_stop.new_lat,
        line_coords=list(route.line_coords),
        points=[
            (f"Omitida {removed_stop.new_name}", removed_stop.new_lon, removed_stop.new_lat),
            (f"Conservada {kept_stop.new_name}", kept_stop.new_lon, kept_stop.new_lat),
            (school.name, school.lon, school.lat),
        ],
        distance_meters=distance_meters,
    )


def assign_school_labels_to_corrected_stops(
    route: Route,
    stops: list[CorrectedStop],
    schools: list[School],
    school_radius_meters: float,
    external_school_lookup: SchoolLookup | None = None,
) -> list[str]:
    warnings: list[str] = []
    reset_school_labels(stops)

    kmz_assignments = assign_school_collection_to_stops(stops, schools, school_radius_meters, warnings)
    if external_school_lookup is None:
        return warnings

    warnings.extend(refine_generic_school_labels_from_external(stops, school_radius_meters, external_school_lookup))
    if not has_unlabeled_stops(stops):
        return warnings

    external_schools = discover_external_schools_for_route(stops, school_radius_meters, external_school_lookup)
    external_schools = filter_external_schools_not_already_assigned(external_schools, stops)
    if not external_schools:
        return warnings

    external_assignments = assign_school_collection_to_stops(
        stops,
        external_schools,
        school_radius_meters,
        warnings,
        only_unassigned=True,
    )
    if external_assignments > 0:
        if kmz_assignments > 0:
            warnings.append("Centros educativos adicionales asignados desde fuente externa para paradas sin nombre del KMZ.")
        else:
            warnings.append("Centros educativos asignados desde fuente externa porque no hubo centro del KMZ asignable.")
    return warnings


def has_unlabeled_stops(stops: list[CorrectedStop]) -> bool:
    return any(not stop.school_name for stop in stops)


def refine_generic_school_labels_from_external(
    stops: list[CorrectedStop],
    school_radius_meters: float,
    external_school_lookup: SchoolLookup,
) -> list[str]:
    refinements: dict[str, tuple[float, School]] = {}
    for stop in stops:
        if stop.tipo != "ida" or not stop.school_name or has_school_hint(stop.school_name):
            continue
        match = external_school_lookup(stop.new_lon, stop.new_lat, school_radius_meters)
        if not match or not match.school or not has_school_hint(match.school.name):
            continue
        if not school_names_look_related(stop.school_name, match.school.name):
            continue
        distance = match.distance_meters
        if distance is None:
            distance = haversine_meters(stop.new_lon, stop.new_lat, match.school.lon, match.school.lat)
        key = school_match_text(stop.school_name)
        existing = refinements.get(key)
        if existing is None or distance < existing[0]:
            refinements[key] = (distance, match.school)

    warnings: list[str] = []
    for old_key, (_distance, school) in refinements.items():
        matching_stops = [stop for stop in stops if school_match_text(stop.school_name) == old_key]
        if not matching_stops:
            continue
        old_name = matching_stops[0].school_name
        for stop in matching_stops:
            stop_distance = haversine_meters(stop.new_lon, stop.new_lat, school.lon, school.lat)
            set_stop_school_label(stop, school, stop_distance)
        warnings.append(f"Nombre de centro educativo refinado desde {school.source}: {old_name} -> {school.name}.")
    return warnings


def school_names_look_related(first: str, second: str) -> bool:
    first_tokens = meaningful_school_name_tokens(first)
    second_tokens = meaningful_school_name_tokens(second)
    if not first_tokens or not second_tokens:
        return False
    required_matches = min(2, len(first_tokens))
    return len(first_tokens & second_tokens) >= required_matches


def meaningful_school_name_tokens(name: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Z0-9]+", school_match_text(name))
        if len(token) > 1 and token not in SCHOOL_NAME_REFINEMENT_STOPWORDS
    }


def filter_external_schools_not_already_assigned(
    external_schools: list[School],
    stops: list[CorrectedStop],
) -> list[School]:
    assigned_names = {school_match_text(stop.school_name) for stop in stops if stop.school_name}
    return [school for school in external_schools if school_match_text(school.name) not in assigned_names]


def reset_school_labels(stops: list[CorrectedStop]) -> None:
    for stop in stops:
        stop.school_name = ""
        stop.school_distance_meters = None
        stop.school_source = ""
        stop.new_name = base_stop_name(stop.new_name)


def assign_school_collection_to_stops(
    stops: list[CorrectedStop],
    schools: list[School],
    school_radius_meters: float,
    warnings: list[str],
    *,
    only_unassigned: bool = False,
) -> int:
    proposals: list[tuple[float, int, School, str]] = []
    for school in schools:
        school_proposals = nearest_stop_proposals_for_school(stops, school, school_radius_meters, only_unassigned)
        if len(school_proposals) == 1:
            warnings.append(
                f"{school.name}: solo se encontro una parada dentro de {school_radius_meters:.0f} m."
            )
        proposals.extend(school_proposals)

    assigned_by_stop: dict[int, tuple[float, School]] = {}
    assignments = 0
    for distance, stop_index, school, _tipo in sorted(proposals, key=lambda item: item[0]):
        stop = stops[stop_index]
        existing = assigned_by_stop.get(stop_index)
        if existing is not None:
            existing_distance, existing_school = existing
            warnings.append(
                f"{school.name}: no se asigno a {base_stop_name(stop.new_name)} porque "
                f"{existing_school.name} esta mas cerca ({existing_distance:.1f} m vs {distance:.1f} m)."
            )
            continue
        set_stop_school_label(stop, school, distance)
        assigned_by_stop[stop_index] = (distance, school)
        assignments += 1
    return assignments


def nearest_stop_proposals_for_school(
    stops: list[CorrectedStop],
    school: School,
    school_radius_meters: float,
    only_unassigned: bool = False,
) -> list[tuple[float, int, School, str]]:
    proposals: list[tuple[float, int, School, str]] = []
    for tipo in ("ida", "regreso"):
        candidates: list[tuple[float, int]] = []
        for index, stop in enumerate(stops):
            if stop.tipo != tipo:
                continue
            if only_unassigned and stop.school_name:
                continue
            distance = haversine_meters(stop.new_lon, stop.new_lat, school.lon, school.lat)
            if distance <= school_radius_meters:
                candidates.append((distance, index))
        if candidates:
            distance, stop_index = min(candidates, key=lambda item: item[0])
            proposals.append((distance, stop_index, school, tipo))
    return proposals


def discover_external_schools_for_route(
    stops: list[CorrectedStop],
    school_radius_meters: float,
    external_school_lookup: SchoolLookup,
) -> list[School]:
    schools_by_key: dict[tuple[float, float, str, str], School] = {}
    for stop in stops:
        if stop.tipo != "ida" or stop.school_name:
            continue
        match = external_school_lookup(stop.new_lon, stop.new_lat, school_radius_meters)
        if not match or not match.school:
            continue
        school = match.school
        key = (round(school.lat, 6), round(school.lon, 6), school.name, school.source)
        schools_by_key.setdefault(key, school)
    return list(schools_by_key.values())


def set_stop_school_label(stop: CorrectedStop, school: School, distance_meters: float) -> None:
    stop.school_name = school.name
    stop.school_distance_meters = distance_meters
    stop.school_source = school.source
    stop.new_name = f"{base_stop_name(stop.new_name)} - {school.name}"
    if school.source in EXTERNAL_SCHOOL_SOURCES:
        warning = f"Centro educativo asignado desde {school.source}; no se encontro dentro del KMZ."
        if warning not in stop.warnings:
            stop.warnings.append(warning)


def base_stop_name(name: str) -> str:
    match = re.match(r"^\s*(P\s*\d+)\b", name or "", re.IGNORECASE)
    if match:
        return re.sub(r"\s+", "", match.group(1).upper())
    return (name or "").split(" - ", 1)[0].strip() or "P"


def removed_stop_irregularity(
    route_name: str,
    district_name: str,
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
        district_name=district_name or "Sin distrito",
        kind="removed_far_stop",
        title="Parada eliminada lejos de la ruta",
        description=(
            f"La parada original {removed_stop.name or '(sin nombre)'} fue consolidada con "
            f"{kept_stop.name or '(sin nombre)'}, pero estaba a {distance_meters:.1f} m de la linea de ruta. "
            f"Umbral de lejania: {FAR_REMOVED_STOP_ROUTE_METERS:.0f} m."
        ),
        lon=removed_stop.lon,
        lat=removed_stop.lat,
        line_coords=list(line_coords or []),
        points=[
            ("Eliminada lejos", removed_stop.lon, removed_stop.lat),
            ("Conservada", kept_stop.lon, kept_stop.lat),
        ],
        distance_meters=distance_meters,
    )


def find_created_stop_mismatch_irregularities(
    route: Route,
    kept_stops: list[Stop],
    corrected_stops: list[CorrectedStop],
) -> list[Irregularity]:
    expected_names = Counter(stop.name for stop in kept_stops)
    irregularities: list[Irregularity] = []
    for stop in [candidate for candidate in corrected_stops if candidate.tipo == "ida"]:
        if expected_names[stop.original_name] > 0:
            expected_names[stop.original_name] -= 1
            continue
        irregularities.append(
            Irregularity(
                route_name=route.name,
                district_name=route.district_name or "Sin distrito",
                kind="created_unmatched_stop",
                title="Parada creada sin coincidencia original",
                description=(
                    f"La parada corregida {stop.new_name} fue creada como parada de ida, "
                    f"pero no coincide con una parada original conservada."
                ),
                lon=stop.new_lon,
                lat=stop.new_lat,
                line_coords=list(route.line_coords),
                points=[(stop.new_name, stop.new_lon, stop.new_lat)],
            )
        )
    return irregularities


def find_schools_near_route_without_stops(
    route: Route,
    schools: list[School],
    corrected_stops: list[CorrectedStop],
    school_radius_meters: float,
) -> list[Irregularity]:
    if not schools or not route.line_coords:
        return []

    irregularities: list[Irregularity] = []
    seen: set[tuple[str, float, float]] = set()
    for school in schools:
        key = (school.name, round(school.lon, 7), round(school.lat, 7))
        if key in seen:
            continue
        seen.add(key)

        route_distance = distance_to_line_meters(school.lon, school.lat, route.line_coords)
        if route_distance is None or route_distance > school_radius_meters:
            continue

        closest_stop, closest_stop_distance = closest_corrected_stop_to_school(school, corrected_stops)
        if closest_stop_distance is not None and closest_stop_distance <= school_radius_meters:
            continue

        if closest_stop is None or closest_stop_distance is None:
            stop_text = "no hay paradas corregidas en la ruta"
            points = [(school.name, school.lon, school.lat)]
            measured_distance = route_distance
        else:
            stop_text = f"la parada mas cercana es {closest_stop.new_name} a {closest_stop_distance:.1f} m"
            points = [
                (school.name, school.lon, school.lat),
                (f"Parada mas cercana {base_stop_name(closest_stop.new_name)}", closest_stop.new_lon, closest_stop.new_lat),
            ]
            measured_distance = closest_stop_distance

        irregularities.append(
            Irregularity(
                route_name=route.name,
                district_name=route.district_name or "Sin distrito",
                kind="school_without_nearby_stop",
                title="Centro educativo sin parada cercana",
                description=(
                    f"{school.name} esta a {route_distance:.1f} m de la linea de ruta, pero {stop_text}. "
                    f"Umbral de parada cercana: {school_radius_meters:.0f} m."
                ),
                lon=school.lon,
                lat=school.lat,
                line_coords=list(route.line_coords),
                points=points,
                distance_meters=measured_distance,
            )
        )
    return irregularities


def closest_corrected_stop_to_school(
    school: School,
    stops: list[CorrectedStop],
) -> tuple[CorrectedStop | None, float | None]:
    closest_stop: CorrectedStop | None = None
    closest_distance = float("inf")
    for stop in stops:
        distance = haversine_meters(stop.new_lon, stop.new_lat, school.lon, school.lat)
        if distance < closest_distance:
            closest_stop = stop
            closest_distance = distance
    if closest_stop is None:
        return None, None
    return closest_stop, closest_distance


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
                district_name=route.district_name or "Sin distrito",
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
    anchors.extend((station, f"P{index}", stop.lon, stop.lat) for index, (station, stop) in enumerate(ranked, start=1))
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
                district_name=route.district_name or "Sin distrito",
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
    station_gap = None
    if previous["station"] is not None and current["station"] is not None:
        station_gap = abs(previous["station"] - current["station"])

    if station_gap is not None and station_gap <= NEAR_CONSECUTIVE_STOP_FLOW_METERS:
        return True

    if min(map_distance, placed_distance) <= NEAR_CONSECUTIVE_STOP_METERS:
        return True

    if not is_same_school(previous["school"], current["school"]):
        return False

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
    stop_warnings = list(dict.fromkeys(warnings))

    return CorrectedStop(
        route_name=route_name,
        original_name=original_name,
        new_name=base_name,
        tipo=tipo,
        original_lon=original_lon,
        original_lat=original_lat,
        new_lon=new_lon,
        new_lat=new_lat,
        offset_meters=offset_meters,
        is_pf=is_pf,
        ordering_method=ordering_method,
        warnings=stop_warnings,
    )


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
