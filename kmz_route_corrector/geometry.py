from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Coordinate, Stop

try:
    from pyproj import CRS, Transformer
except ImportError:  # pragma: no cover - exercised only without optional dependency
    CRS = None
    Transformer = None


EARTH_RADIUS_M = 6371008.8


@dataclass
class ProjectionWarning:
    message: str


class Projector:
    def __init__(self, lon: float, lat: float):
        self.lon0 = lon
        self.lat0 = lat
        self._use_pyproj = CRS is not None and Transformer is not None
        self.warning: ProjectionWarning | None = None
        if self._use_pyproj:
            epsg = choose_utm_epsg(lon, lat)
            crs_wgs84 = CRS.from_epsg(4326)
            crs_metric = CRS.from_epsg(epsg)
            self.to_metric = Transformer.from_crs(crs_wgs84, crs_metric, always_xy=True)
            self.to_wgs84 = Transformer.from_crs(crs_metric, crs_wgs84, always_xy=True)
        else:
            self.warning = ProjectionWarning(
                "pyproj no esta instalado; se uso una aproximacion local para distancias/offsets."
            )

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        if self._use_pyproj:
            return self.to_metric.transform(lon, lat)
        lat0_rad = math.radians(self.lat0)
        x = math.radians(lon - self.lon0) * EARTH_RADIUS_M * math.cos(lat0_rad)
        y = math.radians(lat - self.lat0) * EARTH_RADIUS_M
        return x, y

    def unproject(self, x: float, y: float) -> tuple[float, float]:
        if self._use_pyproj:
            return self.to_wgs84.transform(x, y)
        lat = self.lat0 + math.degrees(y / EARTH_RADIUS_M)
        lon = self.lon0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(self.lat0))))
        return lon, lat


def choose_utm_epsg(lon: float, lat: float) -> int:
    if -72.5 <= lon <= -68.0 and 17.0 <= lat <= 20.5:
        return 32619
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def centroid(coords: list[Coordinate]) -> tuple[float, float]:
    valid = [(lon, lat) for lon, lat, _ in coords if math.isfinite(lon) and math.isfinite(lat)]
    if not valid:
        return -69.9, 18.7
    return sum(lon for lon, _ in valid) / len(valid), sum(lat for _, lat in valid) / len(valid)


def haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def project_point_on_polyline(
    point_xy: tuple[float, float],
    line_xy: list[tuple[float, float]],
) -> tuple[float, tuple[float, float], tuple[float, float]] | None:
    if len(line_xy) < 2:
        return None

    px, py = point_xy
    best: tuple[float, float, tuple[float, float], tuple[float, float]] | None = None
    accumulated = 0.0

    for start, end in zip(line_xy, line_xy[1:]):
        ax, ay = start
        bx, by = end
        dx = bx - ax
        dy = by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            continue
        seg_len = math.sqrt(seg_len_sq)
        t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
        t = min(1.0, max(0.0, t))
        qx = ax + t * dx
        qy = ay + t * dy
        dist_sq = (px - qx) ** 2 + (py - qy) ** 2
        tangent = (dx / seg_len, dy / seg_len)
        distance_along = accumulated + t * seg_len
        if best is None or dist_sq < best[0]:
            best = (dist_sq, distance_along, (qx, qy), tangent)
        accumulated += seg_len

    if best is None:
        return None
    _, distance_along, projected, tangent = best
    return distance_along, projected, tangent


def distance_along_line_meters(lon: float, lat: float, line_coords: list[Coordinate]) -> float | None:
    if len(line_coords) < 2:
        return None

    lon0, lat0 = centroid(line_coords)
    projector = Projector(lon0, lat0)
    line_xy = [projector.project(xlon, xlat) for xlon, xlat, _ in line_coords]
    projected = project_point_on_polyline(projector.project(lon, lat), line_xy)
    if projected is None:
        return None
    return projected[0]


