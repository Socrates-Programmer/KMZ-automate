from kmz_route_corrector.school_detector import clean_school_name, full_school_name, match_school
from kmz_route_corrector.models import School


def test_clean_school_name_removes_code_and_uppercases():
    assert clean_school_name("01391 - Aleman") == "ALEMAN"


def test_full_school_name_prefers_visible_school_name():
    name, _ = full_school_name("Escuela Basica km. 14 de Cumayasa", {"Centro educativo": "123 - KILOMETRO 14"})

    assert name == "ESCUELA BASICA KM. 14 DE CUMAYASA"


def test_full_school_name_adds_centro_educativo_when_missing_keyword():
    name, _ = full_school_name("", {"Centro educativo": "123 - KILOMETRO 14"})

    assert name == "CENTRO EDUCATIVO KILOMETRO 14"


def test_match_school_selects_nearest():
    schools = [
        School(name="LEJANA", lon=-69.5, lat=18.5),
        School(name="CERCANA", lon=-69.0001, lat=18.0001),
    ]

    match = match_school(-69.0, 18.0, schools, 80)

    assert match.school is not None
    assert match.school.name == "CERCANA"
    assert match.distance_meters is not None
