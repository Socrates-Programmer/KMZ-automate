from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from flask import Flask, abort, render_template, request, send_file, url_for

from kmz_route_corrector.core import process_kmz
from kmz_route_corrector.report import (
    DEFAULT_ROUTE_EXCEL_TEMPLATE,
    SCHEDULE_DAY_COLUMNS,
    default_bulk_trip_settings,
    route_excel_template_options,
)

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


def index_context(selected_route_excel_template: str | None = None):
    return {
        "bulk_defaults": default_bulk_trip_settings(),
        "schedule_days": SCHEDULE_DAY_COLUMNS,
        "route_excel_templates": route_excel_template_options(),
        "selected_route_excel_template": selected_route_excel_template or DEFAULT_ROUTE_EXCEL_TEMPLATE,
    }


@app.get("/")
def index():
    return render_template("index.html", **index_context())


@app.post("/process")
def process_upload():
    uploaded = request.files.get("kmz_file")
    if uploaded is None or not uploaded.filename:
        return render_template(
            "index.html",
            error="Selecciona un archivo KMZ.",
            **index_context(request.form.get("route_excel_template")),
        ), 400

    filename = safe_filename(uploaded.filename)
    if not filename.lower().endswith(".kmz"):
        return render_template(
            "index.html",
            error="Solo se aceptan archivos .kmz.",
            **index_context(request.form.get("route_excel_template")),
        ), 400

    offset_meters = 10.0
    school_radius_meters = 100.0
    schedule_days = request.form.getlist("schedule_days")

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
            route_excel_template=request.form.get("route_excel_template"),
            bulk_trip_type=request.form.get("bulk_trip_type"),
            bulk_consider_path=request.form.get("bulk_consider_path"),
            bulk_valid_from=request.form.get("bulk_valid_from"),
            bulk_valid_to=request.form.get("bulk_valid_to"),
            bulk_pickup_time=request.form.get("bulk_pickup_time"),
            bulk_drop_time=request.form.get("bulk_drop_time"),
            bulk_add_as_address=request.form.get("bulk_add_as_address"),
            bulk_schedule_days=schedule_days,
            bulk_schedule_value=request.form.get("bulk_schedule_value"),
            bulk_location=request.form.get("bulk_location"),
        )
    except Exception as exc:
        return render_template(
            "index.html",
            error=f"No se pudo procesar el KMZ: {exc}",
            **index_context(request.form.get("route_excel_template")),
        ), 400

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
    host = os.getenv("KMZ_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("KMZ_WEB_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
