from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .geometry import haversine_meters
from .report import DEFAULT_ROUTE_TEMPLATE_PATH

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
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

REQUIRED_SOURCE_HEADERS = ("station name", "latitude", "longitude")
OUTPUT_HEADERS = (
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
)
DATA_START_ROW = 4
CHECKPOINT_CONFLICT_METERS = 35.0


@dataclass(frozen=True)
class RouteStop:
    station_name: str
    latitude: str
    longitude: str


def create_uffizio_bulk_trip(
    source_path: str | Path,
    output_path: str | Path,
    *,
    template_path: str | Path = DEFAULT_ROUTE_TEMPLATE_PATH,
    today: date | None = None,
    trip_type: str | None = None,
    vehicles: list[str] | tuple[str, ...] | None = None,
) -> Path:
    template = Path(template_path)
    stops = resolve_checkpoint_conflicts(read_route_stops(source_path))
    if not stops:
        raise ValueError("El archivo no contiene paradas validas para convertir.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    trip_type_value = normalize_uffizio_trip_type(trip_type, template)
    vehicle_values = normalize_uffizio_vehicles(vehicles, template)
    rows = build_uffizio_rows(stops, today=today, trip_type=trip_type_value, vehicles=vehicle_values)
    write_bulk_trip_from_template(output, rows, template)
    return output


def bulk_trip_type_options(template_path: str | Path = DEFAULT_ROUTE_TEMPLATE_PATH) -> list[str]:
    try:
        with zipfile.ZipFile(Path(template_path)) as archive:
            shared_strings = read_shared_strings(archive)
            worksheet = ET.fromstring(archive.read(sheet_path_by_name(archive, "HList")))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return ["Pickup", "Drop"]

    trip_types: list[str] = []
    for row in read_rows(worksheet, shared_strings):
        for value in row.values():
            cleaned = value.strip()
            if cleaned and normalize_header(cleaned) != "trip_type" and cleaned not in trip_types:
                trip_types.append(cleaned)
    return trip_types or ["Pickup", "Drop"]

def bulk_trip_vehicle_options(template_path: str | Path = DEFAULT_ROUTE_TEMPLATE_PATH) -> list[str]:
    try:
        with zipfile.ZipFile(Path(template_path)) as archive:
            shared_strings = read_shared_strings(archive)
            worksheet = ET.fromstring(archive.read(sheet_path_by_name(archive, "HList1")))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return ["vehicle 2"]

    vehicles: list[str] = []
    for row in read_rows(worksheet, shared_strings):
        for value in row.values():
            cleaned = value.strip()
            if cleaned and normalize_header(cleaned) != "vehicle" and cleaned not in vehicles:
                vehicles.append(cleaned)
    return vehicles or ["vehicle 2"]


def normalize_uffizio_trip_type(value: str | None, template_path: Path) -> str:
    options = bulk_trip_type_options(template_path)
    options_by_key = {option.casefold(): option for option in options}
    selected = (value or "Pickup").strip() or "Pickup"
    normalized = options_by_key.get(selected.casefold())
    if normalized is None:
        raise ValueError(f"Trip Type no disponible en la plantilla BulkCreateTrip: {selected}")
    return normalized

def normalize_uffizio_vehicles(vehicles: list[str] | tuple[str, ...] | None, template_path: Path) -> list[str]:
    options = bulk_trip_vehicle_options(template_path)
    options_by_key = {option.casefold(): option for option in options}
    selected = [value.strip() for value in vehicles or [] if value and value.strip()]
    if not selected:
        selected = ["vehicle 2" if "vehicle 2" in options else options[0]]

    normalized: list[str] = []
    invalid: list[str] = []
    for value in selected:
        vehicle = options_by_key.get(value.casefold())
        if vehicle is None:
            invalid.append(value)
            continue
        if vehicle not in normalized:
            normalized.append(vehicle)

    if invalid:
        raise ValueError(f"Vehiculo no disponible en la plantilla BulkCreateTrip: {', '.join(invalid)}")
    return normalized

def read_route_stops(source_path: str | Path) -> list[RouteStop]:
    path = Path(source_path)
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = read_shared_strings(archive)
            sheet_path = first_sheet_path(archive)
            worksheet = ET.fromstring(archive.read(sheet_path))
    except KeyError as exc:
        raise ValueError("El archivo Excel no tiene la estructura esperada.") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo no es un .xlsx valido.") from exc
    except ET.ParseError as exc:
        raise ValueError("El archivo Excel no se pudo leer correctamente.") from exc

    rows = read_rows(worksheet, shared_strings)
    if not rows:
        raise ValueError("El archivo Excel esta vacio.")

    header_row = rows[0]
    header_indexes = map_required_headers(header_row)
    stops: list[RouteStop] = []
    for row in rows[1:]:
        station_name = value_at(row, header_indexes["station name"])
        latitude = value_at(row, header_indexes["latitude"])
        longitude = value_at(row, header_indexes["longitude"])
        if not station_name and not latitude and not longitude:
            continue
        if not station_name or not latitude or not longitude:
            raise ValueError("Cada parada debe tener station name, latitude y longitude.")
        stops.append(
            RouteStop(
                station_name=clean_station_name(station_name),
                latitude=normalize_coordinate(latitude, "latitude"),
                longitude=normalize_coordinate(longitude, "longitude"),
            )
        )
    return stops


def resolve_checkpoint_conflicts(stops: list[RouteStop]) -> list[RouteStop]:
    selected: list[RouteStop] = []
    for index, stop in enumerate(stops):
        if not selected:
            selected.append(stop)
            continue

        conflicts_with_selected = any(checkpoint_distance_meters(stop, kept) <= CHECKPOINT_CONFLICT_METERS for kept in selected)
        closes_route = index == len(stops) - 1 and checkpoint_distance_meters(stop, selected[0]) <= CHECKPOINT_CONFLICT_METERS
        if conflicts_with_selected and not closes_route:
            continue
        selected.append(stop)
    return selected


def checkpoint_distance_meters(first: RouteStop, second: RouteStop) -> float:
    return haversine_meters(
        float(first.longitude),
        float(first.latitude),
        float(second.longitude),
        float(second.latitude),
    )

def build_uffizio_rows(
    stops: list[RouteStop],
    *,
    today: date | None = None,
    trip_type: str = "Pickup",
    vehicles: list[str] | tuple[str, ...] | None = None,
) -> list[list[str]]:
    valid_from = (today or date.today()).strftime("%d-%m-%Y")
    pickup_times = interpolate_times("07:00", "08:00", len(stops))
    drop_times = interpolate_times("12:50", "13:30", len(stops))
    trip_type_value = trip_type or "Pickup"
    vehicle_values = list(vehicles or ["vehicle 2"])
    rows: list[list[str]] = []
    total_stops = len(stops)
    for bus_index, vehicle in enumerate(vehicle_values):
        trip_name = uffizio_trip_name(vehicle, bus_index)
        for index, (stop, pickup_time, drop_time) in enumerate(zip(stops, pickup_times, drop_times)):
            rows.append(
                [
                    trip_name,
                    trip_type_value,
                    "y",
                    vehicle,
                    valid_from,
                    "30-06-2028",
                    f"{stop.latitude},{stop.longitude}",
                    "",
                    uffizio_checkpoint_name(stop, index, total_stops),
                    pickup_time,
                    drop_time,
                    "",
                    "y",
                    "y",
                    "y",
                    "y",
                    "y",
                    "",
                    "",
                    "",
                ]
            )
    return rows


def uffizio_trip_name(vehicle: str, index: int) -> str:
    match = re.search(r"\d+", vehicle or "")
    suffix = match.group(0) if match else re.sub(r"[^A-Za-z0-9]+", " ", vehicle or "").strip()
    suffix = suffix or str(index + 1)
    return f"Bus {suffix} 8AM"

def uffizio_checkpoint_name(stop: RouteStop, index: int, total_stops: int) -> str:
    if index == 0:
        return "Start"
    if index == total_stops - 1:
        return "End"
    return stop.station_name


def write_bulk_trip_from_template(output_path: Path, rows: list[list[str]], template_path: Path) -> None:
    if not template_path.is_file():
        raise FileNotFoundError(f"No se encontro la plantilla BulkCreateTrip: {template_path}")

    with zipfile.ZipFile(template_path) as source:
        shared_root = ET.fromstring(source.read("xl/sharedStrings.xml"))
        string_index = SharedStringIndex(shared_root)
        sheet_xml = source.read("xl/worksheets/sheet1.xml")
        sheet_root = build_bulk_trip_sheet(sheet_xml, rows, string_index)
        shared_xml = xml_bytes(shared_root)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    data = xml_bytes(sheet_root)
                elif item.filename == "xl/sharedStrings.xml":
                    data = shared_xml
                target.writestr(item, data)


def build_bulk_trip_sheet(sheet_xml: bytes, rows: list[list[str]], string_index: "SharedStringIndex") -> ET.Element:
    worksheet = ET.fromstring(sheet_xml)
    normalize_worksheet_compatibility(worksheet)

    last_row = max(3, len(rows) + DATA_START_ROW - 1)
    dimension = worksheet.find(xlsx_tag("dimension"))
    if dimension is not None:
        dimension.set("ref", f"A1:T{last_row}")

    old_sheet_data = worksheet.find(xlsx_tag("sheetData"))
    insert_index = list(worksheet).index(old_sheet_data) if old_sheet_data is not None else len(worksheet)
    if old_sheet_data is not None:
        worksheet.remove(old_sheet_data)

    sheet_data = ET.Element(xlsx_tag("sheetData"))
    if old_sheet_data is not None:
        for old_row in old_sheet_data.findall(xlsx_tag("row")):
            row_number = int(old_row.attrib.get("r", "0") or 0)
            if row_number < DATA_START_ROW:
                sheet_data.append(old_row)
    for row_number, row_values in enumerate(rows, start=DATA_START_ROW):
        add_shared_string_row(sheet_data, row_number, row_values, string_index)

    worksheet.insert(insert_index, sheet_data)
    return worksheet


def add_shared_string_row(parent: ET.Element, row_number: int, values: list[str], string_index: "SharedStringIndex") -> None:
    row = ET.SubElement(parent, xlsx_tag("row"), {"r": str(row_number)})
    for column_index, value in enumerate(values, start=1):
        if value == "":
            continue
        attrs = {"r": f"{column_letter(column_index)}{row_number}", "t": "s"}
        cell = ET.SubElement(row, xlsx_tag("c"), attrs)
        ET.SubElement(cell, xlsx_tag("v")).text = str(string_index.index(value))


class SharedStringIndex:
    def __init__(self, root: ET.Element):
        self.root = root
        self.values = read_shared_string_values(root)
        self.lookup = {value: index for index, value in enumerate(self.values)}
        self.count = int(root.attrib.get("count", str(len(self.values))) or len(self.values))

    def index(self, value: str) -> int:
        value = clean_xlsx_text(value)
        if value in self.lookup:
            self.count += 1
            self.root.set("count", str(self.count))
            return self.lookup[value]

        item = ET.SubElement(self.root, xlsx_tag("si"))
        text = ET.SubElement(item, xlsx_tag("t"))
        text.text = value
        index = len(self.values)
        self.values.append(value)
        self.lookup[value] = index
        self.count += 1
        self.root.set("count", str(self.count))
        self.root.set("uniqueCount", str(len(self.values)))
        return index


def first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = workbook_relationships(archive)
    first_sheet = workbook.find(f"{xlsx_tag('sheets')}/{xlsx_tag('sheet')}")
    if first_sheet is None:
        raise KeyError("workbook sheet")
    rel_id = first_sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
    if not rel_id or rel_id not in relationships:
        raise KeyError("workbook relationship")
    return relationships[rel_id]


def sheet_path_by_name(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = workbook_relationships(archive)
    for sheet in workbook.findall(f"{xlsx_tag('sheets')}/{xlsx_tag('sheet')}"):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
        if not rel_id or rel_id not in relationships:
            raise KeyError(f"sheet relationship {sheet_name}")
        return relationships[rel_id]
    raise KeyError(f"sheet {sheet_name}")

def workbook_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationships: dict[str, str] = {}
    for relationship in root.findall(package_tag("Relationship")):
        target = relationship.attrib.get("Target", "")
        if not target.startswith("/"):
            target = posixpath.normpath(posixpath.join("xl", target))
        else:
            target = target.lstrip("/")
        relationships[relationship.attrib["Id"]] = target
    return relationships


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return read_shared_string_values(root)


def read_shared_string_values(root: ET.Element) -> list[str]:
    return ["".join(text.text or "" for text in item.findall(f".//{xlsx_tag('t')}")) for item in root.findall(xlsx_tag("si"))]


def read_rows(worksheet: ET.Element, shared_strings: list[str]) -> list[dict[int, str]]:
    rows: list[dict[int, str]] = []
    for row in worksheet.findall(f".//{xlsx_tag('sheetData')}/{xlsx_tag('row')}"):
        values: dict[int, str] = {}
        for cell in row.findall(xlsx_tag("c")):
            column_index = column_index_from_ref(cell.attrib.get("r", ""))
            if column_index:
                values[column_index] = cell_value(cell, shared_strings)
        rows.append(values)
    return rows


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(f".//{xlsx_tag('t')}")).strip()

    value = cell.find(xlsx_tag("v"))
    if value is None or value.text is None:
        return ""
    raw = value.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw)].strip()
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return "true" if raw == "1" else "false"
    return raw


