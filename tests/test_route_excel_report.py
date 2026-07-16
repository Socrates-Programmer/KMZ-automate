import csv
import zipfile
import xml.etree.ElementTree as ET

from kmz_route_corrector.core import make_bundle
from kmz_route_corrector.irregularity_report import write_irregularities_pdf
from kmz_route_corrector.models import Irregularity
from kmz_route_corrector.models import CorrectedStop, Route, RouteCorrection
from kmz_route_corrector.route_detector import detect_routes
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
        "BUS-77",
        "CHOFER UNO",
        "RUTA 2",
        "P1 - CENTRO EDUCATIVO TEST",
        "18.45523777",
        "-69.01537494",
    ]
    assert rows[2] == [
        "0511R2P2",
        "BUS-88",
        "CHOFER DOS",
        "RUTA 2",
        "P2",
        "18.45230103",
        "-69.01379205",
    ]


def test_route_excel_label_uses_route_number():
    assert route_excel_label("Ruta #2") == "RUTA 2"
    assert route_excel_label("Ruta#4") == "RUTA 4"
    assert route_excel_label("Ruta_#12") == "RUTA 12"


def test_write_route_excels_keeps_routes_without_stops(tmp_path):
    route = Route(
        name="Ruta #11 Jaiqui Picao (en espera bus)",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-70.1, 19.1, None), (-70.2, 19.2, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="Distrito 08-01 SJM",
    )
    correction = RouteCorrection(route=route, ordering_method="sin_paradas", stops=[])

    paths = write_route_excels(
        tmp_path / "excel_rutas",
        [correction],
        drivers_csv_path=tmp_path / "KMZ.csv",
        route_template_path=tmp_path / "plantilla-inexistente.xlsx",
        route_excel_template=ROUTE_EXCEL_TEMPLATE_STOPS,
    )

    assert len(paths) == 1
    assert paths[0].parent.name == "Rutas 08-01"
    assert paths[0].name == "001_Ruta #11 Jaiqui Picao (en espera bus).xlsx"
    rows = read_sheet_rows(paths[0])
    assert rows[0] == STOP_ROUTE_TEMPLATE_HEADERS


def test_nested_route_uses_district_parent_not_route_parent():
    kml = """<kml xmlns="http://www.opengis.net/kml/2.2">
    <Document>
      <name>Santiago Rutas escolares</name>
      <Folder>
        <name>Distrito 08-01 SJM</name>
        <Folder>
          <name>Ruta #6</name>
          <Folder>
            <name>Ruta #6</name>
            <Placemark>
              <name>Ruta #6</name>
              <LineString><coordinates>-70.1,19.1,0 -70.2,19.2,0</coordinates></LineString>
            </Placemark>
            <Folder>
              <name>Paradas</name>
              <Placemark><name>P1</name><Point><coordinates>-70.1,19.1,0</coordinates></Point></Placemark>
            </Folder>
          </Folder>
        </Folder>
      </Folder>
    </Document>
    </kml>"""
    root = ET.fromstring(kml)

    routes, _ = detect_routes(root)

    assert len(routes) == 1
    assert routes[0].name == "Ruta #6"
    assert routes[0].district_name == "Distrito 08-01 SJM"


def test_detect_routes_uses_corrected_stops_when_original_stops_are_absent():
    kml = """<kml xmlns="http://www.opengis.net/kml/2.2">
    <Document>
      <Folder>
        <name>Distrito 08-01 SJM</name>
        <Folder>
          <name>Ruta #6</name>
          <Placemark>
            <name>Ruta #6</name>
            <LineString><coordinates>-70.1,19.1,0 -70.2,19.2,0</coordinates></LineString>
          </Placemark>
          <Folder>
            <name>Paradas corregidas</name>
            <Placemark><name>P1</name><Point><coordinates>-70.1,19.1,0</coordinates></Point></Placemark>
          </Folder>
        </Folder>
      </Folder>
    </Document>
    </kml>"""
    root = ET.fromstring(kml)

    routes, _ = detect_routes(root)

    assert len(routes) == 1
    assert routes[0].district_name == "Distrito 08-01 SJM"
    assert [stop.name for stop in routes[0].stops] == ["P1"]


