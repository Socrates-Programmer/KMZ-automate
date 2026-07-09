from __future__ import annotations

import argparse
from pathlib import Path

from .core import print_summary, process_kmz


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Corrige rutas escolares dentro de archivos KMZ/KML.")
    parser.add_argument("--input", required=True, help="Ruta del archivo .kmz de entrada.")
    parser.add_argument("--output", help="Ruta del archivo .kmz corregido.")
    parser.add_argument("--offset-meters", type=float, default=10.0, help="Separacion lateral minima desde la linea, 10 metros o mas.")
    parser.add_argument("--school-radius-meters", type=float, default=100.0, help="Radio de busqueda de centros educativos.")
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
    )
    print_summary(result)
    if result.bundle_zip_path:
        print()
        print("ZIP generado:")
        print(result.bundle_zip_path)
    return 0
