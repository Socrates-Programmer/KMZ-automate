from kmz_route_corrector.core import correct_route, prune_generated_duplicate_stops
from kmz_route_corrector.geometry import haversine_meters
from kmz_route_corrector.models import CorrectedStop, Route, School, SchoolMatch, Stop


def make_stop(name, lon, lat, index):
    return Stop(name=name, lon=lon, lat=lat, alt=None, element=None, parent=None, original_index=index, source="test")


def make_corrected_stop(name, tipo, lon, lat, original_name=None, original_lon=None, original_lat=None):
    return CorrectedStop(
        route_name="Ruta test",
        original_name=original_name or name,
        new_name=name,
        tipo=tipo,
        original_lon=lon if original_lon is None else original_lon,
        original_lat=lat if original_lat is None else original_lat,
        new_lon=lon,
        new_lat=lat,
        offset_meters=10,
    )


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
    assert not any(irregularity.kind == "removed_stop" for irregularity in correction.irregularities)


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


def test_successive_stops_within_85_meters_by_route_flow_are_consolidated():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.198, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P45", -69.2, 18.0, 0),
            make_stop("P9", -69.19935, 18.0, 1),
            make_stop("P46", -69.198, 18.0, 2),
        ],
    )

    correction = correct_route(route, [], 10, 400)

    assert [stop.original_name for stop in correction.stops] == ["P45", "P46", "P46", "P45"]
    assert [stop.tipo for stop in correction.stops] == ["ida", "ida", "regreso", "regreso"]
    assert any("P9 se unio a P45" in warning for warning in correction.warnings)


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


def test_school_near_route_without_nearby_stop_is_reported():
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
    schools = [School(name="ESCUELA PRIMARIA TEST", lon=-69.195, lat=18.0)]

    correction = correct_route(route, schools, 10, 400)

    assert any(irregularity.kind == "school_without_nearby_stop" for irregularity in correction.irregularities)
    irregularity = next(item for item in correction.irregularities if item.kind == "school_without_nearby_stop")
    assert irregularity.title == "Centro educativo sin parada cercana"
    assert "ESCUELA PRIMARIA TEST" in irregularity.description


def test_school_near_route_with_nearby_stop_is_not_reported():
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
    schools = [School(name="ESCUELA PRIMARIA TEST", lon=-69.2001, lat=18.0)]

    correction = correct_route(route, schools, 10, 400)

    assert not any(irregularity.kind == "school_without_nearby_stop" for irregularity in correction.irregularities)


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


def test_route_gap_uses_corrected_successive_labels_not_old_stop_names():
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
            make_stop("P3", -69.198, 18.0, 2),
            make_stop("P4", -69.197, 18.0, 3),
            make_stop("P5", -69.196, 18.0, 4),
            make_stop("P6", -69.195, 18.0, 5),
            make_stop("P7", -69.194, 18.0, 6),
            make_stop("P10", -69.17, 18.0, 7),
        ],
    )

    correction = correct_route(route, [], 10, 100)

    gap_descriptions = [irregularity.description for irregularity in correction.irregularities if irregularity.kind == "route_gap"]
    assert any("entre P7 y P8" in description for description in gap_descriptions)
    assert not any("P10" in description for description in gap_descriptions)


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


def test_school_farther_than_400_meters_is_not_assigned():
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
    schools = [School(name="CENTRO EDUCATIVO LEJANO", lon=-69.195, lat=18.0)]

    correction = correct_route(route, schools, 8, 400)

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

    correction = correct_route(route, [], 10, 400, external_school_lookup=fake_lookup)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - ESCUELA BASICA EMI LOS JIBAROS",
        "P2 - ESCUELA BASICA EMI LOS JIBAROS",
    ]
    assert len(correction.stops) == 2
    assert correction.stops[0].school_source == "Google Places"
    assert any("Google Places" in warning for warning in correction.stops[0].warnings)


