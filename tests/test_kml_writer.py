import xml.etree.ElementTree as ET

from kmz_route_corrector.kml_parser import kml_tag
from kmz_route_corrector.kml_writer import apply_corrections
from kmz_route_corrector.models import Route, RouteCorrection


def test_empty_correction_removes_previous_corrected_stops_without_adding_empty_folder():
    document = ET.Element(kml_tag("Document"))
    route_folder = ET.SubElement(document, kml_tag("Folder"))
    ET.SubElement(route_folder, kml_tag("name")).text = "Ruta test"
    old_folder = ET.SubElement(route_folder, kml_tag("Folder"))
    ET.SubElement(old_folder, kml_tag("name")).text = "Paradas corregidas"
    old_placemark = ET.SubElement(old_folder, kml_tag("Placemark"))
    ET.SubElement(old_placemark, kml_tag("name")).text = "Pf - CENTRO EDUCATIVO TEST"
    route = Route(
        name="Ruta test",
        container=route_folder,
        document=document,
        line_placemark=None,
        line_coords=[],
        stop_source_nodes=[],
        stop_source_parents=[],
    )

    apply_corrections([RouteCorrection(route=route, ordering_method="sin_paradas", stops=[])])

    folder_names = [node.text for node in route_folder.findall(f"./{kml_tag('Folder')}/{kml_tag('name')}")]
    placemark_names = [node.text for node in route_folder.findall(f".//{kml_tag('Placemark')}/{kml_tag('name')}")]
    assert "Paradas corregidas" not in folder_names
    assert "Pf - CENTRO EDUCATIVO TEST" not in placemark_names
