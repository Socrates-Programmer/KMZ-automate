from io import BytesIO
from types import SimpleNamespace

import web_app


def test_recreate_route_rejects_non_kmz_upload():
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/recreate-route/process",
        data={
            "kmz_file": (BytesIO(b"not a kmz"), "archivo.txt"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Solo se aceptan archivos .kmz" in response.data


def test_recreate_route_process_returns_download_link(monkeypatch, tmp_path):
    captured = {}

    def fake_recreate_routes_with_stops(
        input_path,
        output_dir=None,
        simplification_tolerance_meters=80,
        min_stop_distance_meters=200,
        create_bundle=True,
    ):
        captured["input_path"] = input_path
        captured["output_dir"] = output_dir
        captured["simplification_tolerance_meters"] = simplification_tolerance_meters
        captured["min_stop_distance_meters"] = min_stop_distance_meters
        captured["create_bundle"] = create_bundle
        bundle_path = output_dir / "rutas_ruta_recreada_resultados.zip"
        bundle_path.write_bytes(b"zip")
        return SimpleNamespace(
            route_count=2,
            stops_created=12,
            simplification_tolerance_meters=simplification_tolerance_meters,
            min_stop_distance_meters=min_stop_distance_meters,
            route_excel_paths=[],
            bundle_zip_path=bundle_path,
        )

    monkeypatch.setattr(web_app, "recreate_routes_with_stops", fake_recreate_routes_with_stops)
    monkeypatch.setattr(web_app, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(web_app, "OUTPUT_DIR", tmp_path / "outputs")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/recreate-route/process",
        data={
            "kmz_file": (BytesIO(b"fake kmz"), "rutas.kmz"),
            "simplification_tolerance_meters": "90",
            "min_stop_distance_meters": "250",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Descargar ZIP completo" in response.data
    assert captured["input_path"].name == "rutas.kmz"
    assert captured["simplification_tolerance_meters"] == 90
    assert captured["min_stop_distance_meters"] == 250
    assert captured["create_bundle"] is True