def test_detect_routes_keeps_multiple_elevation_profiles():
    kml = """<kml xmlns="http://www.opengis.net/kml/2.2">
    <Document>
      <Folder>
        <name>Distrito 08-01 SJM</name>
        <Folder>
          <name>Ruta #6</name>
          <Placemark>
            <name>Perfil 1</name>
            <LineString><coordinates>-70.1,19.1,0 -70.11,19.11,0</coordinates></LineString>
          </Placemark>
          <Placemark>
            <name>Perfil 2</name>
            <LineString><coordinates>-70.3,19.3,0 -70.4,19.4,0 -70.5,19.5,0</coordinates></LineString>
          </Placemark>
          <Folder>
            <name>Paradas</name>
            <Placemark><name>P1</name><Point><coordinates>-70.3,19.3,0</coordinates></Point></Placemark>
          </Folder>
        </Folder>
      </Folder>
    </Document>
    </kml>"""
    root = ET.fromstring(kml)

    routes, _ = detect_routes(root)

    assert len(routes) == 1
    assert len(routes[0].line_coord_sets) == 2
    assert routes[0].line_coords == routes[0].line_coord_sets[0]
    assert routes[0].line_coord_sets[0][0][:2] == (-70.3, 19.3)
    assert routes[0].line_coord_sets[1][0][:2] == (-70.1, 19.1)
    assert any("perfil de mayor longitud" in warning for warning in routes[0].warnings)


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


def test_irregularities_pdf_is_generated(tmp_path):
    path = tmp_path / "reporte_irregularidades.pdf"
    write_irregularities_pdf(
        path,
        [
            Irregularity(
                route_name="Ruta #1",
                district_name="Distrito 07-05 Sur Este",
                kind="route_gap",
                title="Tramo largo sin paradas",
                description="Tramo de prueba sin paradas.",
                lon=-69.1,
                lat=18.0,
                line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
                points=[("P1", -69.2, 18.0), ("P2", -69.0, 18.0)],
                distance_meters=2000,
            )
        ],
    )

    pdf_bytes = path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert b"Indice por distrito y ruta" in pdf_bytes
    assert b"Resumen de ruta" in pdf_bytes
    assert b"Distrito: Distrito 07-05 Sur Este | Ruta: Ruta #1" in pdf_bytes
    assert b"Tramo de 2000.0 m sin paradas entre P1 y P2." in pdf_bytes
    assert b"Grafico consolidado: todas las irregularidades de esta ruta" in pdf_bytes
    assert b"franja amarilla/roja=recorrido KML" in pdf_bytes
    assert b"Detalle de irregularidad" not in pdf_bytes
    assert b"Pagina 1 de 2" in pdf_bytes


def test_bundle_includes_route_excels(tmp_path):
    kmz_path = tmp_path / "rutas_corregido.kmz"
    report_path = tmp_path / "reporte_correccion_rutas.csv"
    flow_path = tmp_path / "recorrido_ruta.csv"
    irregularities_path = tmp_path / "reporte_irregularidades.pdf"
    warnings_path = tmp_path / "warnings.log"
    excel_path = tmp_path / "excel_rutas" / "Rutas 05-11" / "001_Ruta #2.xlsx"
    for path in [kmz_path, report_path, flow_path, irregularities_path, warnings_path, excel_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")

    bundle_path = make_bundle(
        kmz_path,
        tmp_path / "rutas_corregido.kml",
        report_path,
        warnings_path,
        [excel_path],
        route_flow_path=flow_path,
        irregularities_report_path=irregularities_path,
    )

    with zipfile.ZipFile(bundle_path) as archive:
        assert sorted(archive.namelist()) == [
            "excel_rutas/Rutas 05-11/001_Ruta #2.xlsx",
            "recorrido_ruta.csv",
            "reporte_correccion_rutas.csv",
            "reporte_irregularidades.pdf",
            "rutas_corregido.kmz",
            "warnings.log",
        ]
