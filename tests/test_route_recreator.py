import csv
import zipfile
import xml.etree.ElementTree as ET

import pytest

from kmz_route_corrector.geometry import haversine_meters
from kmz_route_corrector.kml_parser import kml_tag, name_of, point_coordinate
from kmz_route_corrector.route_recreator import recreate_routes_with_stops
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
    <name>Rutas de prueba</name>
    <Folder>
      <name>Rutas</name>
      <Placemark>
        <name>Ruta #1</name>
        <LineString>
          <coordinates>-69.9000,18.5000,0 -69.8950,18.5050,0 -69.9000,18.5100,0</coordinates>
        </LineString>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


def straight_kml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Rutas de prueba</name>
    <Folder>
      <name>Rutas</name>
      <Placemark>
        <name>Ruta recta</name>
        <LineString>
          <coordinates>-69.9000,18.5000,0 -69.9000,18.5050,0 -69.9000,18.5100,0 -69.9000,18.5150,0 -69.9000,18.5200,0</coordinates>
        </LineString>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


def recreated_stop_placemarks(root):
    stops = []
    for placemark in root.findall(f".//{kml_tag('Placemark')}"):
        if point_coordinate(placemark) and name_of(placemark).startswith("P"):
            stops.append(placemark)
    return stops


def test_recreate_routes_generates_bus_stops_excel_and_zip(tmp_path):
    input_path = tmp_path / "rutas.kmz"
    write_kmz(input_path, sample_kml())

    result = recreate_routes_with_stops(
        input_path,
        output_dir=tmp_path,
        simplification_tolerance_meters=30,
        min_stop_distance_meters=150,
    )

    assert result.route_count == 1
    assert result.stops_created == 3
    assert len(result.route_excel_paths) == 1
    assert result.output_kmz_path.name == "rutas_ruta_recreada.kmz"

    root = read_output_kml(result.output_kmz_path)
    folders = [name_of(folder) for folder in root.findall(f".//{kml_tag('Folder')}")]
    assert "Paradas recreadas" in folders

    stops = recreated_stop_placemarks(root)
    assert len(stops) == result.stops_created
    coords = [point_coordinate(stop) for stop in stops]
    for first, second in zip(coords, coords[1:]):
        assert haversine_meters(first[0], first[1], second[0], second[1]) >= 145

    route_stops = read_route_stops(result.route_excel_paths[0])
    assert [stop.station_name for stop in route_stops] == [f"P{index}" for index in range(1, result.stops_created + 1)]

    with result.report_csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == result.stops_created
    assert rows[0]["ruta"] == "Ruta #1"

    with zipfile.ZipFile(result.bundle_zip_path) as archive:
        names = sorted(archive.namelist())
    assert "excel_uffizio/001_Ruta #1.xlsx" in names
    assert "reporte_ruta_recreada.csv" in names
    assert "warnings.log" in names
    assert "rutas_ruta_recreada.kmz" in names


def test_recreate_routes_keeps_only_endpoints_for_straight_route(tmp_path):
    input_path = tmp_path / "recta.kmz"
    write_kmz(input_path, straight_kml())

    result = recreate_routes_with_stops(
        input_path,
        output_dir=tmp_path,
        simplification_tolerance_meters=30,
        min_stop_distance_meters=150,
    )

    assert result.stops_created == 2
    root = read_output_kml(result.output_kmz_path)
    assert [name_of(stop) for stop in recreated_stop_placemarks(root)] == ["P1", "P2"]


def test_recreate_routes_rejects_invalid_distances(tmp_path):
    input_path = tmp_path / "rutas.kmz"
    write_kmz(input_path, sample_kml())

    with pytest.raises(ValueError, match="tolerancia"):
        recreate_routes_with_stops(input_path, output_dir=tmp_path, simplification_tolerance_meters=0)

    with pytest.raises(ValueError, match="distancia minima"):
        recreate_routes_with_stops(input_path, output_dir=tmp_path, min_stop_distance_meters=0)