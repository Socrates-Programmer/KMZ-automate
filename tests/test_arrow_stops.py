import csv
import zipfile
import xml.etree.ElementTree as ET

from kmz_route_corrector.arrow_stops import convert_arrow_points_to_bus_stops
from kmz_route_corrector.geometry import distance_to_line_meters
from kmz_route_corrector.kml_parser import kml_tag, line_coordinates, point_coordinate
from kmz_route_corrector.kml_writer import STYLE_OUTBOUND
from kmz_route_corrector.uffizio import read_route_stops


def write_kmz(path, kml_text):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("doc.kml", kml_text)


def read_output_kml(path):
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("doc.kml"))


def sample_kml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Flechas</name>
    <Style id="arrow-style">
      <IconStyle>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/shapes/arrow.png</href>
        </Icon>
      </IconStyle>
    </Style>
    <StyleMap id="arrow-map">
      <Pair>
        <key>normal</key>
        <styleUrl>#arrow-style</styleUrl>
      </Pair>
    </StyleMap>
    <Style id="donut-style">
      <IconStyle>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/shapes/donut.png</href>
        </Icon>
      </IconStyle>
    </Style>
    <Folder>
      <name>Lugares</name>
      <Placemark>
        <name>Salida Villa</name>
        <styleUrl>#arrow-map</styleUrl>
        <Point><coordinates>-69.9000,18.5000,0</coordinates></Point>
      </Placemark>
      <Placemark>
        <name>Estadio</name>
        <styleUrl>#arrow-map</styleUrl>
        <Point><coordinates>-69.8990,18.4981,0</coordinates></Point>
      </Placemark>
      <Placemark>
        <name>Conexion con todos los hoteles Santiago</name>
        <styleUrl>#donut-style</styleUrl>
        <Point><coordinates>-69.9500,18.5500,0</coordinates></Point>
      </Placemark>
    </Folder>
    <Folder>
      <name>Rutas</name>
      <Placemark>
        <name>Ruta Villa - Estadio</name>
        <LineString>
          <coordinates>-69.9010,18.4970,0 -69.8990,18.4980,0 -69.9000,18.5002,0</coordinates>
        </LineString>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


def placemark_by_name(root, name):
    for placemark in root.findall(f".//{kml_tag('Placemark')}"):
        name_el = placemark.find(kml_tag("name"))
        if name_el is not None and name_el.text == name:
            return placemark
    raise AssertionError(f"No se encontro Placemark {name}")


def test_converts_arrow_points_to_bus_style_keeps_donut_and_generates_uffizio_excel(tmp_path):
    input_path = tmp_path / "juegos.kmz"
    write_kmz(input_path, sample_kml())

    result = convert_arrow_points_to_bus_stops(input_path, output_dir=tmp_path)

    assert result.converted_count == 2
    assert result.point_count == 3
    assert result.route_count == 1
    assert len(result.route_excel_paths) == 1
    assert result.output_kmz_path.name == "juegos_paradas_bus.kmz"
    assert result.bundle_zip_path.name == "juegos_paradas_bus_resultados.zip"

    root = read_output_kml(result.output_kmz_path)
    converted = placemark_by_name(root, "Estadio")
    donut = placemark_by_name(root, "Conexion con todos los hoteles Santiago")
    route = placemark_by_name(root, "Ruta Villa - Estadio")

    assert converted.find(kml_tag("styleUrl")).text == f"#{STYLE_OUTBOUND}"
    assert donut.find(kml_tag("styleUrl")).text == "#donut-style"
    assert len(root.findall(f".//{kml_tag('Point')}")) == 3

    moved_lon, moved_lat, _ = point_coordinate(converted)
    distance = distance_to_line_meters(moved_lon, moved_lat, line_coordinates(route))
    assert 19.0 <= distance <= 21.0

    route_stops = read_route_stops(result.route_excel_paths[0])
    assert [stop.station_name for stop in route_stops] == ["Estadio", "Salida Villa"]


def test_report_uses_nearest_linestring_and_radius_flag(tmp_path):
    input_path = tmp_path / "juegos.kmz"
    write_kmz(input_path, sample_kml())

    result = convert_arrow_points_to_bus_stops(input_path, output_dir=tmp_path, route_match_radius_meters=1)

    with result.report_csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert rows[0]["nombre"] == "Salida Villa"
    assert rows[0]["ruta_mas_cercana"] == "Ruta Villa - Estadio"
    assert rows[0]["dentro_radio"] == "no"

    with zipfile.ZipFile(result.bundle_zip_path) as archive:
        assert sorted(archive.namelist()) == [
            "juegos_paradas_bus.kmz",
            "reporte_flechas_paradas.csv",
            "warnings.log",
        ]


def test_zip_includes_uffizio_excels_when_routes_have_nearby_stops(tmp_path):
    input_path = tmp_path / "juegos.kmz"
    write_kmz(input_path, sample_kml())

    result = convert_arrow_points_to_bus_stops(input_path, output_dir=tmp_path)

    with zipfile.ZipFile(result.bundle_zip_path) as archive:
        names = sorted(archive.namelist())

    assert "excel_uffizio/001_Ruta Villa - Estadio.xlsx" in names
    assert "juegos_paradas_bus.kmz" in names
    assert "reporte_flechas_paradas.csv" in names
    assert "warnings.log" in names

def test_already_converted_bus_kmz_still_generates_uffizio_excel(tmp_path):
    input_path = tmp_path / "juegos.kmz"
    write_kmz(input_path, sample_kml())
    first_result = convert_arrow_points_to_bus_stops(input_path, output_dir=tmp_path / "first")

    second_result = convert_arrow_points_to_bus_stops(
        first_result.output_kmz_path,
        output_dir=tmp_path / "second",
    )

    assert second_result.converted_count == 0
    assert len(second_result.route_excel_paths) == 1
    assert second_result.output_kmz_path.name == "juegos_paradas_bus.kmz"
    assert second_result.bundle_zip_path.name == "juegos_paradas_bus_resultados.zip"
    assert [stop.station_name for stop in read_route_stops(second_result.route_excel_paths[0])] == ["Estadio", "Salida Villa"]
