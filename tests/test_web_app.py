from io import BytesIO
from types import SimpleNamespace

import web_app
from kmz_route_corrector.report import ROUTE_EXCEL_TEMPLATE_STOPS


def fake_process_result():
    return SimpleNamespace(
        summary=SimpleNamespace(
            routes_processed=0,
            original_stops_detected=0,
            new_stops_created=0,
            schools_detected=0,
            stops_with_school=0,
            irregularities_count=0,
            warnings_count=0,
        ),
        route_excel_paths=[],
        route_flow_csv_path=None,
        irregularities_report_pdf_path=None,
    )


def test_rejects_non_kmz_upload():
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/process",
        data={
            "kmz_file": (BytesIO(b"not a kmz"), "archivo.txt"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Solo se aceptan archivos .kmz" in response.data


def test_process_upload_forces_stop_route_template(monkeypatch, tmp_path):
    captured = {}

    def fake_process_kmz(*args, **kwargs):
        captured.update(kwargs)
        return fake_process_result()

    monkeypatch.setattr(web_app, "process_kmz", fake_process_kmz)
    monkeypatch.setattr(web_app, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(web_app, "OUTPUT_DIR", tmp_path / "outputs")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/process",
        data={
            "kmz_file": (BytesIO(b"fake kmz"), "ruta.kmz"),
            "route_excel_template": "bulk_create_trip",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["route_excel_template"] == ROUTE_EXCEL_TEMPLATE_STOPS
    assert "bulk_trip_type" not in captured


def test_uffizio_rejects_non_xlsx_upload():
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/uffizio/create",
        data={
            "route_excel_file": (BytesIO(b"not excel"), "ruta.csv"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Solo se aceptan archivos .xlsx" in response.data


def test_uffizio_create_returns_download_link(monkeypatch, tmp_path):
    captured = {}

    def fake_create_uffizio_bulk_trip(source_path, output_path, trip_type=None, vehicles=None):
        captured["source_path"] = source_path
        captured["output_path"] = output_path
        captured["trip_type"] = trip_type
        captured["vehicles"] = vehicles
        output_path.write_bytes(b"xlsx")

    monkeypatch.setattr(web_app, "create_uffizio_bulk_trip", fake_create_uffizio_bulk_trip)
    monkeypatch.setattr(web_app, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(web_app, "OUTPUT_DIR", tmp_path / "outputs")
    web_app.app.config["TESTING"] = True
    client = web_app.app.test_client()

    response = client.post(
        "/uffizio/create",
        data={
            "route_excel_file": (BytesIO(b"excel"), "001_Ruta #22_MC.xlsx"),
            "trip_type": "Drop",
            "vehicles": "vehicle 3",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Descargar Excel" in response.data
    assert captured["source_path"].name == "001_Ruta _22_MC.xlsx"
    assert captured["output_path"].name == "BulkCreateTrip_001_Ruta _22_MC.xlsx"
    assert captured["trip_type"] == "Drop"
    assert captured["vehicles"] == ["vehicle 3"]
