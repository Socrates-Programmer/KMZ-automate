import xml.etree.ElementTree as ET

from kmz_route_corrector.kml_parser import kml_tag
from kmz_route_corrector.models import Route, Stop
from kmz_route_corrector.stop_detector import extract_stops_from_route, order_stops


def make_stop(name, lon, lat, index):
    return Stop(name=name, lon=lon, lat=lat, alt=None, element=None, parent=None, original_index=index, source="test")


def make_route(stops, line_coords=None):
    return Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=line_coords or [],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=stops,
    )


def test_orders_by_p_number():
    route = make_route([
        make_stop("P3", -69.0, 18.0, 0),
        make_stop("P1", -69.2, 18.0, 1),
        make_stop("P2", -69.1, 18.0, 2),
    ])

    stops, method, warnings = order_stops(route)

    assert [stop.name for stop in stops] == ["P1", "P2", "P3"]
    assert method == "p_numero"
    assert warnings == []


def test_orders_by_line_when_names_are_not_p_numbers():
    route = make_route(
        [
            make_stop("B", -69.0, 18.0, 0),
            make_stop("A", -69.2, 18.0, 1),
        ],
        [(-69.2, 18.0, None), (-69.0, 18.0, None)],
    )

    stops, method, _ = order_stops(route)

    assert [stop.name for stop in stops] == ["A", "B"]
    assert method == "linea"


def test_line_order_has_priority_over_p_numbers_when_line_exists():
    route = make_route(
        [
            make_stop("P1", -69.0, 18.0, 0),
            make_stop("P2", -69.2, 18.0, 1),
        ],
        [(-69.2, 18.0, None), (-69.0, 18.0, None)],
    )

    stops, method, _ = order_stops(route)

    assert [stop.name for stop in stops] == ["P2", "P1"]
    assert method == "linea"


def test_keeps_kml_order_without_line_or_p_numbers():
    route = make_route([
        make_stop("Sector A", -69.0, 18.0, 0),
        make_stop("Sector B", -69.1, 18.0, 1),
    ])

    stops, method, warnings = order_stops(route)

    assert [stop.name for stop in stops] == ["Sector A", "Sector B"]
    assert method == "orden_kml"
    assert warnings


def test_extract_stops_ignores_direct_school_point():
    school = make_point_placemark("Centro Educativo Canta Rana")
    stop = make_point_placemark("P20")
    route = make_extract_route([school, stop])

    stops = extract_stops_from_route(route)

    assert [stop.name for stop in stops] == ["P20"]


def test_extract_stops_keeps_named_stop_with_school_label():
    route = make_extract_route([make_point_placemark("P20 - Centro Educativo Canta Rana")])

    stops = extract_stops_from_route(route)

    assert [stop.name for stop in stops] == ["P20 - Centro Educativo Canta Rana"]


def test_extract_stops_keeps_school_like_name_inside_paradas_folder():
    folder = make_folder("Paradas")
    folder.append(make_point_placemark("Centro Educativo Canta Rana"))
    route = make_extract_route([folder])

    stops = extract_stops_from_route(route)

    assert [stop.name for stop in stops] == ["Centro Educativo Canta Rana"]


def make_extract_route(source_nodes):
    return Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[],
        stop_source_nodes=source_nodes,
        stop_source_parents=[],
        stops=[],
    )


def make_folder(name):
    folder = ET.Element(kml_tag("Folder"))
    ET.SubElement(folder, kml_tag("name")).text = name
    return folder


def make_point_placemark(name):
    placemark = ET.Element(kml_tag("Placemark"))
    ET.SubElement(placemark, kml_tag("name")).text = name
    point = ET.SubElement(placemark, kml_tag("Point"))
    ET.SubElement(point, kml_tag("coordinates")).text = "-69.0,18.0,0"
    return placemark
