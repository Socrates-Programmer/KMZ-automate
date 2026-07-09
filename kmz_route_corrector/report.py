from __future__ import annotations

import csv
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

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
    "es_pf",
    "metodo_ordenamiento",
    "advertencias",
]

ROUTE_EXCEL_HEADERS = ["ns1:name3", "ns1:name4", "Columna1", "ns1:coordinates"]
ROUTE_EXCEL_FOLDER_NAME = "Paradas corregidas"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

ET.register_namespace("", SPREADSHEET_NS)
ET.register_namespace("r", OFFICE_REL_NS)


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
                    "es_pf": "si" if stop.is_pf else "no",
                    "metodo_ordenamiento": stop.ordering_method,
                    "advertencias": " | ".join(stop.warnings),
                }
            )


def write_route_excels(output_dir: str | Path, corrections: list[RouteCorrection]) -> list[Path]:
    excel_dir = Path(output_dir)
    if excel_dir.exists():
        shutil.rmtree(excel_dir)
    excel_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    route_numbers_by_district: dict[str, int] = {}
    for correction in corrections:
        if not correction.stops:
            continue
        district_name = safe_excel_filename(correction.route.district_name or "Sin distrito")
        route_number = route_numbers_by_district.get(district_name, 0) + 1
        route_numbers_by_district[district_name] = route_number
        filename = f"{route_number:03d}_{safe_excel_filename(correction.route.name)}.xlsx"
        path = excel_dir / district_name / filename
        write_route_excel(path, correction.stops)
        paths.append(path)
    return paths


def safe_excel_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name or "Ruta")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "Ruta")[:80]


def write_route_excel(path: str | Path, stops: list[CorrectedStop]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", xml_bytes(build_content_types()))
        archive.writestr("_rels/.rels", xml_bytes(build_root_relationships()))
        archive.writestr("docProps/app.xml", docprops_app_xml())
        archive.writestr("docProps/core.xml", docprops_core_xml())
        archive.writestr("xl/workbook.xml", xml_bytes(build_workbook()))
        archive.writestr("xl/_rels/workbook.xml.rels", xml_bytes(build_workbook_relationships()))
        archive.writestr("xl/styles.xml", xml_bytes(build_styles()))
        archive.writestr("xl/worksheets/sheet1.xml", xml_bytes(build_route_sheet(stops)))


def build_route_sheet(stops: list[CorrectedStop]) -> ET.Element:
    worksheet = ET.Element(xlsx_tag("worksheet"))
    dimension = ET.SubElement(worksheet, xlsx_tag("dimension"))
    dimension.set("ref", f"A1:D{len(stops) + 1}")

    cols = ET.SubElement(worksheet, xlsx_tag("cols"))
    for min_col, max_col, width in [("1", "1", "18.42578125"), ("2", "2", "66.7109375"), ("4", "4", "31.5703125")]:
        ET.SubElement(
            cols,
            xlsx_tag("col"),
            {"min": min_col, "max": max_col, "width": width, "bestFit": "1", "customWidth": "1"},
        )

    sheet_data = ET.SubElement(worksheet, xlsx_tag("sheetData"))
    add_xlsx_row(sheet_data, 1, ROUTE_EXCEL_HEADERS)
    for row_index, stop in enumerate(stops, start=2):
        add_xlsx_row(
            sheet_data,
            row_index,
            [
                ROUTE_EXCEL_FOLDER_NAME,
                stop.new_name,
                stop.new_lat,
                stop.new_lon,
            ],
        )
    return worksheet


def add_xlsx_row(parent: ET.Element, row_index: int, values: list[str | float]) -> None:
    row = ET.SubElement(parent, xlsx_tag("row"), {"r": str(row_index)})
    for column_index, value in enumerate(values, start=1):
        cell_ref = f"{column_letter(column_index)}{row_index}"
        if isinstance(value, float):
            cell = ET.SubElement(row, xlsx_tag("c"), {"r": cell_ref})
            ET.SubElement(cell, xlsx_tag("v")).text = f"{value:.8f}"
            continue
        cell = ET.SubElement(row, xlsx_tag("c"), {"r": cell_ref, "t": "inlineStr"})
        inline_string = ET.SubElement(cell, xlsx_tag("is"))
        ET.SubElement(inline_string, xlsx_tag("t")).text = str(value)


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
        {"name": ROUTE_EXCEL_FOLDER_NAME, "sheetId": "1", f"{{{OFFICE_REL_NS}}}id": "rId1"},
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
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_warnings(path: str | Path, warnings: list[str]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        if not warnings:
            handle.write("Sin advertencias.\n")
            return
        for warning in warnings:
            handle.write(f"{warning}\n")
