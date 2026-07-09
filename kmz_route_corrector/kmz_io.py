from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class KmlPackage:
    root: ET.Element
    primary_kml_name: str
    original_entries: dict[str, bytes]
    warnings: list[str]


def read_kmz(path: str | Path) -> KmlPackage:
    kmz_path = Path(path)
    warnings: list[str] = []
    if not kmz_path.exists():
        raise FileNotFoundError(f"No existe el archivo: {kmz_path}")

    with zipfile.ZipFile(kmz_path, "r") as archive:
        entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}

    kml_names = [name for name in entries if name.lower().endswith(".kml")]
    if not kml_names:
        raise ValueError("El KMZ no contiene archivos .kml")

    primary = next((name for name in kml_names if Path(name).name.lower() == "doc.kml"), kml_names[0])
    if len(kml_names) > 1:
        warnings.append(
            "El KMZ contiene varios KML; se proceso el principal "
            f"'{primary}' y se copiaron los demas sin modificar."
        )

    root = ET.fromstring(entries[primary])
    return KmlPackage(root=root, primary_kml_name=primary, original_entries=entries, warnings=warnings)


def write_kml(root: ET.Element, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def write_kmz(
    root: ET.Element,
    path: str | Path,
    primary_kml_name: str,
    original_entries: dict[str, bytes] | None = None,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    kml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(primary_kml_name or "doc.kml", kml_bytes)
        for name, payload in (original_entries or {}).items():
            if name == primary_kml_name or name.lower().endswith(".kml"):
                continue
            archive.writestr(name, payload)


def make_output_paths(input_path: Path, output_path: str | Path | None, output_dir: str | Path | None = None) -> tuple[Path, Path, Path, Path]:
    base_name = input_path.stem
    if output_path:
        kmz_path = Path(output_path)
        if not kmz_path.is_absolute() and output_dir:
            kmz_path = Path(output_dir) / kmz_path
    else:
        parent = Path(output_dir) if output_dir else input_path.parent
        kmz_path = parent / f"{base_name}_corregido.kmz"

    stem = kmz_path.stem
    out_parent = kmz_path.parent
    kml_path = out_parent / f"{stem}.kml"
    report_path = out_parent / "reporte_correccion_rutas.csv"
    warnings_path = out_parent / "warnings.log"
    return kmz_path, kml_path, report_path, warnings_path
