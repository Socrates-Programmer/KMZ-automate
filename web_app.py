from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from flask import Flask, abort, render_template, request, send_file, url_for

from kmz_route_corrector.core import process_kmz
from kmz_route_corrector.report import ROUTE_EXCEL_TEMPLATE_STOPS
from kmz_route_corrector.uffizio import bulk_trip_type_options, bulk_trip_vehicle_options, create_uffizio_bulk_trip

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
MAX_UPLOAD_MB = 100

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def safe_filename(filename: str) -> str:
    name = Path(filename or "archivo").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "archivo"


def uffizio_context(**extra):
    context = {
        "active_page": "uffizio",
        "trip_type_options": bulk_trip_type_options(),
        "vehicle_options": bulk_trip_vehicle_options(),
    }
    context.update(extra)
    return context


@app.get("/")
def index():
    return render_template("index.html", active_page="kmz")


@app.post("/process")
def process_upload():
    uploaded = request.files.get("kmz_file")
    if uploaded is None or not uploaded.filename:
        return render_template(
            "index.html",
            error="Selecciona un archivo KMZ.",
            active_page="kmz",
        ), 400

    filename = safe_filename(uploaded.filename)
    if not filename.lower().endswith(".kmz"):
        return render_template(
            "index.html",
            error="Solo se aceptan archivos .kmz.",
            active_page="kmz",
        ), 400

    offset_meters = 10.0
    school_radius_meters = 400.0

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
            route_excel_template=ROUTE_EXCEL_TEMPLATE_STOPS,
        )
    except Exception as exc:
        return render_template(
            "index.html",
            error=f"No se pudo procesar el KMZ: {exc}",
            active_page="kmz",
        ), 400

    return render_template(
        "result.html",
        result=result,
        download_url=url_for("download_result", job_id=job_id),
        active_page="kmz",
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


@app.get("/uffizio")
def uffizio():
    return render_template("uffizio.html", **uffizio_context())


@app.post("/uffizio/create")
def create_uffizio_route():
    uploaded = request.files.get("route_excel_file")
    if uploaded is None or not uploaded.filename:
        return render_template(
            "uffizio.html",
            error="Selecciona un archivo Excel.",
            **uffizio_context(),
        ), 400

    filename = safe_filename(uploaded.filename)
    if not filename.lower().endswith(".xlsx"):
        return render_template(
            "uffizio.html",
            error="Solo se aceptan archivos .xlsx.",
            **uffizio_context(),
        ), 400

    job_id = uuid.uuid4().hex
    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_upload_dir / filename
    uploaded.save(input_path)
    output_path = job_output_dir / f"BulkCreateTrip_{Path(filename).stem}.xlsx"

    try:
        create_uffizio_bulk_trip(
            input_path,
            output_path,
            trip_type=request.form.get("trip_type"),
            vehicles=request.form.getlist("vehicles"),
        )
    except Exception as exc:
        return render_template(
            "uffizio.html",
            error=f"No se pudo crear la ruta Uffizio: {exc}",
            **uffizio_context(),
        ), 400

    return render_template(
        "uffizio_result.html",
        download_url=url_for("download_uffizio_result", job_id=job_id),
        output_name=output_path.name,
        active_page="uffizio",
    )


@app.get("/uffizio/download/<job_id>")
def download_uffizio_result(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        abort(404)
    job_output_dir = OUTPUT_DIR / job_id
    files = sorted(job_output_dir.glob("BulkCreateTrip_*.xlsx"))
    if not files:
        abort(404)
    return send_file(files[0], as_attachment=True, download_name=files[0].name)


if __name__ == "__main__":
    host = os.getenv("KMZ_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("KMZ_WEB_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
