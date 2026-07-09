from __future__ import annotations

import re
import uuid
from pathlib import Path

from flask import Flask, abort, render_template, request, send_file, url_for

from kmz_route_corrector.core import process_kmz

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
MAX_UPLOAD_MB = 100

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def safe_filename(filename: str) -> str:
    name = Path(filename or "archivo.kmz").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "archivo.kmz"


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/process")
def process_upload():
    uploaded = request.files.get("kmz_file")
    if uploaded is None or not uploaded.filename:
        return render_template("index.html", error="Selecciona un archivo KMZ."), 400

    filename = safe_filename(uploaded.filename)
    if not filename.lower().endswith(".kmz"):
        return render_template("index.html", error="Solo se aceptan archivos .kmz."), 400

    offset_meters = 10.0
    school_radius_meters = 100.0

    job_id = uuid.uuid4().hex
    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_upload_dir / filename
    uploaded.save(input_path)

    try:
        result = process_kmz(
            input_path,
            output_dir=job_output_dir,
            offset_meters=offset_meters,
            school_radius_meters=school_radius_meters,
            create_bundle=True,
        )
    except Exception as exc:
        return render_template("index.html", error=f"No se pudo procesar el KMZ: {exc}"), 400

    return render_template(
        "result.html",
        result=result,
        download_url=url_for("download_result", job_id=job_id),
    )


@app.get("/download/<job_id>")
def download_result(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        abort(404)
    job_output_dir = OUTPUT_DIR / job_id
    bundles = sorted(job_output_dir.glob("*_resultados.zip"))
    if not bundles:
        abort(404)
    return send_file(bundles[0], as_attachment=True, download_name=bundles[0].name)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
