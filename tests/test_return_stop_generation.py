from kmz_route_corrector.core import correct_route
from kmz_route_corrector.geometry import haversine_meters
from kmz_route_corrector.models import Route, School, SchoolMatch, Stop


def make_stop(name, lon, lat, index):
    return Stop(name=name, lon=lon, lat=lat, alt=None, element=None, parent=None, original_index=index, source="test")


def test_generates_outbound_and_return_stop_per_original_stop():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -69.2, 18.0, 0),
            make_stop("P2", -69.1, 18.0, 1),
            make_stop("P3", -69.0, 18.0, 2),
        ],
    )

    correction = correct_route(route, [], 8, 80)

    assert [stop.new_name for stop in correction.stops] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert [stop.tipo for stop in correction.stops] == ["ida", "ida", "ida", "regreso", "regreso", "regreso"]
    assert all(stop.is_pf is False for stop in correction.stops)


def test_return_stops_inherit_school_name_from_adjacent_outbound_stop():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -69.2, 18.0, 0),
            make_stop("P2", -69.1, 18.0, 1),
        ],
    )
    schools = [
        School(name="ESCUELA TEST", lon=-69.2, lat=18.0),
        School(name="OTRA ESCUELA", lon=-69.1, lat=18.0),
    ]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - ESCUELA TEST",
        "P2 - OTRA ESCUELA",
        "P3 - OTRA ESCUELA",
        "P4 - ESCUELA TEST",
    ]


def test_close_stops_by_same_school_are_consolidated_before_numbering():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1 vieja", -69.2, 18.0, 0),
            make_stop("P2 vieja", -69.1997, 18.0, 1),
            make_stop("P3 vieja", -69.19, 18.0, 2),
        ],
    )
    schools = [School(name="CENTRO EDUCATIVO TEST", lon=-69.2, lat=18.0)]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - CENTRO EDUCATIVO TEST",
        "P2",
        "P3",
        "P4 - CENTRO EDUCATIVO TEST",
    ]
    assert any("Parada duplicada consolidada" in warning for warning in correction.warnings)


def test_very_close_successive_stops_are_consolidated_even_without_school():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1 vieja", -69.2, 18.0, 0),
            make_stop("P2 vieja", -69.1998, 18.0, 1),
            make_stop("P3 vieja", -69.19, 18.0, 2),
        ],
    )

    correction = correct_route(route, [], 8, 100)

    assert [stop.new_name for stop in correction.stops] == ["P1", "P2", "P3", "P4"]


def test_removed_stop_farther_than_150_meters_from_route_is_reported():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1 vieja", -69.2, 18.01, 0),
            make_stop("P2 vieja", -69.1999, 18.01, 1),
        ],
    )

    correction = correct_route(route, [], 10, 100)

    assert any(irregularity.kind == "removed_far_stop" for irregularity in correction.irregularities)
    assert correction.irregularities[0].distance_meters > 150


def test_long_route_gap_without_stops_is_reported():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -69.2, 18.0, 0),
            make_stop("P2", -69.19, 18.0, 1),
        ],
    )

    correction = correct_route(route, [], 10, 100)

    assert any(irregularity.kind == "route_gap" for irregularity in correction.irregularities)


def test_close_successive_stops_are_consolidated_even_with_different_nearby_schools():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P8 vieja", -69.2, 18.0, 0),
            make_stop("P9 vieja", -69.1995, 18.0, 1),
            make_stop("P10 vieja", -69.19, 18.0, 2),
        ],
    )
    schools = [
        School(name="CENTRO EDUCATIVO A", lon=-69.2, lat=18.0),
        School(name="CENTRO EDUCATIVO B", lon=-69.1995, lat=18.0),
    ]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - CENTRO EDUCATIVO A",
        "P2",
        "P3",
        "P4 - CENTRO EDUCATIVO A",
    ]


def test_school_farther_than_100_meters_is_not_assigned():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[make_stop("P1", -69.2, 18.0, 0)],
    )
    schools = [School(name="CENTRO EDUCATIVO LEJANO", lon=-69.1988, lat=18.0)]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == ["P1", "P2"]


def test_external_school_lookup_is_used_when_kmz_has_no_nearby_school():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-70.281, 18.5225, None), (-70.280, 18.5225, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[make_stop("P28", -70.280968, 18.522499, 0)],
    )

    def fake_lookup(lon, lat, radius_meters):
        return SchoolMatch(
            school=School(
                name="ESCUELA BASICA EMI LOS JIBAROS",
                lon=lon - 0.0003,
                lat=lat,
                source="Google Places",
            ),
            distance_meters=55.0,
        )

    correction = correct_route(route, [], 10, 100, external_school_lookup=fake_lookup)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - ESCUELA BASICA EMI LOS JIBAROS",
        "P2 - ESCUELA BASICA EMI LOS JIBAROS",
    ]
    assert correction.stops[0].school_source == "Google Places"
    assert any("Google Places" in warning for warning in correction.stops[0].warnings)


def test_repeated_school_label_within_150_meters_is_omitted_on_outbound_stop():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -69.2, 18.0, 0),
            make_stop("P2", -69.199, 18.0, 1),
        ],
    )
    schools = [School(name="CENTRO EDUCATIVO TEST", lon=-69.1995, lat=18.0)]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - CENTRO EDUCATIVO TEST",
        "P2",
        "P3",
        "P4 - CENTRO EDUCATIVO TEST",
    ]
    assert any("Nombre de centro educativo omitido" in warning for warning in correction.stops[1].warnings)


def test_repeated_school_label_farther_than_150_meters_is_allowed_on_outbound_stop():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -69.2, 18.0, 0),
            make_stop("P2", -69.1983, 18.0, 1),
        ],
    )
    schools = [School(name="CENTRO EDUCATIVO TEST", lon=-69.19915, lat=18.0)]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - CENTRO EDUCATIVO TEST",
        "P2 - CENTRO EDUCATIVO TEST",
        "P3 - CENTRO EDUCATIVO TEST",
        "P4 - CENTRO EDUCATIVO TEST",
    ]


def test_different_school_label_within_150_meters_is_allowed_on_outbound_stop():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -69.2, 18.0, 0),
            make_stop("P2", -69.199, 18.0, 1),
        ],
    )
    schools = [
        School(name="CENTRO EDUCATIVO A", lon=-69.2, lat=18.0),
        School(name="CENTRO EDUCATIVO B", lon=-69.199, lat=18.0),
    ]

    correction = correct_route(route, schools, 8, 100)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - CENTRO EDUCATIVO A",
        "P2 - CENTRO EDUCATIVO B",
        "P3 - CENTRO EDUCATIVO B",
        "P4 - CENTRO EDUCATIVO A",
    ]


def test_return_sequence_places_last_number_next_to_first_outbound_stop():
    stops = [make_stop(f"P{idx}", -69.2 + (idx - 1) * 0.0012, 18.0, idx - 1) for idx in range(1, 12)]
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.188, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=stops,
    )

    correction = correct_route(route, [], 8, 100)

    assert len(correction.stops) == 22
    assert correction.stops[0].new_name == "P1"
    assert correction.stops[10].new_name == "P11"
    assert correction.stops[11].new_name == "P12"
    assert correction.stops[21].new_name == "P22"
    assert correction.stops[11].tipo == "regreso"
    assert correction.stops[21].tipo == "regreso"
    assert haversine_meters(
        correction.stops[0].new_lon,
        correction.stops[0].new_lat,
        correction.stops[21].new_lon,
        correction.stops[21].new_lat,
    ) <= 25