def test_external_school_lookup_refines_generic_kmz_school_name():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-70.3462, 19.4599, None), (-70.3458, 19.4599, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[make_stop("P1", -70.3460, 19.4599, 0)],
    )
    schools = [School(name="JUAN ANDRES VASQUEZ RODRIGUEZ", lon=-70.3460, lat=19.4599, source="KMZ")]

    def fake_lookup(lon, lat, radius_meters):
        return SchoolMatch(
            school=School(
                name="ESCUELA PRIMARIA JUAN ANDRES VASQUEZ GARCIA",
                lon=lon,
                lat=lat,
                source="Google Places",
            ),
            distance_meters=1.0,
        )

    correction = correct_route(route, schools, 10, 400, external_school_lookup=fake_lookup)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - ESCUELA PRIMARIA JUAN ANDRES VASQUEZ GARCIA",
        "P2 - ESCUELA PRIMARIA JUAN ANDRES VASQUEZ GARCIA",
    ]
    assert all(stop.school_source == "Google Places" for stop in correction.stops)
    assert any("refinado desde Google Places" in warning for warning in correction.warnings)


def test_external_school_lookup_is_not_used_when_kmz_school_is_assignable():
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
    schools = [School(name="ESCUELA DEL KMZ", lon=-70.280968, lat=18.522499, source="KMZ")]
    calls = {"count": 0}

    def fake_lookup(lon, lat, radius_meters):
        calls["count"] += 1
        return SchoolMatch(
            school=School(
                name="ESCUELA ONLINE",
                lon=lon,
                lat=lat,
                source="Google Places",
            ),
            distance_meters=1.0,
        )

    correction = correct_route(route, schools, 10, 400, external_school_lookup=fake_lookup)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - ESCUELA DEL KMZ",
        "P2 - ESCUELA DEL KMZ",
    ]
    assert calls["count"] == 0


def test_external_school_lookup_completes_unlabeled_stops_without_replacing_kmz_labels():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-70.30, 18.52, None), (-70.28, 18.52, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P1", -70.3000, 18.5200, 0),
            make_stop("P2", -70.2800, 18.5200, 1),
        ],
    )
    schools = [School(name="ESCUELA DEL KMZ", lon=-70.3000, lat=18.5200, source="KMZ")]

    def fake_lookup(lon, lat, radius_meters):
        return SchoolMatch(
            school=School(
                name="ESCUELA BASICA RURAL PALMA SOLA",
                lon=lon,
                lat=lat,
                source="Google Places",
            ),
            distance_meters=1.0,
        )

    correction = correct_route(route, schools, 10, 400, external_school_lookup=fake_lookup)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - ESCUELA DEL KMZ",
        "P2 - ESCUELA BASICA RURAL PALMA SOLA",
        "P3 - ESCUELA BASICA RURAL PALMA SOLA",
        "P4 - ESCUELA DEL KMZ",
    ]
    assert correction.stops[0].school_source == "KMZ"
    assert correction.stops[1].school_source == "Google Places"


def test_school_labels_only_nearest_outbound_and_return_stop():
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
            make_stop("P2", -69.197, 18.0, 1),
        ],
    )
    schools = [School(name="CENTRO EDUCATIVO TEST", lon=-69.197, lat=18.0)]

    correction = correct_route(route, schools, 8, 400)

    assert [stop.new_name for stop in correction.stops] == [
        "P1",
        "P2 - CENTRO EDUCATIVO TEST",
        "P3 - CENTRO EDUCATIVO TEST",
        "P4",
    ]


def test_same_school_does_not_label_more_than_one_outbound_and_one_return_stop():
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

    correction = correct_route(route, schools, 8, 400)

    assert sum("CENTRO EDUCATIVO TEST" in stop.new_name for stop in correction.stops) == 2
    assert sum("CENTRO EDUCATIVO TEST" in stop.new_name for stop in correction.stops if stop.tipo == "ida") == 1
    assert sum("CENTRO EDUCATIVO TEST" in stop.new_name for stop in correction.stops if stop.tipo == "regreso") == 1


def test_duplicate_stop_pair_near_same_school_is_pruned_to_one_outbound_and_one_return():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.19, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        stops=[
            make_stop("P20 vieja", -69.2, 18.0, 0),
            make_stop("P21 vieja", -69.1986, 18.0, 1),
        ],
    )
    schools = [School(name="CENTRO EDUCATIVO CANTA RANA", lon=-69.2, lat=18.0)]

    correction = correct_route(route, schools, 10, 400)

    assert [stop.new_name for stop in correction.stops] == [
        "P1 - CENTRO EDUCATIVO CANTA RANA",
        "P2 - CENTRO EDUCATIVO CANTA RANA",
    ]
    assert [stop.tipo for stop in correction.stops] == ["ida", "regreso"]
    assert any(irregularity.kind == "school_cluster_duplicate_stop" for irregularity in correction.irregularities)


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

    correction = correct_route(route, schools, 8, 400)

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


