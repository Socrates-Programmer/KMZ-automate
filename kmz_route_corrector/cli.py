from __future__ import annotations

import argparse
from pathlib import Path

from .core import print_summary, process_kmz
from .report import ROUTE_EXCEL_TEMPLATE_BULK, ROUTE_EXCEL_TEMPLATE_STOPS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Corrige rutas escolares dentro de archivos KMZ/KML.")
    parser.add_argument("--input", required=True, help="Ruta del archivo .kmz de entrada.")
    parser.add_argument("--output", help="Ruta del archivo .kmz corregido.")
    parser.add_argument("--offset-meters", type=float, default=10.0, help="Separacion lateral minima desde la linea, 10 metros o mas.")
    parser.add_argument("--school-radius-meters", type=float, default=400.0, help="Radio de busqueda de centros educativos.")
    parser.add_argument(
        "--google-places-api-key",
        help=(
            "API key de Google Places para buscar escuelas si no aparecen en el KMZ ni en OpenStreetMap. "
            "Tambien puede usarse GOOGLE_MAPS_API_KEY."
        ),
    )
    parser.add_argument(
        "--google-places-monthly-limit",
        type=int,
        default=None,
        help="Limite mensual local de requests a Google Places. Default 5000 o GOOGLE_PLACES_MONTHLY_LIMIT.",
    )
    parser.add_argument("--drivers-csv", help="CSV de choferes/autobuses. Default: db/KMZ.csv o KMZ_DRIVERS_CSV_PATH.")
    parser.add_argument(
        "--route-template",
        help="Plantilla Excel de rutas. Default: kmz-plantilla/BulkCreateTrip.xlsx o KMZ_ROUTE_TEMPLATE_PATH.",
    )
    parser.add_argument(
        "--route-excel-template",
        choices=[ROUTE_EXCEL_TEMPLATE_BULK, ROUTE_EXCEL_TEMPLATE_STOPS],
        default=None,
        help="Formato de Excel por ruta: bulk_create_trip o plantillas_rutas.",
    )
    parser.add_argument("--bulk-trip-type", default=None, help="Trip Type para BulkCreateTrip. Default: Pickup.")
    parser.add_argument("--bulk-consider-path", default=None, help="Consider Path para BulkCreateTrip. Default: Yes.")
    parser.add_argument("--bulk-valid-from", default=None, help="Valid From en formato dd-MM-yyyy. Default: fecha actual.")
    parser.add_argument("--bulk-valid-to", default=None, help="Valid To en formato dd-MM-yyyy. Default: 31-12-del anio actual.")
    parser.add_argument("--bulk-pickup-time", default=None, help="Pickup Time en formato HH:mm. Default: 06:00.")
    parser.add_argument("--bulk-drop-time", default=None, help="Drop Time en formato HH:mm. Default: 14:00.")
    parser.add_argument("--bulk-add-as-address", default=None, help="Add As Address para BulkCreateTrip. Default: No.")
    parser.add_argument("--bulk-schedule-days", default=None, help="Dias activos separados por coma. Default: Mo,Tu,We,Th,Fr,Sa,Su.")
    parser.add_argument("--bulk-schedule-value", default=None, help="Valor a escribir en dias activos. Default: Yes.")
    parser.add_argument("--bulk-location", default=None, help="Location para BulkCreateTrip. Default: distrito de la ruta.")
    parser.add_argument("--output-dir", help="Directorio donde se escribiran los archivos de salida.")
    parser.add_argument("--bundle", action="store_true", help="Genera un ZIP con KMZ, CSV y log.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = process_kmz(
        Path(args.input),
        args.output,
        output_dir=args.output_dir,
        offset_meters=args.offset_meters,
        school_radius_meters=args.school_radius_meters,
        create_bundle=args.bundle,
        google_places_api_key=args.google_places_api_key,
        google_places_monthly_limit=args.google_places_monthly_limit,
        drivers_csv_path=args.drivers_csv,
        route_template_path=args.route_template,
        route_excel_template=args.route_excel_template,
        bulk_trip_type=args.bulk_trip_type,
        bulk_consider_path=args.bulk_consider_path,
        bulk_valid_from=args.bulk_valid_from,
        bulk_valid_to=args.bulk_valid_to,
        bulk_pickup_time=args.bulk_pickup_time,
        bulk_drop_time=args.bulk_drop_time,
        bulk_add_as_address=args.bulk_add_as_address,
        bulk_schedule_days=args.bulk_schedule_days,
        bulk_schedule_value=args.bulk_schedule_value,
        bulk_location=args.bulk_location,
    )
    print_summary(result)
    if result.bundle_zip_path:
        print()
        print("ZIP generado:")
        print(result.bundle_zip_path)
    return 0
