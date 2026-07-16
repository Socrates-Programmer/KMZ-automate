import zipfile
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from kmz_route_corrector.uffizio import create_uffizio_bulk_trip


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def write_source_route_excel(path, rows, headers=("station name", "latitude", "longitude")):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr("xl/worksheets/sheet1.xml", source_sheet_xml(rows, headers))


def source_sheet_xml(rows, headers=("station name", "latitude", "longitude")):
    xml_rows = [source_row_xml(1, list(headers))]
    for index, row in enumerate(rows, start=2):
        xml_rows.append(source_row_xml(index, row))
    return (
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>"""
        + "".join(xml_rows)
        + """</sheetData>
</worksheet>"""
    )


def source_row_xml(row_number, values):
    cells = []
    for column, value in zip(("A", "B", "C"), values):
        cells.append(f'<c r="{column}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>')
    return f'<row r="{row_number}">{"".join(cells)}</row>'


def output_sheet_values(path):
    with zipfile.ZipFile(path) as archive:
        shared = shared_strings(archive)
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        values = {}
        types = {}
        for cell in root.findall(".//x:sheetData/x:row/x:c", NS):
            ref = cell.attrib["r"]
            types[ref] = cell.attrib.get("t")
            values[ref] = cell_value(cell, shared)
        validations = root.findall(".//x:dataValidations/x:dataValidation", NS)
        names = archive.namelist()
    return values, types, validations, names


def shared_strings(archive):
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(text.text or "" for text in item.findall(".//x:t", NS)) for item in root.findall("x:si", NS)]


def cell_value(cell, shared):
    value = cell.find("x:v", NS)
    if value is None or value.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        return shared[int(value.text)]
    return value.text


def test_create_uffizio_bulk_trip_preserves_template_and_writes_expected_rows(tmp_path):
    source = tmp_path / "001_Ruta #22_MC.xlsx"
    output = tmp_path / "BulkCreateTrip.xlsx"
    write_source_route_excel(
        source,
        [
            ["P1 - ESCUELA, UNO &amp; DOS", "18.5", "-69.2"],
            ["P2", "18.75", "-69.35"],
        ],
    )

    create_uffizio_bulk_trip(source, output, today=date(2026, 7, 16))

    values, types, validations, names = output_sheet_values(output)
    assert "xl/worksheets/sheet2.xml" in names
    assert "xl/worksheets/sheet3.xml" in names
    assert len(validations) == 2
    assert values["A4"] == "Bus 2 8AM"
    assert values["B4"] == "Pickup"
    assert types["B4"] == "s"
    assert values["C4"] == "y"
    assert values["D4"] == "vehicle 2"
    assert types["D4"] == "s"
    assert values["E4"] == "16-07-2026"
    assert values["F4"] == "30-06-2028"
    assert values["G4"] == "18.50000000,-69.20000000"
    assert "H4" not in values
    assert values["I4"] == "Start"
    assert values["J4"] == "07:00"
    assert values["K4"] == "12:50"
    assert "L4" not in values
    assert [values[f"{column}4"] for column in ("M", "N", "O", "P", "Q")] == ["y"] * 5
    assert "R4" not in values
    assert "S4" not in values
    assert "T4" not in values
    assert values["I5"] == "End"
    assert values["J5"] == "08:00"
    assert values["K5"] == "13:30"


def test_create_uffizio_bulk_trip_drops_internal_conflicting_checkpoints(tmp_path):
    source = tmp_path / "ruta.xlsx"
    output = tmp_path / "BulkCreateTrip.xlsx"
    write_source_route_excel(
        source,
        [
            ["P1", "18.00000000", "-69.00000000"],
            ["P2", "18.00100000", "-69.00100000"],
            ["P3 duplicada", "18.00110000", "-69.00100000"],
            ["P4 cierre", "18.00010000", "-69.00000000"],
        ],
    )

    create_uffizio_bulk_trip(source, output, today=date(2026, 7, 16))

    values, _, _, _ = output_sheet_values(output)
    assert values["I4"] == "Start"
    assert values["I5"] == "P2"
    assert values["I6"] == "End"
    assert "I7" not in values
    assert values["J4"] == "07:00"
    assert values["J5"] == "07:30"
    assert values["J6"] == "08:00"

def test_create_uffizio_bulk_trip_writes_one_block_per_selected_vehicle(tmp_path):
    source = tmp_path / "ruta.xlsx"
    output = tmp_path / "BulkCreateTrip.xlsx"
    write_source_route_excel(
        source,
        [
            ["P1", "18.00000000", "-69.00000000"],
            ["P2", "18.00100000", "-69.00100000"],
        ],
    )

    create_uffizio_bulk_trip(source, output, today=date(2026, 7, 16), trip_type="Drop", vehicles=["vehicle 2", "vehicle 3"])

    values, _, _, _ = output_sheet_values(output)
    assert values["A4"] == "Bus 2 8AM"
    assert values["B4"] == "Drop"
    assert values["D4"] == "vehicle 2"
    assert values["K4"] == "12:50"
    assert values["K5"] == "13:30"
    assert values["I4"] == "Start"
    assert values["I5"] == "End"
    assert values["A6"] == "Bus 3 8AM"
    assert values["B6"] == "Drop"
    assert values["D6"] == "vehicle 3"
    assert values["K6"] == "12:50"
    assert values["K7"] == "13:30"
    assert values["I6"] == "Start"
    assert values["I7"] == "End"

def test_create_uffizio_bulk_trip_rejects_missing_source_headers(tmp_path):
    source = tmp_path / "ruta.xlsx"
    output = tmp_path / "BulkCreateTrip.xlsx"
    write_source_route_excel(source, [["P1", "18.5", "-69.2"]], headers=("station name", "latitude", "lon"))

    with pytest.raises(ValueError, match="Faltan columnas requeridas"):
        create_uffizio_bulk_trip(source, output)
