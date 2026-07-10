from __future__ import annotations

import csv
import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .geometry import haversine_meters
from .models import CorrectedStop, RouteCorrection

REPORT_COLUMNS = [
    "ruta",
    "parada_original",
    "parada_nueva",
    "tipo",
    "lat_original",
    "lon_original",
    "lat_nueva",
    "lon_nueva",
    "offset_meters",
    "centro_educativo_detectado",
    "distancia_centro_metros",
    "fuente_centro_educativo",
    "es_pf",
    "metodo_ordenamiento",
    "advertencias",
]

ROUTE_FLOW_COLUMNS = [
    "distrito",
    "ruta",
    "indice_vertice",
    "lat",
    "lon",
    "alt",
    "segmento_metros",
    "distancia_acumulada_metros",
    "total_vertices",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTE_TEMPLATE_HEADERS = [
    "Trip Name*",
    "Trip Type*",
    "Consider Path",
    "Vehicle*",
    "Valid From*",
    "Valid To*",
    "Checkpoints*",
    "Add As Address",
    "CheckPoint Name*",
    "Pickup Time*",
    "Drop Time*",
    "GR Number",
    "Mo",
    "Tu",
    "We",
    "Th",
    "Fr",
    "Sa",
    "Su",
    "Location",
]
STOP_ROUTE_TEMPLATE_HEADERS = [
    "ID",
    "Ficha Autobus",
    "Nombre Del Conductor",
    "routename",
    "station name",
    "latitude",
    "longitude",
]
ROUTE_TEMPLATE_SHEET_NAME = "Sheet1"
ROUTE_TEMPLATE_DATA_START_ROW = 4
STOP_ROUTE_TEMPLATE_DATA_START_ROW = 2
ROUTE_EXCEL_TEMPLATE_BULK = "bulk_create_trip"
ROUTE_EXCEL_TEMPLATE_STOPS = "plantillas_rutas"
DEFAULT_ROUTE_EXCEL_TEMPLATE = ROUTE_EXCEL_TEMPLATE_BULK
DEFAULT_TRIP_TYPE = "Pickup"
DEFAULT_CONSIDER_PATH = "Yes"
DEFAULT_ADD_AS_ADDRESS = "No"
DEFAULT_PICKUP_TIME = "06:00"
DEFAULT_DROP_TIME = "14:00"
DEFAULT_SCHEDULE_VALUE = "Yes"
SCHEDULE_DAY_COLUMNS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
DEFAULT_ROUTE_TEMPLATE_PATH = PROJECT_ROOT / "kmz-plantilla" / "BulkCreateTrip.xlsx"
DEFAULT_STOP_ROUTE_TEMPLATE_PATH = PROJECT_ROOT / "kmz-plantilla" / "Plantillas de rutas.xlsx"
DEFAULT_DRIVERS_CSV_PATH = PROJECT_ROOT / "db" / "KMZ.csv"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MARKUP_COMPATIBILITY_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
X14AC_NS = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"
XR_NS = "http://schemas.microsoft.com/office/spreadsheetml/2014/revision"
XR2_NS = "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2"
XR3_NS = "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3"
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

ET.register_namespace("", SPREADSHEET_NS)
ET.register_namespace("r", OFFICE_REL_NS)
ET.register_namespace("mc", MARKUP_COMPATIBILITY_NS)
ET.register_namespace("x14ac", X14AC_NS)
ET.register_namespace("xr", XR_NS)
ET.register_namespace("xr2", XR2_NS)
ET.register_namespace("xr3", XR3_NS)


@dataclass(frozen=True)
class DriverAssignment:
    ficha_autobus: str = ""
    conductor: str = ""


@dataclass(frozen=True)
class BulkTripSettings:
    trip_type: str
    consider_path: str
    valid_from: str
    valid_to: str
    pickup_time: str
    drop_time: str
    add_as_address: str
    schedule_days: tuple[str, ...]
    schedule_value: str
    location: str = ""


@dataclass(frozen=True)
class RouteExcelLayout:
    headers: list[str]
    data_start_row: int
    header_row: int
    last_column: str
    fallback_note: str = ""


BULK_ROUTE_EXCEL_LAYOUT = RouteExcelLayout(
    headers=ROUTE_TEMPLATE_HEADERS,
    data_start_row=ROUTE_TEMPLATE_DATA_START_ROW,
    header_row=3,
    last_column="T",
    fallback_note="BulkCreateTrip template fallback.",
)
STOP_ROUTE_EXCEL_LAYOUT = RouteExcelLayout(
    headers=STOP_ROUTE_TEMPLATE_HEADERS,
    data_start_row=STOP_ROUTE_TEMPLATE_DATA_START_ROW,
    header_row=1,
    last_column="G",
)


def default_bulk_trip_settings() -> BulkTripSettings:
    today = date.today()
    return BulkTripSettings(
        trip_type=DEFAULT_TRIP_TYPE,
        consider_path=DEFAULT_CONSIDER_PATH,
        valid_from=today.strftime("%d-%m-%Y"),
        valid_to=f"31-12-{today.year}",
        pickup_time=DEFAULT_PICKUP_TIME,
        drop_time=DEFAULT_DROP_TIME,
        add_as_address=DEFAULT_ADD_AS_ADDRESS,
        schedule_days=SCHEDULE_DAY_COLUMNS,
        schedule_value=DEFAULT_SCHEDULE_VALUE,
    )


def build_bulk_trip_settings(
    *,
    trip_type: str | None = None,
    consider_path: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    pickup_time: str | None = None,
    drop_time: str | None = None,
    add_as_address: str | None = None,
    schedule_days: str | list[str] | tuple[str, ...] | None = None,
    schedule_value: str | None = None,
    location: str | None = None,
) -> BulkTripSettings:
    defaults = default_bulk_trip_settings()
    settings = BulkTripSettings(
        trip_type=clean_driver_value(trip_type) or defaults.trip_type,
        consider_path=clean_driver_value(consider_path) or defaults.consider_path,
        valid_from=clean_driver_value(valid_from) or defaults.valid_from,
        valid_to=clean_driver_value(valid_to) or defaults.valid_to,
        pickup_time=clean_driver_value(pickup_time) or defaults.pickup_time,
        drop_time=clean_driver_value(drop_time) or defaults.drop_time,
        add_as_address=clean_driver_value(add_as_address) or defaults.add_as_address,
        schedule_days=parse_schedule_days(schedule_days) or defaults.schedule_days,
        schedule_value=clean_driver_value(schedule_value) or defaults.schedule_value,
        location=clean_driver_value(location or ""),
    )
    validate_bulk_trip_settings(settings)
    return settings


def validate_bulk_trip_settings(settings: BulkTripSettings) -> None:
    for label, value in [("Valid From", settings.valid_from), ("Valid To", settings.valid_to)]:
        if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", value):
            raise ValueError(f"{label} debe estar en formato dd-MM-yyyy")
        try:
            datetime.strptime(value, "%d-%m-%Y")
        except ValueError as exc:
            raise ValueError(f"{label} no es una fecha valida") from exc
    for label, value in [("Pickup Time", settings.pickup_time), ("Drop Time", settings.drop_time)]:
        if not re.fullmatch(r"\d{2}:\d{2}", value):
            raise ValueError(f"{label} debe estar en formato HH:mm")
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError(f"{label} no es una hora valida") from exc


def parse_schedule_days(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    raw_days = value if isinstance(value, (list, tuple)) else re.split(r"[,;\s]+", value)
    allowed = {day.lower(): day for day in SCHEDULE_DAY_COLUMNS}
    days: list[str] = []
    for raw_day in raw_days:
        day = clean_driver_value(raw_day).lower()
        if day in allowed and allowed[day] not in days:
            days.append(allowed[day])
    return tuple(days)


def route_excel_template_options() -> list[dict[str, str]]:
    return [
        {"value": ROUTE_EXCEL_TEMPLATE_BULK, "label": "BulkCreateTrip"},
        {"value": ROUTE_EXCEL_TEMPLATE_STOPS, "label": "Plantilla de rutas"},
    ]


def normalize_route_excel_template(value: str | None, template_path: str | Path | None = None) -> str:
    cleaned = clean_driver_value(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "",
        ROUTE_EXCEL_TEMPLATE_BULK: ROUTE_EXCEL_TEMPLATE_BULK,
        "bulk": ROUTE_EXCEL_TEMPLATE_BULK,
        "bulkcreatetrip": ROUTE_EXCEL_TEMPLATE_BULK,
        "bulk_create_trip": ROUTE_EXCEL_TEMPLATE_BULK,
        ROUTE_EXCEL_TEMPLATE_STOPS: ROUTE_EXCEL_TEMPLATE_STOPS,
        "plantilla": ROUTE_EXCEL_TEMPLATE_STOPS,
        "plantillas": ROUTE_EXCEL_TEMPLATE_STOPS,
        "plantilla_de_rutas": ROUTE_EXCEL_TEMPLATE_STOPS,
        "plantillas_de_rutas": ROUTE_EXCEL_TEMPLATE_STOPS,
        "rutas": ROUTE_EXCEL_TEMPLATE_STOPS,
    }
    if cleaned in aliases and aliases[cleaned]:
        return aliases[cleaned]
    if cleaned and cleaned not in aliases:
        raise ValueError("Plantilla Excel no soportada.")

    inferred = infer_route_excel_template_from_path(template_path)
    return inferred or DEFAULT_ROUTE_EXCEL_TEMPLATE


def infer_route_excel_template_from_path(template_path: str | Path | None) -> str | None:
    if not template_path:
        return None
    filename = Path(template_path).name.lower()
    if "bulkcreatetrip" in filename or "bulk" in filename:
        return ROUTE_EXCEL_TEMPLATE_BULK
    if "plantilla" in filename and "ruta" in filename:
        return ROUTE_EXCEL_TEMPLATE_STOPS
    return None


def route_excel_layout(route_excel_template: str) -> RouteExcelLayout:
    if route_excel_template == ROUTE_EXCEL_TEMPLATE_STOPS:
        return STOP_ROUTE_EXCEL_LAYOUT
    return BULK_ROUTE_EXCEL_LAYOUT


def default_route_template_path(route_excel_template: str | None = None) -> Path:
    template = normalize_route_excel_template(route_excel_template)
    if template == ROUTE_EXCEL_TEMPLATE_STOPS:
        return DEFAULT_STOP_ROUTE_TEMPLATE_PATH
    return DEFAULT_ROUTE_TEMPLATE_PATH


def write_report(path: str | Path, stops: list[CorrectedStop]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for stop in stops:
            writer.writerow(
                {
                    "ruta": stop.route_name,
                    "parada_original": stop.original_name,
                    "parada_nueva": stop.new_name,
                    "tipo": stop.tipo,
                    "lat_original": f"{stop.original_lat:.8f}",
                    "lon_original": f"{stop.original_lon:.8f}",
                    "lat_nueva": f"{stop.new_lat:.8f}",
                    "lon_nueva": f"{stop.new_lon:.8f}",
                    "offset_meters": f"{stop.offset_meters:.2f}",
                    "centro_educativo_detectado": stop.school_name,
                    "distancia_centro_metros": "" if stop.school_distance_meters is None else f"{stop.school_distance_meters:.2f}",
                    "fuente_centro_educativo": stop.school_source,
                    "es_pf": "si" if stop.is_pf else "no",
                    "metodo_ordenamiento": stop.ordering_method,
                    "advertencias": " | ".join(stop.warnings),
                }
            )


def write_route_flow_report(path: str | Path, corrections: list[RouteCorrection]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROUTE_FLOW_COLUMNS)
        writer.writeheader()
        for correction in corrections:
            coords = correction.route.line_coords
            cumulative = 0.0
            previous: tuple[float, float] | None = None
            total_vertices = len(coords)
            for index, (lon, lat, alt) in enumerate(coords, start=1):
                segment = 0.0
                if previous is not None:
                    segment = haversine_meters(previous[0], previous[1], lon, lat)
                    cumulative += segment
                writer.writerow(
                    {
                        "distrito": correction.route.district_name or "Sin distrito",
                        "ruta": correction.route.name,
                        "indice_vertice": index,
                        "lat": f"{lat:.8f}",
                        "lon": f"{lon:.8f}",
                        "alt": "" if alt is None else f"{alt:.2f}",
                        "segmento_metros": f"{segment:.2f}",
                        "distancia_acumulada_metros": f"{cumulative:.2f}",
                        "total_vertices": total_vertices,
                    }
                )
                previous = (lon, lat)


def write_route_excels(
    output_dir: str | Path,
    corrections: list[RouteCorrection],
    *,
    drivers_csv_path: str | Path | None = None,
    route_template_path: str | Path | None = None,
    route_excel_template: str | None = None,
    bulk_trip_settings: BulkTripSettings | None = None,
    warnings: list[str] | None = None,
) -> list[Path]:
    excel_dir = Path(output_dir)
    if excel_dir.exists():
        shutil.rmtree(excel_dir)
    excel_dir.mkdir(parents=True, exist_ok=True)

    driver_assignments = load_driver_assignments(drivers_csv_path, warnings)
    template_path = usable_route_template_path(route_template_path, warnings, route_excel_template=route_excel_template)
    route_excel_template = normalize_route_excel_template(route_excel_template, template_path)
    layout = route_excel_layout(route_excel_template)
    bulk_trip_settings = bulk_trip_settings or default_bulk_trip_settings()

    paths: list[Path] = []
    route_numbers_by_district: dict[str, int] = {}
    for correction in corrections:
        if not correction.stops:
            continue
        district_name = route_templates_folder_name(correction.route.district_name)
        route_number = route_numbers_by_district.get(district_name, 0) + 1
        route_numbers_by_district[district_name] = route_number
        filename = f"{route_number:03d}_{safe_excel_filename(correction.route.name)}.xlsx"
        path = excel_dir / district_name / filename
        assignments = find_driver_assignments(driver_assignments, correction, warnings)
        if route_excel_template == ROUTE_EXCEL_TEMPLATE_STOPS:
            rows = build_stop_route_template_rows(correction, assignments, fallback_route_number=route_number)
        else:
            rows = build_route_template_rows(
                correction,
                assignments,
                bulk_trip_settings,
                fallback_route_number=route_number,
                warnings=warnings,
            )
        write_route_excel(path, rows, template_path=template_path, layout=layout, warnings=warnings)
        paths.append(path)
    return paths


def route_excel_label(route_name: str) -> str:
    match = re.search(r"ruta\s*[_#:\-]*\s*(\d+)", route_name or "", re.IGNORECASE)
    if match:
        return f"RUTA {int(match.group(1))}"
    cleaned = re.sub(r"\s+", " ", route_name or "Ruta").strip()
    return (cleaned or "Ruta").upper()


def resolve_route_template_path(route_template_path: str | Path | None, route_excel_template: str | None = None) -> Path | None:
    configured_path = route_template_path
    if not configured_path and route_excel_template is None:
        configured_path = os.getenv("KMZ_ROUTE_TEMPLATE_PATH")
    if not configured_path:
        configured_path = default_route_template_path(route_excel_template)
    if not configured_path:
        return None
    return Path(configured_path)


def usable_route_template_path(
    route_template_path: str | Path | None,
    warnings: list[str] | None = None,
    route_excel_template: str | None = None,
) -> Path | None:
    template_path = resolve_route_template_path(route_template_path, route_excel_template)
    if not template_path:
        return None
    try:
        if template_path.is_file():
            return template_path
    except OSError as exc:
        append_warning(warnings, f"No se pudo validar la plantilla Excel {template_path}: {exc}. Se genero una plantilla basica.")
        return None
    append_warning(warnings, f"No se encontro la plantilla Excel {template_path}. Se genero una plantilla basica.")
    return None


def default_drivers_csv_path() -> Path:
    configured_path = os.getenv("KMZ_DRIVERS_CSV_PATH")
    if configured_path:
        return Path(configured_path)
    return DEFAULT_DRIVERS_CSV_PATH


def load_driver_assignments(path: str | Path | None = None, warnings: list[str] | None = None) -> dict[tuple[str, int], list[DriverAssignment]]:
    csv_path = Path(path) if path else default_drivers_csv_path()
    if not csv_path.exists():
        append_warning(warnings, f"No se encontro el CSV de choferes: {csv_path}. Las plantillas saldran sin ficha/conductor.")
        return {}

    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with csv_path.open("r", encoding=encoding, newline="") as handle:
                return parse_driver_assignments(handle, warnings)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            append_warning(warnings, f"No se pudo leer el CSV de choferes {csv_path}: {exc}")
            return {}

    append_warning(warnings, f"No se pudo leer el CSV de choferes {csv_path}: codificacion no soportada.")
    return {}


def parse_driver_assignments(handle, warnings: list[str] | None = None) -> dict[tuple[str, int], list[DriverAssignment]]:
    sample = handle.read(4096)
    handle.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel

    assignments: dict[tuple[str, int], list[DriverAssignment]] = {}
    reader = csv.DictReader(handle, dialect=dialect)
    for row in reader:
        district_code = district_code_from_name(row.get("DISTRITO", ""))
        route_number = route_number_from_name(row.get("No. RUTA", ""))
        if not district_code or route_number is None:
            continue

        key = (district_code, route_number)
        assignment = DriverAssignment(
            ficha_autobus=clean_driver_value(row.get("FICHA", "")),
            conductor=clean_driver_value(row.get("NOMBRES Y APELLIDOS CHOFER", "")),
        )
        if not assignment.ficha_autobus and not assignment.conductor:
            continue
        route_assignments = assignments.setdefault(key, [])
        if assignment in route_assignments:
            continue
        route_assignments.append(assignment)
    return assignments


def find_driver_assignments(
    assignments: dict[tuple[str, int], list[DriverAssignment]],
    correction: RouteCorrection,
    warnings: list[str] | None = None,
) -> list[DriverAssignment]:
    district_code = district_code_from_name(correction.route.district_name)
    route_number = route_number_from_name(correction.route.name)
    if district_code and route_number is not None:
        route_assignments = assignments.get((district_code, route_number))
        if route_assignments:
            return route_assignments

    if district_code:
        district_assignments = [
            route_assignments
            for (candidate_district, _), route_assignments in assignments.items()
            if candidate_district == district_code
        ]
        if len(district_assignments) == 1:
            append_warning(
                warnings,
                f"{correction.route.name}: no hubo coincidencia exacta de chofer; se uso el unico registro del distrito {format_district_code(district_code)}.",
            )
            return district_assignments[0]

    append_warning(warnings, f"{correction.route.name}: no se encontro ficha/conductor para el distrito/ruta en el CSV de choferes.")
    return []


def build_route_template_rows(
    correction: RouteCorrection,
    assignments: list[DriverAssignment],
    bulk_trip_settings: BulkTripSettings,
    *,
    fallback_route_number: int,
    warnings: list[str] | None = None,
) -> list[list[str | float]]:
    route_number = route_number_from_name(correction.route.name) or fallback_route_number
    trip_name = route_template_route_name(correction.route.name) or f"Ruta{route_number}"
    checkpoints = bulk_checkpoints(correction.stops)
    checkpoint_names = bulk_checkpoint_names(correction.stops)
    gr_number = bulk_gr_number(correction, route_number)
    location = bulk_trip_settings.location or correction.route.district_name or format_district_code(
        district_code_from_name(correction.route.district_name)
    ) or "SIN UBICACION"
    rows: list[list[str | float]] = []
    trip_assignments = assignments or [DriverAssignment()]
    for assignment in trip_assignments:
        vehicle = assignment.ficha_autobus or "NO ASIGNADO"
        rows.append(
            [
                trip_name,
                bulk_trip_settings.trip_type,
                bulk_trip_settings.consider_path,
                vehicle,
                bulk_trip_settings.valid_from,
                bulk_trip_settings.valid_to,
                checkpoints,
                bulk_trip_settings.add_as_address,
                checkpoint_names,
                bulk_trip_settings.pickup_time,
                bulk_trip_settings.drop_time,
                gr_number,
                *schedule_day_values(bulk_trip_settings),
                location,
            ]
        )
    return rows


def build_stop_route_template_rows(
    correction: RouteCorrection,
    assignments: list[DriverAssignment],
    *,
    fallback_route_number: int,
) -> list[list[str | float]]:
    district_code = district_code_from_name(correction.route.district_name)
    route_number = route_number_from_name(correction.route.name) or fallback_route_number
    route_name = route_excel_label(correction.route.name)
    ficha_autobus = joined_assignment_values(assignments, "ficha_autobus") or "NO ASIGNADO"
    conductor = joined_assignment_values(assignments, "conductor") or "NO ASIGNADO"

    rows: list[list[str | float]] = []
    for index, stop in enumerate(correction.stops, start=1):
        stop_number = stop_number_from_name(stop.new_name) or index
        rows.append(
            [
                f"{district_code or '0000'}R{route_number}P{stop_number}",
                ficha_autobus if index == 1 else "",
                conductor if index == 1 else "",
                route_name,
                stop.new_name,
                f"{stop.new_lat:.8f}",
                f"{stop.new_lon:.8f}",
            ]
        )
    return rows


def joined_assignment_values(assignments: list[DriverAssignment], field_name: str) -> str:
    values: list[str] = []
    for assignment in assignments:
        value = clean_driver_value(getattr(assignment, field_name, ""))
        if value and value not in values:
            values.append(value)
    return " / ".join(values)


def route_template_route_name(route_name: str | None) -> str:
    cleaned = re.sub(r"#\s*", "", route_name or "")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", cleaned)
    return cleaned


def bulk_gr_number(correction: RouteCorrection, route_number: int) -> str:
    district_code = district_code_from_name(correction.route.district_name)
    return f"{district_code or '0000'}R{route_number}"


def schedule_day_values(settings: BulkTripSettings) -> list[str]:
    active_days = set(settings.schedule_days)
    return [settings.schedule_value if day in active_days else "No" for day in SCHEDULE_DAY_COLUMNS]


def bulk_checkpoints(stops: list[CorrectedStop]) -> str:
    return ",".join(f"({stop.new_lat:.8f},{stop.new_lon:.8f})" for stop in stops)


def bulk_checkpoint_names(stops: list[CorrectedStop]) -> str:
    return ",".join(clean_bulk_checkpoint_name(stop.new_name) for stop in stops)


def clean_bulk_checkpoint_name(name: str) -> str:
    cleaned = re.sub(r"[,&]+", " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def district_code_from_name(name: str | None) -> str:
    text = name or ""
    match = re.search(r"\b(\d{1,2})\s*[-_ ]\s*(\d{1,2})\b", text)
    if match:
        return f"{int(match.group(1)):02d}{int(match.group(2)):02d}"
    digits = re.sub(r"\D+", "", text)
    if len(digits) == 3:
        return f"0{digits}"
    return digits[:4] if len(digits) >= 4 else ""


def format_district_code(district_code: str) -> str:
    return f"{district_code[:2]}-{district_code[2:4]}" if len(district_code) >= 4 else district_code


def route_templates_folder_name(district_name: str | None) -> str:
    district_code = district_code_from_name(district_name)
    if district_code:
        return f"Rutas {format_district_code(district_code)}"
    return safe_excel_filename(district_name or "Sin distrito")


def route_number_from_name(name: str | int | None) -> int | None:
    match = re.search(r"\d+", str(name or ""))
    return int(match.group(0)) if match else None


def stop_number_from_name(name: str | None) -> int | None:
    match = re.search(r"\bP\s*(\d+)\b", name or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def clean_driver_value(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def append_warning(warnings: list[str] | None, message: str) -> None:
    if warnings is not None:
        warnings.append(message)


def safe_excel_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name or "Ruta")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "Ruta")[:80]


def write_route_excel(
    path: str | Path,
    rows: list[list[str | float]],
    *,
    template_path: Path | None = None,
    layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT,
    warnings: list[str] | None = None,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if template_path:
        try:
            write_route_excel_from_template(output_path, rows, template_path, layout)
            return
        except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
            append_warning(warnings, f"No se pudo usar la plantilla Excel {template_path}: {exc}. Se genero una plantilla basica.")

    write_generated_route_excel(output_path, rows, layout)


def write_route_excel_from_template(
    output_path: Path,
    rows: list[list[str | float]],
    template_path: Path,
    layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT,
) -> None:
    with zipfile.ZipFile(template_path) as source, zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = xml_bytes(build_route_sheet_from_template(data, rows, layout))
            target.writestr(item, data)


def write_generated_route_excel(
    output_path: Path,
    rows: list[list[str | float]],
    layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT,
) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", xml_bytes(build_content_types()))
        archive.writestr("_rels/.rels", xml_bytes(build_root_relationships()))
        archive.writestr("docProps/app.xml", docprops_app_xml())
        archive.writestr("docProps/core.xml", docprops_core_xml())
        archive.writestr("xl/workbook.xml", xml_bytes(build_workbook()))
        archive.writestr("xl/_rels/workbook.xml.rels", xml_bytes(build_workbook_relationships()))
        archive.writestr("xl/styles.xml", xml_bytes(build_styles()))
        archive.writestr("xl/worksheets/sheet1.xml", xml_bytes(build_route_sheet(rows, layout)))


def build_route_sheet_from_template(
    sheet_xml: bytes,
    rows: list[list[str | float]],
    layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT,
) -> ET.Element:
    worksheet = ET.fromstring(sheet_xml)
    normalize_worksheet_compatibility(worksheet)
    styles = extract_template_styles(worksheet, layout)
    last_row = max(layout.data_start_row - 1, len(rows) + layout.data_start_row - 1)
    dimension = worksheet.find(xlsx_tag("dimension"))
    if dimension is not None:
        dimension.set("ref", f"A1:{layout.last_column}{last_row}")

    old_sheet_data = worksheet.find(xlsx_tag("sheetData"))
    insert_index = list(worksheet).index(old_sheet_data) if old_sheet_data is not None else len(worksheet)
    if old_sheet_data is not None:
        worksheet.remove(old_sheet_data)
    worksheet.insert(insert_index, build_template_sheet_data(old_sheet_data, rows, styles, layout))
    return worksheet


def normalize_worksheet_compatibility(worksheet: ET.Element) -> None:
    ignorable_attr = f"{{{MARKUP_COMPATIBILITY_NS}}}Ignorable"
    if ignorable_attr not in worksheet.attrib:
        return

    used_prefixes: list[str] = []
    if has_namespaced_content(worksheet, X14AC_NS):
        used_prefixes.append("x14ac")
    if has_namespaced_content(worksheet, XR_NS):
        used_prefixes.append("xr")
    if has_namespaced_content(worksheet, XR2_NS):
        used_prefixes.append("xr2")
    if has_namespaced_content(worksheet, XR3_NS):
        used_prefixes.append("xr3")

    if used_prefixes:
        worksheet.set(ignorable_attr, " ".join(used_prefixes))
    else:
        worksheet.attrib.pop(ignorable_attr, None)


def has_namespaced_content(element: ET.Element, namespace: str) -> bool:
    namespace_prefix = f"{{{namespace}}}"
    for current in element.iter():
        if current.tag.startswith(namespace_prefix):
            return True
        if any(attribute.startswith(namespace_prefix) for attribute in current.attrib):
            return True
    return False


def extract_template_styles(worksheet: ET.Element, layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT) -> dict[int, dict[int, str]]:
    styles: dict[int, dict[int, str]] = {layout.data_start_row: {}}
    for row in worksheet.findall(f".//{xlsx_tag('sheetData')}/{xlsx_tag('row')}"):
        row_number = int(row.attrib.get("r", "0") or 0)
        if row_number not in styles:
            continue
        for cell in row.findall(xlsx_tag("c")):
            cell_ref = cell.attrib.get("r", "")
            style_id = cell.attrib.get("s")
            column_index = column_index_from_ref(cell_ref)
            if style_id and column_index:
                styles[row_number][column_index] = style_id
    return styles


def build_route_sheet(rows: list[list[str | float]], layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT) -> ET.Element:
    worksheet = ET.Element(xlsx_tag("worksheet"))
    dimension = ET.SubElement(worksheet, xlsx_tag("dimension"))
    dimension.set("ref", f"A1:{layout.last_column}{len(rows) + layout.data_start_row - 1}")

    cols = ET.SubElement(worksheet, xlsx_tag("cols"))
    for min_col, max_col, width in route_excel_column_widths(layout):
        ET.SubElement(
            cols,
            xlsx_tag("col"),
            {"min": min_col, "max": max_col, "width": width, "bestFit": "1", "customWidth": "1"},
        )

    worksheet.append(build_sheet_data(rows, {}, layout))
    return worksheet


def route_excel_column_widths(layout: RouteExcelLayout) -> list[tuple[str, str, str]]:
    if layout == STOP_ROUTE_EXCEL_LAYOUT:
        return [
            ("1", "1", "16"),
            ("2", "2", "18"),
            ("3", "3", "28"),
            ("4", "4", "16"),
            ("5", "5", "48"),
            ("6", "7", "16"),
        ]
    return [
        ("1", "1", "16"),
        ("2", "4", "14"),
        ("5", "6", "12"),
        ("7", "9", "48"),
        ("10", "11", "14"),
        ("12", "20", "10"),
    ]


def build_template_sheet_data(
    old_sheet_data: ET.Element | None,
    rows: list[list[str | float]],
    styles: dict[int, dict[int, str]],
    layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT,
) -> ET.Element:
    sheet_data = ET.Element(xlsx_tag("sheetData"))
    if old_sheet_data is not None:
        for old_row in old_sheet_data.findall(xlsx_tag("row")):
            row_number = int(old_row.attrib.get("r", "0") or 0)
            if row_number < layout.data_start_row:
                sheet_data.append(deepcopy(old_row))
    for row_index, row_values in enumerate(rows, start=layout.data_start_row):
        add_xlsx_row(sheet_data, row_index, row_values, styles.get(layout.data_start_row))
    return sheet_data


def build_sheet_data(
    rows: list[list[str | float]],
    styles: dict[int, dict[int, str]],
    layout: RouteExcelLayout = BULK_ROUTE_EXCEL_LAYOUT,
) -> ET.Element:
    sheet_data = ET.Element(xlsx_tag("sheetData"))
    if layout.fallback_note:
        add_xlsx_row(sheet_data, 1, ["Note", layout.fallback_note])
    add_xlsx_row(sheet_data, layout.header_row, layout.headers)
    for row_index, row_values in enumerate(rows, start=layout.data_start_row):
        add_xlsx_row(sheet_data, row_index, row_values, styles.get(layout.data_start_row))
    return sheet_data


def add_xlsx_row(parent: ET.Element, row_index: int, values: list[str | float], styles: dict[int, str] | None = None) -> None:
    row = ET.SubElement(parent, xlsx_tag("row"), {"r": str(row_index)})
    for column_index, value in enumerate(values, start=1):
        cell_ref = f"{column_letter(column_index)}{row_index}"
        attrs = {"r": cell_ref}
        if styles and column_index in styles:
            attrs["s"] = styles[column_index]
        if isinstance(value, float):
            cell = ET.SubElement(row, xlsx_tag("c"), attrs)
            ET.SubElement(cell, xlsx_tag("v")).text = f"{value:.8f}"
            continue
        attrs["t"] = "inlineStr"
        cell = ET.SubElement(row, xlsx_tag("c"), attrs)
        inline_string = ET.SubElement(cell, xlsx_tag("is"))
        ET.SubElement(inline_string, xlsx_tag("t")).text = clean_xlsx_text(value)


def clean_xlsx_text(value: str | float) -> str:
    text = str(value)
    return "".join(char for char in text if is_valid_xml_char(char))


def is_valid_xml_char(char: str) -> bool:
    codepoint = ord(char)
    return (
        codepoint == 0x09
        or codepoint == 0x0A
        or codepoint == 0x0D
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def column_index_from_ref(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - 64
    return index


def column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def build_workbook() -> ET.Element:
    workbook = ET.Element(xlsx_tag("workbook"))
    sheets = ET.SubElement(workbook, xlsx_tag("sheets"))
    ET.SubElement(
        sheets,
        xlsx_tag("sheet"),
        {"name": ROUTE_TEMPLATE_SHEET_NAME, "sheetId": "1", f"{{{OFFICE_REL_NS}}}id": "rId1"},
    )
    return workbook


def build_workbook_relationships() -> ET.Element:
    relationships = ET.Element(package_tag("Relationships"))
    ET.SubElement(
        relationships,
        package_tag("Relationship"),
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            "Target": "worksheets/sheet1.xml",
        },
    )
    ET.SubElement(
        relationships,
        package_tag("Relationship"),
        {
            "Id": "rId2",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
            "Target": "styles.xml",
        },
    )
    return relationships


def build_root_relationships() -> ET.Element:
    relationships = ET.Element(package_tag("Relationships"))
    for rel_id, rel_type, target in [
        ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "xl/workbook.xml"),
        ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
        ("rId3", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "docProps/app.xml"),
    ]:
        ET.SubElement(relationships, package_tag("Relationship"), {"Id": rel_id, "Type": rel_type, "Target": target})
    return relationships


def build_content_types() -> ET.Element:
    types = ET.Element(content_type_tag("Types"))
    ET.SubElement(types, content_type_tag("Default"), {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ET.SubElement(types, content_type_tag("Default"), {"Extension": "xml", "ContentType": "application/xml"})
    overrides = [
        ("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
        ("/xl/worksheets/sheet1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
        ("/xl/styles.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
    ]
    for part_name, content_type in overrides:
        ET.SubElement(types, content_type_tag("Override"), {"PartName": part_name, "ContentType": content_type})
    return types


def build_styles() -> ET.Element:
    style_sheet = ET.Element(xlsx_tag("styleSheet"))
    ET.SubElement(style_sheet, xlsx_tag("fonts"), {"count": "1"}).append(ET.Element(xlsx_tag("font")))
    fills = ET.SubElement(style_sheet, xlsx_tag("fills"), {"count": "1"})
    ET.SubElement(fills, xlsx_tag("fill"))
    borders = ET.SubElement(style_sheet, xlsx_tag("borders"), {"count": "1"})
    ET.SubElement(borders, xlsx_tag("border"))
    cell_style_xfs = ET.SubElement(style_sheet, xlsx_tag("cellStyleXfs"), {"count": "1"})
    ET.SubElement(cell_style_xfs, xlsx_tag("xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0"})
    cell_xfs = ET.SubElement(style_sheet, xlsx_tag("cellXfs"), {"count": "1"})
    ET.SubElement(cell_xfs, xlsx_tag("xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0", "xfId": "0"})
    return style_sheet


def docprops_app_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        b'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        b"<Application>KMZ Route Corrector</Application></Properties>"
    )


def docprops_core_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        b'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        b'xmlns:dcterms="http://purl.org/dc/terms/" '
        b'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        b"<dc:creator>KMZ Route Corrector</dc:creator></cp:coreProperties>"
    )


def xlsx_tag(name: str) -> str:
    return f"{{{SPREADSHEET_NS}}}{name}"


def package_tag(name: str) -> str:
    return f"{{{PACKAGE_REL_NS}}}{name}"


def content_type_tag(name: str) -> str:
    return f"{{{CONTENT_TYPES_NS}}}{name}"


def xml_bytes(root: ET.Element) -> bytes:
    return XML_DECLARATION + ET.tostring(root, encoding="utf-8")


def write_warnings(path: str | Path, warnings: list[str]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        if not warnings:
            handle.write("Sin advertencias.\n")
            return
        for warning in warnings:
            handle.write(f"{warning}\n")
