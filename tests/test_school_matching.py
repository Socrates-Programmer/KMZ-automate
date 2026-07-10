import xml.etree.ElementTree as ET

from kmz_route_corrector.kml_parser import kml_tag
from kmz_route_corrector.school_detector import clean_school_name, detect_schools, full_school_name, match_school
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


def test_detect_schools_uses_visible_escuela_name_outside_school_folder():
    root = kml_with_point("Escuela Basica EMI Los Jibaros")

    schools, warnings = detect_schools(root)

    assert warnings == []
    assert [school.name for school in schools] == ["ESCUELA BASICA EMI LOS JIBAROS"]


def test_detect_schools_uses_visible_liceo_name_outside_school_folder():
    root = kml_with_point("Liceo Leonor Isabel Cabrera Reyes")

    schools, warnings = detect_schools(root)

    assert warnings == []
    assert [school.name for school in schools] == ["LICEO LEONOR ISABEL CABRERA REYES"]


def test_detect_schools_uses_plural_centros_educativos_folder():
    root = kml_with_point("Los Jibaros", folder_name="Centros educativos")

    schools, warnings = detect_schools(root)

    assert warnings == []
    assert [school.name for school in schools] == ["CENTRO EDUCATIVO LOS JIBAROS"]


def kml_with_point(name: str, folder_name: str = "") -> ET.Element:
    root = ET.Element(kml_tag("kml"))
    document = ET.SubElement(root, kml_tag("Document"))
    parent = document
    if folder_name:
        parent = ET.SubElement(document, kml_tag("Folder"))
        ET.SubElement(parent, kml_tag("name")).text = folder_name
    placemark = ET.SubElement(parent, kml_tag("Placemark"))
    ET.SubElement(placemark, kml_tag("name")).text = name
    point = ET.SubElement(placemark, kml_tag("Point"))
    ET.SubElement(point, kml_tag("coordinates")).text = "-69.0,18.0,0"
    return root
