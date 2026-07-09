import zipfile
import xml.etree.ElementTree as ET

from kmz_route_corrector.kmz_io import read_kmz, write_kmz
from kmz_route_corrector.kml_parser import kml_tag


def test_read_and_write_kmz(tmp_path):
    input_path = tmp_path / "sample.kmz"
    kml = b'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>x</name></Document></kml>'
    with zipfile.ZipFile(input_path, "w") as archive:
        archive.writestr("doc.kml", kml)
        archive.writestr("files/icon.png", b"fake")

    package = read_kmz(input_path)
    assert package.primary_kml_name == "doc.kml"

    document = package.root.find(kml_tag("Document"))
    ET.SubElement(document, kml_tag("name")).text = "edited"
    output_path = tmp_path / "out.kmz"
    write_kmz(package.root, output_path, package.primary_kml_name, package.original_entries)

    with zipfile.ZipFile(output_path) as archive:
        assert "doc.kml" in archive.namelist()
        assert "files/icon.png" in archive.namelist()
