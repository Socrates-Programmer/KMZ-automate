from __future__ import annotations

import textwrap
from pathlib import Path

from .models import Coordinate, Irregularity


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 48
MAP_X = 50
MAP_Y = 250
MAP_WIDTH = 495
MAP_HEIGHT = 300


def write_irregularities_pdf(path: str | Path, irregularities: list[Irregularity]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pages = [build_irregularity_page(irregularity, index, len(irregularities)) for index, irregularity in enumerate(irregularities, start=1)]
    if not pages:
        pages = [build_empty_page()]
    output_path.write_bytes(build_pdf(pages))


def build_empty_page() -> str:
    commands = [
        text_cmd("Reporte de irregularidades", MARGIN, 790, 18),
        text_cmd("No se detectaron irregularidades con las reglas actuales.", MARGIN, 755, 12),
        text_cmd("Reglas evaluadas:", MARGIN, 715, 12),
        text_cmd("- Paradas eliminadas a mas de 150 m de la ruta.", MARGIN + 16, 692, 11),
        text_cmd("- Tramos largos de ruta sin paradas.", MARGIN + 16, 672, 11),
    ]
    return "\n".join(commands)


def build_irregularity_page(irregularity: Irregularity, index: int, total: int) -> str:
    commands: list[str] = [
        text_cmd("Reporte de irregularidades", MARGIN, 795, 18),
        text_cmd(f"Irregularidad {index} de {total}", MARGIN, 768, 10),
        text_cmd(f"Ruta: {irregularity.route_name}", MARGIN, 742, 12),
        text_cmd(f"Tipo: {irregularity.title}", MARGIN, 722, 12),
    ]
    if irregularity.distance_meters is not None:
        commands.append(text_cmd(f"Distancia medida: {irregularity.distance_meters:.1f} m", MARGIN, 702, 11))

    y = 675
    for line in wrap_text(irregularity.description, 95):
        commands.append(text_cmd(line, MARGIN, y, 10))
        y -= 16

    commands.extend(draw_capture(irregularity))
    commands.append(text_cmd("Captura esquematica: linea de ruta y punto/tramo asociado a la irregularidad.", MARGIN, 220, 9))
    return "\n".join(commands)


def draw_capture(irregularity: Irregularity) -> list[str]:
    commands = [
        "0.96 0.96 0.96 rg",
        f"{MAP_X} {MAP_Y} {MAP_WIDTH} {MAP_HEIGHT} re f",
        "0.78 0.78 0.78 RG 0.8 w",
        f"{MAP_X} {MAP_Y} {MAP_WIDTH} {MAP_HEIGHT} re S",
    ]
    mapper = CoordinateMapper(irregularity.line_coords, irregularity.points)
    if mapper.is_empty:
        commands.append(text_cmd("No hay geometria suficiente para dibujar la captura.", MAP_X + 18, MAP_Y + MAP_HEIGHT - 30, 10))
        return commands

    route_points = [mapper.map(lon, lat) for lon, lat, _ in irregularity.line_coords]
    if len(route_points) >= 2:
        commands.extend(draw_polyline(route_points, "0.18 0.42 0.76", 1.4))

    if irregularity.kind == "route_gap" and len(irregularity.points) >= 2:
        highlight = [mapper.map(irregularity.points[0][1], irregularity.points[0][2]), mapper.map(irregularity.points[1][1], irregularity.points[1][2])]
        commands.extend(draw_polyline(highlight, "0.90 0.12 0.12", 3.0))

    for label, lon, lat in irregularity.points:
        x, y = mapper.map(lon, lat)
        commands.extend(draw_marker(x, y, label))
    return commands


def draw_polyline(points: list[tuple[float, float]], color: str, width: float) -> list[str]:
    if len(points) < 2:
        return []
    first_x, first_y = points[0]
    parts = [f"{color} RG {width:.1f} w", f"{first_x:.2f} {first_y:.2f} m"]
    parts.extend(f"{x:.2f} {y:.2f} l" for x, y in points[1:])
    parts.append("S")
    return parts


def draw_marker(x: float, y: float, label: str) -> list[str]:
    return [
        "0.88 0.10 0.10 rg",
        f"{x - 4:.2f} {y - 4:.2f} 8 8 re f",
        "0 0 0 rg",
        text_cmd(label, x + 7, y + 7, 8),
    ]


class CoordinateMapper:
    def __init__(self, line_coords: list[Coordinate], points: list[tuple[str, float, float]]):
        coords = [(lon, lat) for lon, lat, _ in line_coords]
        coords.extend((lon, lat) for _, lon, lat in points)
        self.is_empty = not coords
        if not coords:
            self.min_lon = self.max_lon = self.min_lat = self.max_lat = 0.0
            return
        self.min_lon = min(lon for lon, _ in coords)
        self.max_lon = max(lon for lon, _ in coords)
        self.min_lat = min(lat for _, lat in coords)
        self.max_lat = max(lat for _, lat in coords)
        if self.min_lon == self.max_lon:
            self.min_lon -= 0.0001
            self.max_lon += 0.0001
        if self.min_lat == self.max_lat:
            self.min_lat -= 0.0001
            self.max_lat += 0.0001

    def map(self, lon: float, lat: float) -> tuple[float, float]:
        x = MAP_X + 18 + ((lon - self.min_lon) / (self.max_lon - self.min_lon)) * (MAP_WIDTH - 36)
        y = MAP_Y + 18 + ((lat - self.min_lat) / (self.max_lat - self.min_lat)) * (MAP_HEIGHT - 36)
        return x, y


def build_pdf(page_streams: list[str]) -> bytes:
    page_count = len(page_streams)
    font_ref = 3
    pages_ref = 4 + page_count * 2
    catalog_ref = pages_ref + 1
    objects: dict[int, bytes] = {
        font_ref: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids: list[int] = []
    for index, stream in enumerate(page_streams):
        content_ref = 4 + index * 2
        page_ref = content_ref + 1
        kids.append(page_ref)
        stream_bytes = stream.encode("latin-1", errors="replace")
        objects[content_ref] = b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"\nendstream"
        objects[page_ref] = (
            f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_ref} 0 R >> >> /Contents {content_ref} 0 R >>"
        ).encode("ascii")
    objects[pages_ref] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{kid} 0 R' for kid in kids)}] /Count {page_count} >>"
    ).encode("ascii")
    objects[catalog_ref] = f"<< /Type /Catalog /Pages {pages_ref} 0 R >>".encode("ascii")

    output = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for number in range(1, catalog_ref + 1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode("ascii") + objects.get(number, b"<<>>") + b"\nendobj\n"

    xref_offset = len(output)
    output += f"xref\n0 {catalog_ref + 1}\n".encode("ascii")
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode("ascii")
    output += (
        f"trailer\n<< /Size {catalog_ref + 1} /Root {catalog_ref} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return output


def text_cmd(text: str, x: float, y: float, size: int) -> str:
    return f"BT /F1 {size} Tf {x:.2f} {y:.2f} Td ({escape_pdf_text(text)}) Tj ET"


def escape_pdf_text(text: str) -> str:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return safe.replace("\r", " ").replace("\n", " ")


def wrap_text(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width) or [""]
