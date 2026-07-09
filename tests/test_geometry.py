from kmz_route_corrector.geometry import haversine_meters, offset_left_of_route, orient_line_for_stop_sequence, place_stop_on_route_side
from kmz_route_corrector.models import Stop


def make_stop(name, lon, lat, index):
    return Stop(name=name, lon=lon, lat=lat, alt=None, element=None, parent=None, original_index=index, source="test")


def test_return_stop_is_mirrored_to_left_side_of_route_line():
    line = [(-69.0, 18.0, None), (-68.99, 18.0, None)]
    stops = [make_stop("P1", -68.995, 17.9998, 0)]

    new_lon, new_lat, warnings = offset_left_of_route(
        stops[0].lon,
        stops[0].lat,
        line,
        stops,
        0,
        10,
    )

    assert warnings == []
    assert new_lat > 18.0
    assert abs(new_lon - stops[0].lon) < 0.0001
    assert 8 <= haversine_meters(new_lon, new_lat, new_lon, 18.0) <= 12


def test_outbound_stop_is_placed_on_right_side_of_route_line():
    line = [(-69.0, 18.0, None), (-68.99, 18.0, None)]
    stops = [make_stop("P1", -68.995, 18.0002, 0)]

    new_lon, new_lat, warnings = place_stop_on_route_side(
        stops[0].lon,
        stops[0].lat,
        line,
        stops,
        0,
        10,
        "right",
    )

    assert warnings == []
    assert new_lat < 18.0
    assert abs(new_lon - stops[0].lon) < 0.0001
    assert 8 <= haversine_meters(new_lon, new_lat, new_lon, 18.0) <= 12


def test_stop_far_from_route_line_is_pulled_to_configured_offset():
    line = [(-69.0, 18.0, None), (-68.99, 18.0, None)]
    stops = [make_stop("P1", -68.995, 18.001, 0)]

    new_lon, new_lat, warnings = place_stop_on_route_side(
        stops[0].lon,
        stops[0].lat,
        line,
        stops,
        0,
        10,
        "right",
    )

    assert warnings == []
    assert new_lat < 18.0
    assert 8 <= haversine_meters(new_lon, new_lat, new_lon, 18.0) <= 12


def test_line_is_oriented_by_ordered_stop_sequence():
    reversed_line = [(-68.99, 18.0, None), (-69.0, 18.0, None)]
    stops = [
        make_stop("P1", -69.0, 18.0, 0),
        make_stop("P2", -68.99, 18.0, 1),
    ]

    oriented = orient_line_for_stop_sequence(reversed_line, stops)

    assert oriented[0][0] == -69.0
    assert oriented[-1][0] == -68.99
