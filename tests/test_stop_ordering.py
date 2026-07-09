from kmz_route_corrector.models import Route, Stop
from kmz_route_corrector.stop_detector import order_stops


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
