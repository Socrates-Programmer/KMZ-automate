import json

from kmz_route_corrector.osm_overpass import OpenStreetMapSchoolLookup, overpass_query, school_from_osm_element


def test_school_from_osm_node_preserves_name_without_hint():
    school = school_from_osm_element(
        {
            "type": "node",
            "lat": 18.52255,
            "lon": -70.28095,
            "tags": {"amenity": "school", "name": "EMI Los Jibaros"},
        }
    )

    assert school is not None
    assert school.name == "EMI LOS JIBAROS"
    assert school.source == "OpenStreetMap"


def test_school_from_osm_way_uses_center_coordinates():
    school = school_from_osm_element(
        {
            "type": "way",
            "center": {"lat": 18.52255, "lon": -70.28095},
            "tags": {"amenity": "school", "name": "Escuela Basica EMI Los Jibaros"},
        }
    )

    assert school is not None
    assert school.name == "ESCUELA BASICA EMI LOS JIBAROS"
    assert school.lat == 18.52255
    assert school.lon == -70.28095


def test_overpass_query_uses_radius_and_school_filters():
    query = overpass_query(-70.280968, 18.522499, 100)

    assert "around:100.0,18.52249900,-70.28096800" in query
    assert "amenity" in query
    assert "name" in query
    assert "escuela" in query
    assert "liceo" in query
    assert "instituto" in query
    assert "colegio" not in query


def test_school_from_osm_ignores_colegio_name():
    school = school_from_osm_element(
        {
            "type": "node",
            "lat": 18.52255,
            "lon": -70.28095,
            "tags": {"amenity": "school", "name": "Colegio Los Jibaros"},
        }
    )

    assert school is None


def test_openstreetmap_lookup_selects_nearest_school(monkeypatch):
    payload = {
        "elements": [
            {
                "type": "node",
                "lat": 18.5238,
                "lon": -70.2825,
                "tags": {"amenity": "school", "name": "Escuela Lejana"},
            },
            {
                "type": "node",
                "lat": 18.52255,
                "lon": -70.28095,
                "tags": {"amenity": "school", "name": "Escuela Basica EMI Los Jibaros"},
            },
        ]
    }

    def fake_urlopen(request, timeout):
        return FakeResponse(payload)

    monkeypatch.setattr("kmz_route_corrector.osm_overpass.urlopen", fake_urlopen)

    lookup = OpenStreetMapSchoolLookup()
    match = lookup.match_school(-70.280968, 18.522499, 100)

    assert match.school is not None
    assert match.school.name == "ESCUELA BASICA EMI LOS JIBAROS"
    assert match.school.source == "OpenStreetMap"
    assert match.distance_meters is not None
    assert match.distance_meters < 10


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")
