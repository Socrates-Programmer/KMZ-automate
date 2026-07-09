import pytest

from kmz_route_corrector.core import validate_options


def test_offset_meters_must_be_at_least_10(tmp_path):
    kmz_path = tmp_path / "ruta.kmz"
    kmz_path.write_bytes(b"fake")

    with pytest.raises(ValueError, match="mayor o igual a 10"):
        validate_options(kmz_path, 8, 100)


def test_offset_meters_accepts_10(tmp_path):
    kmz_path = tmp_path / "ruta.kmz"
    kmz_path.write_bytes(b"fake")

    validate_options(kmz_path, 10, 100)
