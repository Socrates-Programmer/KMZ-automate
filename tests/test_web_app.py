from io import BytesIO

from web_app import app


def test_rejects_non_kmz_upload():
    app.config["TESTING"] = True
    client = app.test_client()

    response = client.post(
        "/process",
        data={
            "kmz_file": (BytesIO(b"not a kmz"), "archivo.txt"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Solo se aceptan archivos .kmz" in response.data