def distance_to_line_meters(lon: float, lat: float, line_coords: list[Coordinate]) -> float | None:
    if len(line_coords) < 2:
        return None

    lon0, lat0 = centroid(line_coords)
    projector = Projector(lon0, lat0)
    line_xy = [projector.project(xlon, xlat) for xlon, xlat, _ in line_coords]
    point_xy = projector.project(lon, lat)
    projected = project_point_on_polyline(point_xy, line_xy)
    if projected is None:
        return None
    qx, qy = projected[1]
    return math.hypot(point_xy[0] - qx, point_xy[1] - qy)


def line_length_meters(line_coords: list[Coordinate]) -> float:
    if len(line_coords) < 2:
        return 0.0

    lon0, lat0 = centroid(line_coords)
    projector = Projector(lon0, lat0)
    line_xy = [projector.project(lon, lat) for lon, lat, _ in line_coords]
    return sum(math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(line_xy, line_xy[1:]))


def sort_line_coord_sets_by_length(line_coord_sets: list[list[Coordinate]]) -> list[list[Coordinate]]:
    valid_lines = [line for line in line_coord_sets if len(line) >= 2]
    return sorted(valid_lines, key=line_length_meters, reverse=True)


def point_at_distance_along_line(line_coords: list[Coordinate], distance_meters: float) -> tuple[float, float] | None:
    if len(line_coords) < 2:
        return None

    lon0, lat0 = centroid(line_coords)
    projector = Projector(lon0, lat0)
    line_xy = [projector.project(lon, lat) for lon, lat, _ in line_coords]
    remaining = max(0.0, distance_meters)

    for start, end in zip(line_xy, line_xy[1:]):
        ax, ay = start
        bx, by = end
        seg_len = math.hypot(bx - ax, by - ay)
        if seg_len == 0:
            continue
        if remaining <= seg_len:
            ratio = remaining / seg_len
            return projector.unproject(ax + (bx - ax) * ratio, ay + (by - ay) * ratio)
        remaining -= seg_len

    lon, lat, _ = line_coords[-1]
    return lon, lat


def order_stops_by_line(stops: list[Stop], line_coords: list[Coordinate]) -> tuple[list[Stop], str, list[str]]:
    warnings: list[str] = []
    if len(line_coords) < 2:
        return stops, "orden_kml", ["No hay LineString suficiente; se mantuvo el orden KML."]

    lon0, lat0 = centroid(line_coords)
    projector = Projector(lon0, lat0)
    if projector.warning:
        warnings.append(projector.warning.message)

    line_xy = [projector.project(lon, lat) for lon, lat, _ in line_coords]
    ranked: list[tuple[float, int, Stop]] = []
    for idx, stop in enumerate(stops):
        projected = project_point_on_polyline(projector.project(stop.lon, stop.lat), line_xy)
        if projected is None:
            return stops, "orden_kml", ["No se pudo proyectar una parada sobre la linea; se mantuvo el orden KML."]
        ranked.append((projected[0], idx, stop))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [stop for _, _, stop in ranked], "linea", warnings


def order_stops_by_lines(stops: list[Stop], line_coord_sets: list[list[Coordinate]]) -> tuple[list[Stop], str, list[str]]:
    valid_lines = sort_line_coord_sets_by_length(line_coord_sets)
    if not valid_lines:
        return stops, "orden_kml", ["No hay LineString suficiente; se mantuvo el orden KML."]
    if len(valid_lines) == 1:
        return order_stops_by_line(stops, valid_lines[0])

    ranked: list[tuple[int, float, int, Stop]] = []
    for idx, stop in enumerate(stops):
        line_index, station = nearest_line_station(stop.lon, stop.lat, valid_lines)
        if line_index is None or station is None:
            return stops, "orden_kml", ["No se pudo proyectar una parada sobre las lineas; se mantuvo el orden KML."]
        ranked.append((line_index, station, idx, stop))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [stop for _, _, _, stop in ranked], "lineas", [
        "La ruta tiene multiples LineString; se uso primero el perfil de mayor longitud y luego los menores."
    ]


