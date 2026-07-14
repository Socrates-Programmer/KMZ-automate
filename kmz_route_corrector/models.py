from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


Coordinate = tuple[float, float, float | None]


@dataclass
class Stop:
    name: str
    lon: float
    lat: float
    alt: float | None
    element: Any
    parent: Any
    original_index: int
    source: str


@dataclass
class School:
    name: str
    lon: float
    lat: float
    raw_name: str = ""
    source: str = ""


@dataclass
class SchoolMatch:
    school: School | None
    distance_meters: float | None
    multiple_matches: bool = False


@dataclass
class Route:
    name: str
    container: Any
    document: Any
    line_placemark: Any | None
    line_coords: list[Coordinate]
    stop_source_nodes: list[Any]
    stop_source_parents: list[Any]
    stops: list[Stop] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_no_operar: bool = False
    source_kind: str = "folder"
    district_name: str = "Sin distrito"


@dataclass
class CorrectedStop:
    route_name: str
    original_name: str
    new_name: str
    tipo: str
    original_lon: float
    original_lat: float
    new_lon: float
    new_lat: float
    offset_meters: float
    school_name: str = ""
    school_distance_meters: float | None = None
    school_source: str = ""
    is_pf: bool = False
    ordering_method: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class Irregularity:
    route_name: str
    kind: str
    title: str
    description: str
    lon: float
    lat: float
    line_coords: list[Coordinate] = field(default_factory=list)
    points: list[tuple[str, float, float]] = field(default_factory=list)
    distance_meters: float | None = None
    district_name: str = "Sin distrito"


@dataclass
class RouteCorrection:
    route: Route
    ordering_method: str
    stops: list[CorrectedStop]
    warnings: list[str] = field(default_factory=list)
    irregularities: list[Irregularity] = field(default_factory=list)


@dataclass
class Summary:
    routes_processed: int = 0
    original_stops_detected: int = 0
    new_stops_created: int = 0
    pf_stops_created: int = 0
    schools_detected: int = 0
    stops_with_school: int = 0
    irregularities_count: int = 0
    warnings_count: int = 0


@dataclass
class ProcessResult:
    input_path: Path
    output_kmz_path: Path
    output_kml_path: Path
    report_csv_path: Path
    route_flow_csv_path: Path
    irregularities_report_pdf_path: Path
    warnings_log_path: Path
    route_excel_paths: list[Path]
    bundle_zip_path: Path | None
    summary: Summary
    warnings: list[str]