def test_generated_parallel_duplicates_in_same_direction_are_omitted_and_renumbered():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="09-01",
    )
    corrected = [
        make_corrected_stop("P1", "ida", -69.2, 18.0),
        make_corrected_stop("P2", "ida", -69.19, 18.0),
        make_corrected_stop("P3", "regreso", -69.18, 18.0),
        make_corrected_stop("P4", "regreso", -69.1799, 18.0),
        make_corrected_stop("P5", "regreso", -69.17, 18.0),
    ]

    kept, warnings, irregularities = prune_generated_duplicate_stops(route, corrected)

    assert [stop.new_name for stop in kept] == ["P1", "P2", "P3", "P4"]
    assert [stop.original_name for stop in kept] == ["P1", "P2", "P3", "P5"]
    assert any("ida/vuelta paralela" in warning for warning in warnings)
    assert any(irregularity.kind == "generated_duplicate_stop" for irregularity in irregularities)


def test_generated_duplicate_cleanup_removes_its_return_pair():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="09-01",
    )
    corrected = [
        make_corrected_stop("P1", "ida", -69.2, 18.0, original_name="A", original_lon=-69.2, original_lat=18.0),
        make_corrected_stop("P2", "ida", -69.1999, 18.0, original_name="B", original_lon=-69.199, original_lat=18.0),
        make_corrected_stop("P3", "regreso", -69.18, 18.0, original_name="B", original_lon=-69.199, original_lat=18.0),
        make_corrected_stop("P4", "regreso", -69.17, 18.0, original_name="A", original_lon=-69.2, original_lat=18.0),
    ]

    kept, warnings, irregularities = prune_generated_duplicate_stops(route, corrected)

    assert [stop.original_name for stop in kept] == ["A", "A"]
    assert [stop.tipo for stop in kept] == ["ida", "regreso"]
    assert [stop.new_name for stop in kept] == ["P1", "P2"]
    assert any("duplicada omitida" in warning for warning in warnings)
    assert any(irregularity.kind == "generated_duplicate_stop" for irregularity in irregularities)


def test_generated_route_overlap_duplicates_are_omitted_even_when_not_consecutive():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
        district_name="09-01",
    )
    corrected = [
        make_corrected_stop("P1", "ida", -69.2, 18.0),
        make_corrected_stop("P2", "ida", -69.18, 18.0),
        make_corrected_stop("P3", "ida", -69.1994, 18.0),
        make_corrected_stop("P4", "regreso", -69.17, 18.0),
        make_corrected_stop("P5", "regreso", -69.16, 18.0),
        make_corrected_stop("P6", "regreso", -69.1694, 18.0),
    ]

    kept, warnings, irregularities = prune_generated_duplicate_stops(route, corrected)

    assert [stop.original_name for stop in kept] == ["P1", "P2", "P4", "P5"]
    assert [stop.new_name for stop in kept] == ["P1", "P2", "P3", "P4"]
    assert sum(1 for warning in warnings if "mismo lugar" in warning) == 2
    assert sum(1 for irregularity in irregularities if irregularity.kind == "generated_duplicate_stop") == 2


def test_generated_parallel_cleanup_keeps_opposite_direction_pair():
    route = Route(
        name="Ruta test",
        container=None,
        document=None,
        line_placemark=None,
        line_coords=[(-69.2, 18.0, None), (-69.0, 18.0, None)],
        stop_source_nodes=[],
        stop_source_parents=[],
    )
    corrected = [
        make_corrected_stop("P1", "ida", -69.2, 18.0),
        make_corrected_stop("P2", "regreso", -69.2, 18.0),
    ]

    kept, warnings, irregularities = prune_generated_duplicate_stops(route, corrected)

    assert [stop.new_name for stop in kept] == ["P1", "P2"]
    assert warnings == []
    assert irregularities == []
