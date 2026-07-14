from __future__ import annotations

import math
import textwrap
from pathlib import Path

from .models import Coordinate, Irregularity


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 48
MAP_X = 50
MAP_Y = 345
MAP_WIDTH = 495
MAP_HEIGHT = 285
INDEX_ROWS_PER_PAGE = 28
FIRST_ROUTE_DETAILS_PER_PAGE = 7
CONTINUATION_ROUTE_DETAILS_PER_PAGE = 24

IrregularityGroup = tuple[str, str, list[Irregularity]]


def write_irregularities_pdf(path: str | Path, irregularities: list[Irregularity]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    irregularities = [irregularity for irregularity in irregularities if irregularity.kind != "removed_stop"]
    groups = group_irregularities(irregularities)
    pages = build_report_pages(groups) if groups else [build_empty_page(1, 1)]
    output_path.write_bytes(build_pdf(pages))


def group_irregularities(irregularities: list[Irregularity]) -> list[IrregularityGroup]:
    groups: list[IrregularityGroup] = []
    index: dict[tuple[str, str], list[Irregularity]] = {}
    for irregularity in irregularities:
        district = irregularity.district_name or "Sin distrito"
        route = irregularity.route_name or "Ruta sin nombre"
        key = (district, route)
        if key not in index:
            items: list[Irregularity] = []
            index[key] = items
            groups.append((district, route, items))
        index[key].append(irregularity)
    return groups


def build_report_pages(groups: list[IrregularityGroup]) -> list[str]:
    index_page_count = max(1, math.ceil(len(groups) / INDEX_ROWS_PER_PAGE))
    route_page_counts = [route_page_count(len(items)) for _, _, items in groups]
    total_irregularities = sum(len(items) for _, _, items in groups)
    total_pages = index_page_count + sum(route_page_counts)

    route_start_pages: dict[tuple[str, str], int] = {}
    next_page = index_page_count + 1
    for (district, route, _), page_count in zip(groups, route_page_counts):
        route_start_pages[(district, route)] = next_page
        next_page += page_count

    pages: list[str] = []
    for index_page in range(index_page_count):
        pages.append(
            build_index_page(
                groups,
                route_start_pages,
                total_irregularities,
                index_page,
                index_page_count,
                page_number=index_page + 1,
                total_pages=total_pages,
            )
        )

    current_page = index_page_count + 1
    for group_number, ((district, route, items), page_count) in enumerate(zip(groups, route_page_counts), start=1):
        for route_page_index in range(page_count):
            pages.append(
                build_route_page(
                    district,
                    route,
                    items,
                    group_number,
                    len(groups),
                    route_page_index,
                    page_count,
                    page_number=current_page,
                    total_pages=total_pages,
                )
            )
            current_page += 1
    return pages


def route_page_count(item_count: int) -> int:
    if item_count <= FIRST_ROUTE_DETAILS_PER_PAGE:
        return 1
    remaining = item_count - FIRST_ROUTE_DETAILS_PER_PAGE
    return 1 + math.ceil(remaining / CONTINUATION_ROUTE_DETAILS_PER_PAGE)


def route_page_slice(items: list[Irregularity], route_page_index: int) -> tuple[int, list[Irregularity]]:
    if route_page_index == 0:
        return 0, items[:FIRST_ROUTE_DETAILS_PER_PAGE]
    start = FIRST_ROUTE_DETAILS_PER_PAGE + (route_page_index - 1) * CONTINUATION_ROUTE_DETAILS_PER_PAGE
    end = start + CONTINUATION_ROUTE_DETAILS_PER_PAGE
    return start, items[start:end]


def build_empty_page(page_number: int, total_pages: int) -> str:
    commands = [
        text_cmd("Reporte de irregularidades", MARGIN, 790, 18),
        text_cmd("No se detectaron irregularidades con las reglas actuales.", MARGIN, 755, 12),
        text_cmd("Reglas evaluadas:", MARGIN, 715, 12),
        text_cmd("- Paradas eliminadas solo si estaban a mas de 150 m de la ruta.", MARGIN + 16, 692, 11),
        text_cmd("- Centros educativos a 400 m de la ruta sin parada cercana.", MARGIN + 16, 672, 11),
        text_cmd("- Tramos de mas de 1500 m sin paradas sobre el recorrido.", MARGIN + 16, 652, 11),
        footer_cmd(page_number, total_pages),
    ]
    return "\n".join(commands)


def build_index_page(
    groups: list[IrregularityGroup],
    route_start_pages: dict[tuple[str, str], int],
    total_irregularities: int,
    index_page: int,
    index_page_count: int,
    *,
    page_number: int,
    total_pages: int,
) -> str:
    start = index_page * INDEX_ROWS_PER_PAGE
    end = start + INDEX_ROWS_PER_PAGE
    page_groups = groups[start:end]
    commands = [
        text_cmd("Reporte de irregularidades", MARGIN, 795, 18),
        text_cmd("Indice por distrito y ruta", MARGIN, 768, 13),
        text_cmd(f"Total: {total_irregularities} irregularidades en {len(groups)} rutas.", MARGIN, 744, 11),
    ]
    if index_page_count > 1:
        commands.append(text_cmd(f"Indice {index_page + 1} de {index_page_count}", MARGIN, 726, 10))

    y = 700
    commands.extend([
        text_cmd("Ruta", MARGIN, y, 10),
        text_cmd("Irreg.", 438, y, 10),
        text_cmd("Pag.", 505, y, 10),
    ])
    y -= 18
    for offset, (district, route, items) in enumerate(page_groups, start=start + 1):
        route_page = route_start_pages[(district, route)]
        commands.append(text_cmd(f"{offset}. {truncate_text(district + ' / ' + route, 78)}", MARGIN, y, 9))
        commands.append(text_cmd(str(len(items)), 452, y, 9))
        commands.append(text_cmd(str(route_page), 510, y, 9))
        y -= 20

    commands.append(footer_cmd(page_number, total_pages))
    return "\n".join(commands)


def build_route_page(
    district: str,
    route: str,
    items: list[Irregularity],
    group_number: int,
    total_groups: int,
    route_page_index: int,
    route_page_count: int,
    *,
    page_number: int,
    total_pages: int,
) -> str:
    start_index, page_items = route_page_slice(items, route_page_index)
    route_title = f"Distrito: {district} | Ruta: {route}"
    commands = [
        text_cmd("Resumen de ruta", MARGIN, 795, 18),
        text_cmd(f"Ruta {group_number} de {total_groups}", MARGIN, 770, 10),
        text_cmd(route_title, MARGIN, 744, 12),
        text_cmd(f"Irregularidades en esta ruta: {len(items)}", MARGIN, 722, 11),
    ]
    if route_page_count > 1:
        commands.append(text_cmd(f"Pagina de ruta {route_page_index + 1} de {route_page_count}", MARGIN, 704, 10))

    if route_page_index == 0:
        commands.append(text_cmd("Grafico consolidado: todas las irregularidades de esta ruta en un solo recorrido.", MARGIN, 684, 10))
        commands.extend(draw_route_capture(items))
        commands.append(text_cmd("Leyenda: franja amarilla/roja=recorrido KML; naranja=tramo; I#=irregularidad listada abajo.", MARGIN, 324, 8))
        y = 300
    else:
        commands.append(text_cmd("Continuacion del listado. El grafico consolidado esta en la primera pagina de esta ruta.", MARGIN, 684, 10))
        y = 650

    for local_index, irregularity in enumerate(page_items, start=start_index + 1):
        y = add_irregularity_detail(commands, irregularity, local_index, y)
        if y < 58:
            break

    commands.append(footer_cmd(page_number, total_pages))
    return "\n".join(commands)


def add_irregularity_detail(commands: list[str], irregularity: Irregularity, local_index: int, y: int) -> int:
    header = f"I{local_index}. {irregularity.title}"
    commands.append(text_cmd(header, MARGIN, y, 9))
    y -= 13
    lines = [
        f"Resumen: {short_irregularity_text(irregularity)}",
        f"Criterio: {irregularity_rule_text(irregularity)}",
    ]
    if irregularity.distance_meters is not None:
        lines.insert(1, f"Distancia medida: {irregularity.distance_meters:.1f} m")

    for detail in lines:
        for line in wrap_text(detail, 105):
            commands.append(text_cmd(line, MARGIN + 14, y, 8))
            y -= 11
    return y - 6


def short_irregularity_text(irregularity: Irregularity) -> str:
    distance = format_distance(irregularity.distance_meters)
    labels = [point[0] for point in irregularity.points]
    if irregularity.kind == "route_gap" and len(labels) >= 2:
        return f"Tramo de {distance} sin paradas entre {labels[0]} y {labels[1]}."
    if irregularity.kind == "route_gap":
        return f"Ruta de {distance} sin paradas detectadas."
    if irregularity.kind == "removed_far_stop":
        return f"Parada original eliminada/consolidada a {distance} de la linea de ruta."
    if irregularity.kind == "school_without_nearby_stop":
        school_name = labels[0] if labels else "Centro educativo"
        return f"{school_name} esta cerca de la ruta, pero no tiene parada a 400 m o menos."
    if irregularity.kind == "removed_stop":
        return "Parada original consolidada con otra parada consecutiva cercana."
    if irregularity.kind == "generated_duplicate_stop":
        return f"Parada corregida omitida por duplicado; separacion {distance}."
    if irregularity.kind == "school_cluster_duplicate_stop":
        return f"Duplicado cerca del mismo centro educativo; separacion {distance}."
    if irregularity.kind == "created_unmatched_stop":
        return "Parada de ida corregida sin coincidencia con una parada original conservada."
    return truncate_text(irregularity.description or irregularity.title, 115)


def irregularity_rule_text(irregularity: Irregularity) -> str:
    if irregularity.kind == "route_gap":
        return "El recorrido entre paradas supera 1500 m sobre el LineString de la ruta."
    if irregularity.kind == "removed_far_stop":
        return "Una parada eliminada/consolidada estaba a mas de 150 m de la linea de ruta."
    if irregularity.kind == "school_without_nearby_stop":
        return "Un centro educativo esta a 400 m o menos de la ruta, pero ninguna parada queda a 400 m o menos del centro."
    if irregularity.kind == "removed_stop":
        return "Dos paradas originales consecutivas se consolidaron por cercania."
    if irregularity.kind == "generated_duplicate_stop":
        return "Dos paradas corregidas quedaron duplicadas en la misma zona de la ruta."
    if irregularity.kind == "school_cluster_duplicate_stop":
        return "Se conserva la parada mas cercana al centro educativo por sentido y se reporta la omitida."
    if irregularity.kind == "created_unmatched_stop":
        return "Una parada de ida corregida no viene de una parada original conservada."
    return "Regla interna asociada a este tipo de irregularidad."


def format_distance(distance_meters: float | None) -> str:
    if distance_meters is None:
        return "distancia no disponible"
    return f"{distance_meters:.1f} m"


def draw_route_capture(irregularities: list[Irregularity]) -> list[str]:
    commands = draw_map_background()
    line_coords = route_line_coords(irregularities)
    points = route_marker_points(irregularities)
    mapper = CoordinateMapper(line_coords, points)
    if mapper.is_empty:
        commands.append(text_cmd("No hay geometria suficiente para dibujar el esquema.", MAP_X + 18, MAP_Y + MAP_HEIGHT - 30, 10))
        return commands

    route_points = [mapper.map(lon, lat) for lon, lat, _ in line_coords]
    if len(route_points) >= 2:
        commands.extend(draw_route_line(route_points))

    for local_index, irregularity in enumerate(irregularities, start=1):
        if irregularity.kind == "route_gap" and len(irregularity.points) >= 2:
            highlight = [mapper.map(irregularity.points[0][1], irregularity.points[0][2]), mapper.map(irregularity.points[1][1], irregularity.points[1][2])]
            commands.extend(draw_polyline(highlight, "1.00 0.48 0.05", 5.0))
            commands.extend(draw_polyline(highlight, "0.85 0.05 0.05", 2.0))

        x, y = mapper.map(irregularity.lon, irregularity.lat)
        commands.extend(draw_marker(x, y, f"I{local_index}", irregularity.kind))

    if len(route_points) >= 2:
        commands.extend(draw_route_vertices(route_points))
    commands.extend(draw_scale_hint(mapper))
    return commands


def route_line_coords(irregularities: list[Irregularity]) -> list[Coordinate]:
    return max((irregularity.line_coords for irregularity in irregularities), key=len, default=[])


def route_marker_points(irregularities: list[Irregularity]) -> list[tuple[str, float, float]]:
    points: list[tuple[str, float, float]] = []
    for index, irregularity in enumerate(irregularities, start=1):
        points.append((f"I{index}", irregularity.lon, irregularity.lat))
        if irregularity.kind == "route_gap":
            points.extend(irregularity.points[:2])
    return points


def draw_polyline(points: list[tuple[float, float]], color: str, width: float) -> list[str]:
    if len(points) < 2:
        return []
    first_x, first_y = points[0]
    parts = [f"{color} RG {width:.1f} w", f"{first_x:.2f} {first_y:.2f} m"]
    parts.extend(f"{x:.2f} {y:.2f} l" for x, y in points[1:])
    parts.append("S")
    return parts


def draw_map_background() -> list[str]:
    commands = [
        "0.93 0.94 0.91 rg",
        f"{MAP_X} {MAP_Y} {MAP_WIDTH} {MAP_HEIGHT} re f",
        "0.82 0.84 0.80 RG 0.4 w",
    ]
    for offset in range(50, MAP_WIDTH, 50):
        x = MAP_X + offset
        commands.append(f"{x:.2f} {MAP_Y:.2f} m {x:.2f} {MAP_Y + MAP_HEIGHT:.2f} l S")
    for offset in range(50, MAP_HEIGHT, 50):
        y = MAP_Y + offset
        commands.append(f"{MAP_X:.2f} {y:.2f} m {MAP_X + MAP_WIDTH:.2f} {y:.2f} l S")
    commands.extend([
        "0.68 0.70 0.66 RG 0.8 w",
        f"{MAP_X} {MAP_Y} {MAP_WIDTH} {MAP_HEIGHT} re S",
    ])
    return commands


def draw_route_line(points: list[tuple[float, float]]) -> list[str]:
    commands: list[str] = []
    commands.extend(draw_polyline(points, "0.98 0.82 0.18", 7.0))
    commands.extend(draw_polyline(points, "0.98 0.93 0.45", 4.0))
    commands.extend(draw_polyline(points, "0.85 0.05 0.05", 1.8))
    return commands


def draw_route_vertices(points: list[tuple[float, float]]) -> list[str]:
    if len(points) <= 2:
        return []
    step = max(1, len(points) // 30)
    commands = ["0.30 0.30 0.30 rg"]
    for x, y in points[::step]:
        commands.append(f"{x - 1.2:.2f} {y - 1.2:.2f} 2.4 2.4 re f")
    return commands


def draw_scale_hint(mapper: CoordinateMapper) -> list[str]:
    scale_meters = mapper.approximate_scale_meters()
    if scale_meters <= 0:
        return []
    x = MAP_X + 18
    y = MAP_Y + 18
    bar_width = 95
    return [
        "0 0 0 RG 1.2 w",
        f"{x:.2f} {y:.2f} m {x + bar_width:.2f} {y:.2f} l S",
        f"{x:.2f} {y - 4:.2f} m {x:.2f} {y + 4:.2f} l S",
        f"{x + bar_width:.2f} {y - 4:.2f} m {x + bar_width:.2f} {y + 4:.2f} l S",
        text_cmd(f"~{scale_meters:.0f} m", x + 28, y + 8, 8),
    ]


def draw_marker(x: float, y: float, label: str, kind: str) -> list[str]:
    fill = "0.12 0.35 0.80 rg" if kind == "school_without_nearby_stop" else "0.88 0.10 0.10 rg"
    return [
        fill,
        f"{x - 4:.2f} {y - 4:.2f} 8 8 re f",
        "1 1 1 RG 0.5 w",
        f"{x - 4:.2f} {y - 4:.2f} 8 8 re S",
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
        self.pad_bounds()

    def pad_bounds(self) -> None:
        lon_pad = max((self.max_lon - self.min_lon) * 0.08, 0.0001)
        lat_pad = max((self.max_lat - self.min_lat) * 0.08, 0.0001)
        self.min_lon -= lon_pad
        self.max_lon += lon_pad
        self.min_lat -= lat_pad
        self.max_lat += lat_pad

    def map(self, lon: float, lat: float) -> tuple[float, float]:
        x = MAP_X + 18 + ((lon - self.min_lon) / (self.max_lon - self.min_lon)) * (MAP_WIDTH - 36)
        y = MAP_Y + 18 + ((lat - self.min_lat) / (self.max_lat - self.min_lat)) * (MAP_HEIGHT - 36)
        return x, y

    def approximate_scale_meters(self) -> float:
        lon_span = abs(self.max_lon - self.min_lon)
        lat_span = abs(self.max_lat - self.min_lat)
        center_lat = (self.min_lat + self.max_lat) / 2
        meters_per_degree_lon = 111320 * math.cos(math.radians(center_lat))
        width_meters = max(lon_span * meters_per_degree_lon, lat_span * 111320)
        return width_meters * (95 / max(MAP_WIDTH - 36, 1))


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


def footer_cmd(page_number: int, total_pages: int) -> str:
    return text_cmd(f"Pagina {page_number} de {total_pages}", PAGE_WIDTH - 132, 32, 9)


def escape_pdf_text(text: str) -> str:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return safe.replace("\r", " ").replace("\n", " ")


def wrap_text(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width) or [""]


def truncate_text(text: str, max_length: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."
