from io import BytesIO
from types import SimpleNamespace

import web_app


def test_arrow_stops_rejects_non_kmz_upload():
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/arrow-stops/process",
        data={
            "kmz_file": (BytesIO(b"not a kmz"), "archivo.txt"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Solo se aceptan archivos .kmz" in response.data


def test_arrow_stops_process_returns_download_link(monkeypatch, tmp_path):
    captured = {}

    def fake_convert_arrow_points_to_bus_stops(input_path, output_dir=None, route_match_radius_meters=2000, create_bundle=True):
        captured["input_path"] = input_path
        captured["output_dir"] = output_dir
        captured["route_match_radius_meters"] = route_match_radius_meters
        captured["create_bundle"] = create_bundle
        bundle_path = output_dir / "juegos_paradas_bus_resultados.zip"
        bundle_path.write_bytes(b"zip")
        return SimpleNamespace(
            converted_count=56,
            point_count=57,
            route_count=41,
            route_match_radius_meters=route_match_radius_meters,
            bundle_zip_path=bundle_path,
            route_excel_paths=[],
        )

    monkeypatch.setattr(web_app, "convert_arrow_points_to_bus_stops", fake_convert_arrow_points_to_bus_stops)
    monkeypatch.setattr(web_app, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(web_app, "OUTPUT_DIR", tmp_path / "outputs")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/arrow-stops/process",
        data={
            "kmz_file": (BytesIO(b"fake kmz"), "Rutas Juegos.kmz"),
            "route_match_radius_meters": "2500",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Descargar ZIP completo" in response.data
    assert captured["input_path"].name == "Rutas Juegos.kmz"
    assert captured["route_match_radius_meters"] == 2500
    assert captured["create_bundle"] is True