def nearest_line_station(
    lon: float,
    lat: float,
    line_coord_sets: list[list[Coordinate]],
) -> tuple[int | None, float | None]:
    best_index: int | None = None
    best_station: float | None = None
    best_distance: float | None = None
    for index, line_coords in enumerate(line_coord_sets):
        distance = distance_to_line_meters(lon, lat, line_coords)
        station = distance_along_line_meters(lon, lat, line_coords)
        if distance is None or station is None:
            continue
        if best_distance is None or distance < best_distance:
            best_index = index
            best_station = station
            best_distance = distance
    return best_index, best_station


def orient_line_for_stop_sequence(line_coords: list[Coordinate], ordered_stops: list[Stop]) -> list[Coordinate]:
    if len(line_coords) < 2 or len(ordered_stops) < 2:
        return line_coords

    lon0, lat0 = centroid(line_coords)
    projector = Projector(lon0, lat0)
    line_xy = [projector.project(lon, lat) for lon, lat, _ in line_coords]
    first = ordered_stops[0]
    last = ordered_stops[-1]
    first_projection = project_point_on_polyline(projector.project(first.lon, first.lat), line_xy)
    last_projection = project_point_on_polyline(projector.project(last.lon, last.lat), line_xy)
    if first_projection is None or last_projection is None:
        return line_coords
    if first_projection[0] > last_projection[0]:
        return list(reversed(line_coords))
    return line_coords


def place_stop_on_route_side(
    lon: float,
    lat: float,
    line_coords: list[Coordinate],
    ordered_stops: list[Stop],
    stop_index: int,
    offset_meters: float,
    side: str,
) -> tuple[float, float, list[str]]:
    warnings: list[str] = []
    if side not in {"left", "right"}:
        raise ValueError("side debe ser 'left' o 'right'")

    reference_coords = line_coords or [(stop.lon, stop.lat, stop.alt) for stop in ordered_stops]
    lon0, lat0 = centroid(reference_coords)
    projector = Projector(lon0, lat0)
    if projector.warning:
        warnings.append(projector.warning.message)

    point_xy = projector.project(lon, lat)
    tangent: tuple[float, float] | None = None
    projected_xy: tuple[float, float] | None = None

    if len(line_coords) >= 2:
        line_xy = [projector.project(xlon, xlat) for xlon, xlat, _ in line_coords]
        projected = project_point_on_polyline(point_xy, line_xy)
        if projected is not None:
            projected_xy = projected[1]
            tangent = projected[2]

    if tangent is None:
        tangent = tangent_from_neighbor_stops(projector, ordered_stops, stop_index)
        if tangent is not None:
            warnings.append("Offset calculado con paradas vecinas por falta de LineString util.")

    if tangent is None:
        warnings.append("No se pudo calcular direccion; la parada corregida quedo en la coordenada original.")
        return lon, lat, warnings

    tx, ty = tangent
    side_x, side_y = (-ty, tx) if side == "left" else (ty, -tx)
    if projected_xy is not None:
        new_x = projected_xy[0] + side_x * offset_meters
        new_y = projected_xy[1] + side_y * offset_meters
    else:
        new_x = point_xy[0] + side_x * offset_meters
        new_y = point_xy[1] + side_y * offset_meters
    new_lon, new_lat = projector.unproject(new_x, new_y)
    return new_lon, new_lat, warnings


def offset_left_of_route(
    lon: float,
    lat: float,
    line_coords: list[Coordinate],
    ordered_stops: list[Stop],
    stop_index: int,
    offset_meters: float,
) -> tuple[float, float, list[str]]:
    return place_stop_on_route_side(lon, lat, line_coords, ordered_stops, stop_index, offset_meters, "left")


def tangent_from_neighbor_stops(projector: Projector, stops: list[Stop], index: int) -> tuple[float, float] | None:
    if len(stops) < 2:
        return None

    current = stops[index]
    if 0 < index < len(stops) - 1:
        a = stops[index - 1]
        b = stops[index + 1]
    elif index == 0:
        a = current
        b = stops[index + 1]
    else:
        a = stops[index - 1]
        b = current

    ax, ay = projector.project(a.lon, a.lat)
    bx, by = projector.project(b.lon, b.lat)
    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    return dx / length, dy / length