def map_required_headers(row: dict[int, str]) -> dict[str, int]:
    headers = {normalize_header(value): index for index, value in row.items() if value}
    missing = [header for header in REQUIRED_SOURCE_HEADERS if header not in headers]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing)}.")
    return {header: headers[header] for header in REQUIRED_SOURCE_HEADERS}


def value_at(row: dict[int, str], column_index: int) -> str:
    return (row.get(column_index) or "").strip()


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def normalize_coordinate(value: str, label: str) -> str:
    cleaned = value.strip().replace(",", ".")
    try:
        number = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"La columna {label} contiene una coordenada invalida: {value}") from exc
    return f"{number:.8f}"


def clean_station_name(value: str) -> str:
    cleaned = re.sub(r"[,&]+", " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return clean_xlsx_text(cleaned)


def interpolate_times(start: str, end: str, count: int) -> list[str]:
    if count <= 0:
        return []
    start_minutes = parse_hhmm(start)
    end_minutes = parse_hhmm(end)
    if count == 1:
        return [format_hhmm(start_minutes)]
    step = (end_minutes - start_minutes) / (count - 1)
    return [format_hhmm(round(start_minutes + step * index)) for index in range(count)]


def parse_hhmm(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def format_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


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


def column_index_from_ref(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
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


def clean_xlsx_text(value: str) -> str:
    return "".join(char for char in str(value) if is_valid_xml_char(char))


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


def xlsx_tag(name: str) -> str:
    return f"{{{SPREADSHEET_NS}}}{name}"


def package_tag(name: str) -> str:
    return f"{{{PACKAGE_REL_NS}}}{name}"


def xml_bytes(root: ET.Element) -> bytes:
    return XML_DECLARATION + ET.tostring(root, encoding="utf-8")
