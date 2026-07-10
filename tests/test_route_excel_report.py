import csv
import zipfile
import xml.etree.ElementTree as ET

from kmz_route_corrector.core import make_bundle
from kmz_route_corrector.models import CorrectedStop, Route, RouteCorrection
from kmz_route_corrector.report import (
    ROUTE_EXCEL_TEMPLATE_STOPS,
    STOP_ROUTE_TEMPLATE_HEADERS,
    build_bulk_trip_settings,
    build_route_sheet_from_template,
    default_drivers_csv_path,
    resolve_route_template_path,
    route_excel_label,
    write_route_excels,
    write_route_flow_report,
)


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def make_stop(name, lat, lon):
    return CorrectedStop(
        route_name="Ruta #2",
        original_name=name,
        new_name=name,
        tipo="ida",
        original_lon=lon,
        original_lat=lat,
        new_lon=lon,
        new_lat=lat,
        offset_meters=8,
    )


def cell_value(cell):
    inline_text = cell.find(".//x:t", NS)
    if inline_text is not None:
        return inline_text.text or ""
    value = cell.find("x:v", NS)
    return value.text if value is not None else ""


def read_sheet_rows(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in root.findall(".//x:sheetData/x:row", NS):
        rows.append([cell_value(cell) for cell in row.findall("x:c", NS)])
    return rows


BULK_HEADERS = [
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


def fixed_bulk_settings():
    return build_bulk_trip_settings(
        valid_from="01-01-2026",
        valid_to="31-12-2026",
        pickup_time="06:30",
        drop_time="14:15",
        schedule_days="Mo,Tu,We,Th,Fr",
        location="TEST LOCATION",
    )


def test_write_route_excels_uses_route_x_template_columns(tmp_path):
    drivers_csv = tmp_path / "KMZ.csv"
    drivers_csv.write_text(
        "FICHA,DISTRITO,No. RUTA,NOMBRES Y APELLIDOS AUXILIAR,NOMBRES Y APELLIDOS CHOFER,NOTAS PERSONAL NUEVOS NOMBRAMIENTOS\n"
        "BUS-77,05-11,2,AUXILIAR TEST,CHOFER TEST,\n",
        encoding="utf-8",
    )
    route = Route(
        name="Ruta #2",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="05-11 Rutas Villa Hermosa",
    )
    correction = RouteCorrection(
        route=route,
        ordering_method="linea",
        stops=[
            make_stop("P1 - CENTRO EDUCATIVO TEST", 18.45523777, -69.01537494),
            make_stop("P2", 18.45230103, -69.01379205),
        ],
    )

    paths = write_route_excels(
        tmp_path / "excel_rutas",
        [correction],
        drivers_csv_path=drivers_csv,
        route_template_path=tmp_path / "plantilla-inexistente.xlsx",
        bulk_trip_settings=fixed_bulk_settings(),
    )

    assert len(paths) == 1
    assert paths[0].name == "001_Ruta #2.xlsx"
    assert paths[0].parent.name == "Rutas 05-11"
    rows = read_sheet_rows(paths[0])
    assert rows[1] == BULK_HEADERS
    assert rows[2] == [
        "Ruta2",
        "Pickup",
        "Yes",
        "BUS-77",
        "01-01-2026",
        "31-12-2026",
        "(18.45523777,-69.01537494),(18.45230103,-69.01379205)",
        "No",
        "P1 - CENTRO EDUCATIVO TEST,P2",
        "06:30",
        "14:15",
        "0511R2",
        "Yes",
        "Yes",
        "Yes",
        "Yes",
        "Yes",
        "No",
        "No",
        "TEST LOCATION",
    ]


def test_route_excel_defaults_use_local_project_files(monkeypatch):
    monkeypatch.delenv("KMZ_DRIVERS_CSV_PATH", raising=False)
    monkeypatch.delenv("KMZ_ROUTE_TEMPLATE_PATH", raising=False)

    assert default_drivers_csv_path().parts[-2:] == ("db", "KMZ.csv")
    assert resolve_route_template_path(None).parts[-2:] == ("kmz-plantilla", "BulkCreateTrip.xlsx")
    assert resolve_route_template_path(None, ROUTE_EXCEL_TEMPLATE_STOPS).parts[-2:] == (
        "kmz-plantilla",
        "Plantillas de rutas.xlsx",
    )


def test_write_route_excels_places_multiple_drivers_once_each(tmp_path):
    drivers_csv = tmp_path / "KMZ.csv"
    drivers_csv.write_text(
        "FICHA,DISTRITO,No. RUTA,NOMBRES Y APELLIDOS AUXILIAR,NOMBRES Y APELLIDOS CHOFER,NOTAS PERSONAL NUEVOS NOMBRAMIENTOS\n"
        "BUS-77,05-11,2,AUXILIAR TEST,CHOFER UNO,\n"
        "BUS-88,05-11,2,AUXILIAR TEST,CHOFER DOS,\n"
        "BUS-88,05-11,2,AUXILIAR TEST,CHOFER DOS,\n",
        encoding="utf-8",
    )
    route = Route(
        name="Ruta #2",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="05-11 Rutas Villa Hermosa",
    )
    correction = RouteCorrection(
        route=route,
        ordering_method="linea",
        stops=[
            make_stop("P1", 18.45523777, -69.01537494),
            make_stop("P2", 18.45230103, -69.01379205),
            make_stop("P3", 18.45240103, -69.01389205),
        ],
    )

    paths = write_route_excels(
        tmp_path / "excel_rutas",
        [correction],
        drivers_csv_path=drivers_csv,
        route_template_path=tmp_path / "plantilla-inexistente.xlsx",
        bulk_trip_settings=fixed_bulk_settings(),
    )

    rows = read_sheet_rows(paths[0])
    assert rows[2][0:4] == ["Ruta2", "Pickup", "Yes", "BUS-77"]
    assert rows[3][0:4] == ["Ruta2", "Pickup", "Yes", "BUS-88"]
    assert len(rows) == 4


def test_write_route_excels_can_use_stop_route_template(tmp_path):
    drivers_csv = tmp_path / "KMZ.csv"
    drivers_csv.write_text(
        "FICHA,DISTRITO,No. RUTA,NOMBRES Y APELLIDOS AUXILIAR,NOMBRES Y APELLIDOS CHOFER,NOTAS PERSONAL NUEVOS NOMBRAMIENTOS\n"
        "BUS-77,05-11,2,AUXILIAR TEST,CHOFER UNO,\n"
        "BUS-88,05-11,2,AUXILIAR TEST,CHOFER DOS,\n",
        encoding="utf-8",
    )
    route = Route(
        name="Ruta #2",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="05-11 Rutas Villa Hermosa",
    )
    correction = RouteCorrection(
        route=route,
        ordering_method="linea",
        stops=[
            make_stop("P1 - CENTRO EDUCATIVO TEST", 18.45523777, -69.01537494),
            make_stop("P2", 18.45230103, -69.01379205),
        ],
    )

    paths = write_route_excels(
        tmp_path / "excel_rutas",
        [correction],
        drivers_csv_path=drivers_csv,
        route_template_path=tmp_path / "plantilla-inexistente.xlsx",
        route_excel_template=ROUTE_EXCEL_TEMPLATE_STOPS,
    )

    rows = read_sheet_rows(paths[0])
    assert rows[0] == STOP_ROUTE_TEMPLATE_HEADERS
    assert rows[1] == [
        "0511R2P1",
        "BUS-77 / BUS-88",
        "CHOFER UNO / CHOFER DOS",
        "RUTA 2",
        "P1 - CENTRO EDUCATIVO TEST",
        "18.45523777",
        "-69.01537494",
    ]
    assert rows[2] == [
        "0511R2P2",
        "",
        "",
        "RUTA 2",
        "P2",
        "18.45230103",
        "-69.01379205",
    ]


def test_route_excel_label_uses_route_number():
    assert route_excel_label("Ruta #2") == "RUTA 2"
    assert route_excel_label("Ruta#4") == "RUTA 4"
    assert route_excel_label("Ruta_#12") == "RUTA 12"


def test_template_sheet_preserves_excel_compatibility_namespaces():
    template_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
    xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"
    xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision"
    xmlns:xr2="http://schemas.microsoft.com/office/spreadsheetml/2015/revision2"
    xmlns:xr3="http://schemas.microsoft.com/office/spreadsheetml/2016/revision3"
    mc:Ignorable="x14ac xr xr2 xr3"
    xr:uid="{00000000-0001-0000-0000-000000000000}">
    <dimension ref="A1:G37"/>
    <sheetFormatPr x14ac:dyDescent="0.25"/>
    <sheetData><row r="1"><c r="A1" s="3" t="s"><v>6</v></c></row></sheetData>
</worksheet>"""

    root = build_route_sheet_from_template(template_xml, [["Ruta 4", "Pickup", "", "F-0645", "", "", "(19.50000000,-70.90000000)"]])
    output = ET.tostring(root, encoding="unicode")

    assert "xmlns:ns" not in output
    assert 'mc:Ignorable="x14ac xr"' in output
    assert "xr2" not in output
    assert "xr3" not in output


def test_write_route_flow_report_exports_linestring_order(tmp_path):
    route = Route(
        name="Ruta #4",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[
            (-70.28096817, 18.52249917, None),
            (-70.28081402, 18.52260422, 12.5),
        ],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="Distrito_0401",
    )
    correction = RouteCorrection(route=route, ordering_method="linea", stops=[])
    path = tmp_path / "recorrido_ruta.csv"

    write_route_flow_report(path, [correction])

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["indice_vertice"] for row in rows] == ["1", "2"]
    assert rows[0]["distrito"] == "Distrito_0401"
    assert rows[0]["ruta"] == "Ruta #4"
    assert rows[0]["lat"] == "18.52249917"
    assert rows[0]["lon"] == "-70.28096817"
    assert rows[0]["segmento_metros"] == "0.00"
    assert rows[1]["alt"] == "12.50"
    assert float(rows[1]["distancia_acumulada_metros"]) > 0


def test_bundle_includes_route_excels(tmp_path):
    kmz_path = tmp_path / "rutas_corregido.kmz"
    report_path = tmp_path / "reporte_correccion_rutas.csv"
    flow_path = tmp_path / "recorrido_ruta.csv"
    warnings_path = tmp_path / "warnings.log"
    excel_path = tmp_path / "excel_rutas" / "Rutas 05-11" / "001_Ruta #2.xlsx"
    for path in [kmz_path, report_path, flow_path, warnings_path, excel_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")

    bundle_path = make_bundle(
        kmz_path,
        tmp_path / "rutas_corregido.kml",
        report_path,
        warnings_path,
        [excel_path],
        route_flow_path=flow_path,
    )

    with zipfile.ZipFile(bundle_path) as archive:
        assert sorted(archive.namelist()) == [
            "excel_rutas/Rutas 05-11/001_Ruta #2.xlsx",
            "recorrido_ruta.csv",
            "reporte_correccion_rutas.csv",
            "rutas_corregido.kmz",
            "warnings.log",
        ]
