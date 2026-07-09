import zipfile
import xml.etree.ElementTree as ET

from kmz_route_corrector.core import make_bundle
from kmz_route_corrector.models import CorrectedStop, Route, RouteCorrection
from kmz_route_corrector.report import write_route_excels


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


def test_write_route_excels_uses_route_x_template_columns(tmp_path):
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

    paths = write_route_excels(tmp_path / "excel_rutas", [correction])

    assert len(paths) == 1
    assert paths[0].name == "001_Ruta #2.xlsx"
    assert paths[0].parent.name == "05-11 Rutas Villa Hermosa"
    rows = read_sheet_rows(paths[0])
    assert rows[0] == ["ns1:name3", "ns1:name4", "Columna1", "ns1:coordinates"]
    assert rows[1] == ["Paradas corregidas", "P1 - CENTRO EDUCATIVO TEST", "18.45523777", "-69.01537494"]
    assert rows[2] == ["Paradas corregidas", "P2", "18.45230103", "-69.01379205"]


def test_bundle_includes_route_excels(tmp_path):
    kmz_path = tmp_path / "rutas_corregido.kmz"
    report_path = tmp_path / "reporte_correccion_rutas.csv"
    warnings_path = tmp_path / "warnings.log"
    excel_path = tmp_path / "excel_rutas" / "05-11 Rutas Villa Hermosa" / "001_Ruta #2.xlsx"
    for path in [kmz_path, report_path, warnings_path, excel_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")

    bundle_path = make_bundle(kmz_path, tmp_path / "rutas_corregido.kml", report_path, warnings_path, [excel_path])

    with zipfile.ZipFile(bundle_path) as archive:
        assert sorted(archive.namelist()) == [
            "excel_rutas/05-11 Rutas Villa Hermosa/001_Ruta #2.xlsx",
            "reporte_correccion_rutas.csv",
            "rutas_corregido.kmz",
            "warnings.log",
        ]
