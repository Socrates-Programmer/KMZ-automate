import json
from datetime import datetime, timezone

from kmz_route_corrector.google_places import GooglePlacesSchoolLookup, school_from_place


def test_school_from_place_prefixes_school_type_name_without_hint():
    school = school_from_place(
        {
            "displayName": {"text": "EMI Los Jibaros"},
            "location": {"latitude": 18.5221, "longitude": -70.2809},
            "types": ["school"],
        }
    )

    assert school is not None
    assert school.name == "CENTRO EDUCATIVO EMI LOS JIBAROS"
    assert school.source == "Google Places"


def test_google_places_lookup_selects_nearest_school(monkeypatch):
    payload = {
        "places": [
            {
                "displayName": {"text": "Escuela Lejana"},
                "location": {"latitude": 18.5238, "longitude": -70.2825},
                "types": ["school"],
            },
            {
                "displayName": {"text": "Escuela Basica EMI Los Jibaros"},
                "location": {"latitude": 18.52255, "longitude": -70.28095},
                "types": ["school"],
            },
        ]
    }

    def fake_urlopen(request, timeout):
        return FakeResponse(payload)

    monkeypatch.setattr("kmz_route_corrector.google_places.urlopen", fake_urlopen)

    lookup = GooglePlacesSchoolLookup("test-key")
    match = lookup.match_school(-70.280968, 18.522499, 100)

    assert match.school is not None
    assert match.school.name == "ESCUELA BASICA EMI LOS JIBAROS"
    assert match.distance_meters is not None
    assert match.distance_meters < 10


def test_google_places_lookup_respects_monthly_limit(monkeypatch, tmp_path):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        return FakeResponse({"places": []})

    monkeypatch.setattr("kmz_route_corrector.google_places.urlopen", fake_urlopen)

    usage_file = tmp_path / "google_places_usage.json"
    lookup = GooglePlacesSchoolLookup("test-key", monthly_limit=1, usage_file=usage_file)

    first = lookup.match_school(-70.280968, 18.522499, 100)
    second = lookup.match_school(-70.2815, 18.5229, 100)

    assert first.school is None
    assert second.school is None
    assert calls["count"] == 1
    assert any("limite mensual local de 1 requests" in warning for warning in lookup.warnings)
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    assert json.loads(usage_file.read_text(encoding="utf-8")) == {month_key: 1}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")
