#!/usr/bin/env python3
"""
Calculate parish/county crossing times for DAT tornado tracks.

Inputs:
  - DAT tornado tracks/damage lines as GeoJSON
  - Parish/county boundary polygons as GeoJSON

Output:
  - CSV of crossing times using constant-speed interpolation along the track
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import pandas as pd
from dateutil import parser as dtparser
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

M_PER_MILE = 1609.344

OUTPUT_COLUMNS = [
    "event_id",
    "stormdate",
    "wfo",
    "efscale",
    "start_time",
    "end_time",
    "duration_minutes",
    "measured_track_miles",
    "total_track_miles_used",
    "avg_speed_mph",
    "crossing_index",
    "crossing_distance_miles",
    "crossing_fraction",
    "crossing_time",
    "boundary_from",
    "boundary_to",
    "crossing_lon",
    "crossing_lat",
    "review_flag",
]


@dataclass
class Config:
    tracks_file: str
    boundaries_file: str
    output_csv: str
    track_id_field: str
    start_time_field: str
    end_time_field: str
    boundary_name_field: str
    timezone: str = "America/Chicago"
    track_length_field_miles: Optional[str] = None
    projected_crs: str = "EPSG:5070"
    endpoint_link_distance_m: float = 250.0
    endpoint_link_time_seconds: float = 120.0
    endpoint_sample_offset_m: float = 100.0


@dataclass
class TrackInfo:
    row: Any
    line: LineString
    tornado_id: str
    start: pd.Timestamp
    end: pd.Timestamp
    measured_miles: float
    total_miles: float
    duration_seconds: float
    duration_minutes: float
    avg_speed_mph: Optional[float]


@dataclass
class LinkedEndpointCrossing:
    point: Point
    boundary_from: str
    boundary_to: str
    downstream_event_id: str


def load_config(path: str | Path) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return Config(**raw)


def parse_time(value: Any, timezone: str) -> pd.Timestamp:
    """Parse DAT/GeoJSON datetime values.

    DAT ArcGIS fields commonly arrive as epoch milliseconds. This also handles
    ISO-ish strings and local/tz-aware text values.
    """
    if pd.isna(value):
        raise ValueError("Missing datetime value")

    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="ms", utc=True).tz_convert(timezone)

    text = str(value).strip()
    if text.replace(".", "", 1).isdigit():
        num = float(text)
        unit = "ms" if num > 10_000_000_000 else "s"
        return pd.to_datetime(num, unit=unit, utc=True).tz_convert(timezone)

    ts = pd.Timestamp(dtparser.parse(text))
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone)
    else:
        ts = ts.tz_convert(timezone)
    return ts


def as_single_line(geom) -> LineString:
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        coords = []
        for part in geom.geoms:
            coords.extend(list(part.coords))
        return LineString(coords)
    raise TypeError(f"Expected LineString or MultiLineString, got {geom.geom_type}")


def point_at_distance(line: LineString, distance_m: float) -> Point:
    distance_m = max(0.0, min(distance_m, line.length))
    return line.interpolate(distance_m)


def boundary_name_at_point(boundaries: gpd.GeoDataFrame, point: Point, name_field: str) -> Optional[str]:
    hits = boundaries[boundaries.contains(point)]
    if not hits.empty:
        return str(hits.iloc[0][name_field])

    distances = boundaries.geometry.distance(point)
    nearest_idx = distances.idxmin()
    if math.isfinite(distances.loc[nearest_idx]) and distances.loc[nearest_idx] < 100:
        return str(boundaries.loc[nearest_idx, name_field])
    return None


def from_to_names(
    boundaries: gpd.GeoDataFrame,
    line: LineString,
    crossing_dist_m: float,
    name_field: str,
    offset_m: float = 100.0,
) -> tuple[Optional[str], Optional[str]]:
    before = point_at_distance(line, crossing_dist_m - offset_m)
    after = point_at_distance(line, crossing_dist_m + offset_m)
    return (
        boundary_name_at_point(boundaries, before, name_field),
        boundary_name_at_point(boundaries, after, name_field),
    )


def extract_crossing_points(line: LineString, boundary_lines) -> list[Point]:
    """Return points where a track crosses parish/county boundary lines.

    Important: do NOT dissolve county polygons and then use the dissolved
    polygon boundary. That removes internal county/parish lines and only leaves
    the outside edge of the whole LA/MS/AL boundary dataset. Instead, this uses
    the union of each polygon's boundary rings, so internal shared boundaries
    remain available for intersection.
    """
    intersection = line.intersection(boundary_lines)
    points: list[Point] = []

    if intersection.is_empty:
        return points
    if isinstance(intersection, Point):
        points.append(intersection)
    elif intersection.geom_type == "MultiPoint":
        points.extend(list(intersection.geoms))
    elif intersection.geom_type == "GeometryCollection":
        for g in intersection.geoms:
            if isinstance(g, Point):
                points.append(g)
            elif g.geom_type == "MultiPoint":
                points.extend(list(g.geoms))
            elif isinstance(g, LineString):
                points.append(g.interpolate(g.length / 2))
    elif isinstance(intersection, LineString):
        points.append(intersection.interpolate(intersection.length / 2))
    elif intersection.geom_type == "MultiLineString":
        for g in intersection.geoms:
            points.append(g.interpolate(g.length / 2))

    return points


def dedupe_crossings(crossings: list[tuple[float, Point]], min_separation_m: float = 50.0) -> list[tuple[float, Point]]:
    crossings = sorted(crossings, key=lambda x: x[0])
    deduped: list[tuple[float, Point]] = []
    for dist, pt in crossings:
        if not deduped or abs(dist - deduped[-1][0]) >= min_separation_m:
            deduped.append((dist, pt))
    return deduped


def build_track_info(trk, cfg: Config) -> Optional[TrackInfo]:
    tornado_id = str(trk[cfg.track_id_field])
    start = parse_time(trk[cfg.start_time_field], cfg.timezone)
    end = parse_time(trk[cfg.end_time_field], cfg.timezone)

    if end <= start:
        print(f"Skipping {tornado_id}: end time is not after start time")
        return None

    line = as_single_line(trk.geometry)
    measured_miles = line.length / M_PER_MILE
    total_miles = measured_miles

    if cfg.track_length_field_miles and cfg.track_length_field_miles in trk.index:
        try:
            val = trk[cfg.track_length_field_miles]
            if not pd.isna(val):
                total_miles = float(val)
        except Exception:
            total_miles = measured_miles

    duration_seconds = (end - start).total_seconds()
    duration_minutes = duration_seconds / 60.0
    avg_speed_mph = total_miles / (duration_minutes / 60.0) if duration_minutes > 0 else None

    return TrackInfo(
        row=trk,
        line=line,
        tornado_id=tornado_id,
        start=start,
        end=end,
        measured_miles=measured_miles,
        total_miles=total_miles,
        duration_seconds=duration_seconds,
        duration_minutes=duration_minutes,
        avg_speed_mph=avg_speed_mph,
    )


def find_linked_endpoint_crossings(
    track_infos: list[TrackInfo],
    boundaries: gpd.GeoDataFrame,
    boundary_lines,
    cfg: Config,
) -> dict[int, LinkedEndpointCrossing]:
    """Link an upstream DAT feature ending on a boundary to its downstream feature.

    Neighboring WFOs commonly maintain separate DAT line features that are
    intentionally snapped together at a CWA/county boundary. A normal endpoint
    filter would discard the crossing on both features. This identifies the
    best end-to-start continuation using time, distance, and the counties just
    inside each segment, then records the crossing on the upstream feature.
    """
    linked: dict[int, LinkedEndpointCrossing] = {}

    for upstream_idx, upstream in enumerate(track_infos):
        upstream_end = Point(upstream.line.coords[-1])
        upstream_county = boundary_name_at_point(
            boundaries,
            point_at_distance(
                upstream.line,
                max(0.0, upstream.line.length - cfg.endpoint_sample_offset_m),
            ),
            cfg.boundary_name_field,
        )
        if upstream_county is None:
            continue

        best: Optional[tuple[float, LinkedEndpointCrossing]] = None

        for downstream_idx, downstream in enumerate(track_infos):
            if downstream_idx == upstream_idx:
                continue

            time_gap = abs((downstream.start - upstream.end).total_seconds())
            if time_gap > cfg.endpoint_link_time_seconds:
                continue

            downstream_start = Point(downstream.line.coords[0])
            endpoint_gap = upstream_end.distance(downstream_start)
            if endpoint_gap > cfg.endpoint_link_distance_m:
                continue

            shared_point = Point(
                (upstream_end.x + downstream_start.x) / 2.0,
                (upstream_end.y + downstream_start.y) / 2.0,
            )
            if shared_point.distance(boundary_lines) > cfg.endpoint_link_distance_m:
                continue

            downstream_county = boundary_name_at_point(
                boundaries,
                point_at_distance(
                    downstream.line,
                    min(cfg.endpoint_sample_offset_m, downstream.line.length),
                ),
                cfg.boundary_name_field,
            )
            if downstream_county is None or downstream_county == upstream_county:
                continue

            # Prefer the closest spatial and temporal continuation when more
            # than one candidate falls within the tolerances.
            score = endpoint_gap + time_gap
            candidate = LinkedEndpointCrossing(
                point=shared_point,
                boundary_from=upstream_county,
                boundary_to=downstream_county,
                downstream_event_id=downstream.tornado_id,
            )
            if best is None or score < best[0]:
                best = (score, candidate)

        if best is not None:
            linked[upstream_idx] = best[1]

    return linked


def make_output_row(
    info: TrackInfo,
    crossing_index: int,
    dist_m: float,
    pt_proj: Point,
    crossing_time: pd.Timestamp,
    before_name: Optional[str],
    after_name: Optional[str],
    cfg: Config,
    review_flag: str = "",
) -> dict[str, Any]:
    measured_fraction = dist_m / info.line.length if info.line.length else 0.0
    crossing_distance_miles = measured_fraction * info.total_miles
    pt_wgs = gpd.GeoSeries([pt_proj], crs=cfg.projected_crs).to_crs("EPSG:4326").iloc[0]

    if not review_flag and (before_name is None or after_name is None):
        review_flag = "CHECK"

    return {
        "event_id": info.tornado_id,
        "stormdate": info.row.get("stormdate", ""),
        "wfo": info.row.get("wfo", ""),
        "efscale": info.row.get("efscale", ""),
        "start_time": info.start.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "end_time": info.end.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "duration_minutes": round(info.duration_minutes, 2),
        "measured_track_miles": round(info.measured_miles, 3),
        "total_track_miles_used": round(info.total_miles, 3),
        "avg_speed_mph": round(info.avg_speed_mph, 1) if info.avg_speed_mph is not None else None,
        "crossing_index": crossing_index,
        "crossing_distance_miles": round(crossing_distance_miles, 3),
        "crossing_fraction": round(measured_fraction, 5),
        "crossing_time": crossing_time.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "boundary_from": before_name,
        "boundary_to": after_name,
        "crossing_lon": round(pt_wgs.x, 6),
        "crossing_lat": round(pt_wgs.y, 6),
        "review_flag": review_flag,
    }


def calculate(cfg: Config) -> pd.DataFrame:
    tracks = gpd.read_file(cfg.tracks_file)
    boundaries = gpd.read_file(cfg.boundaries_file)

    if tracks.empty:
        raise ValueError(f"No DAT track features found in {cfg.tracks_file}. Check date/bbox/workflow inputs.")
    if boundaries.empty:
        raise ValueError(f"No boundary polygon features found in {cfg.boundaries_file}. Boundary fetch failed or file is empty.")

    required_track_fields = [cfg.track_id_field, cfg.start_time_field, cfg.end_time_field]
    for field in required_track_fields:
        if field not in tracks.columns:
            raise KeyError(f"Track field not found: {field}. Available: {list(tracks.columns)}")
    if cfg.boundary_name_field not in boundaries.columns:
        raise KeyError(f"Boundary name field not found: {cfg.boundary_name_field}. Available: {list(boundaries.columns)}")

    if tracks.crs is None:
        tracks = tracks.set_crs("EPSG:4326")
    if boundaries.crs is None:
        boundaries = boundaries.set_crs("EPSG:4326")

    tracks_proj = tracks.to_crs(cfg.projected_crs)
    boundaries_proj = boundaries.to_crs(cfg.projected_crs)

    # Use all individual county/parish polygon boundary rings. This preserves
    # internal boundaries. Using boundaries_proj.geometry.union_all().boundary
    # dissolves internal boundaries and causes a header-only CSV.
    boundary_lines = boundaries_proj.geometry.boundary.union_all()

    track_infos = []
    for _, trk in tracks_proj.iterrows():
        info = build_track_info(trk, cfg)
        if info is not None:
            track_infos.append(info)

    linked_endpoints = find_linked_endpoint_crossings(
        track_infos,
        boundaries_proj,
        boundary_lines,
        cfg,
    )

    rows = []

    for track_idx, info in enumerate(track_infos):
        pts = extract_crossing_points(info.line, boundary_lines)
        crossings = []
        for pt in pts:
            dist_m = info.line.project(pt)
            # Ordinary isolated endpoint touches remain excluded. A legitimate
            # split-track endpoint crossing is added separately below after a
            # matching downstream DAT segment has been confirmed.
            if dist_m < 10 or dist_m > info.line.length - 10:
                continue
            crossings.append((dist_m, pt))

        crossings = dedupe_crossings(crossings)
        crossing_index = 1

        for dist_m, pt_proj in crossings:
            measured_fraction = dist_m / info.line.length if info.line.length else None
            if measured_fraction is None:
                continue

            before_name, after_name = from_to_names(
                boundaries_proj,
                info.line,
                dist_m,
                cfg.boundary_name_field,
            )
            if before_name == after_name:
                continue

            crossing_time = info.start + pd.Timedelta(
                seconds=measured_fraction * info.duration_seconds
            )
            rows.append(
                make_output_row(
                    info,
                    crossing_index,
                    dist_m,
                    pt_proj,
                    crossing_time,
                    before_name,
                    after_name,
                    cfg,
                )
            )
            crossing_index += 1

        linked = linked_endpoints.get(track_idx)
        if linked is not None:
            rows.append(
                make_output_row(
                    info,
                    crossing_index,
                    info.line.length,
                    linked.point,
                    info.end,
                    linked.boundary_from,
                    linked.boundary_to,
                    cfg,
                    review_flag=f"LINKED_DAT_SEGMENT:{linked.downstream_event_id}",
                )
            )

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate tornado parish/county crossing times.")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    args = parser.parse_args()

    cfg = load_config(args.config)
    df = calculate(cfg)

    out = Path(cfg.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(f"Wrote {len(df)} crossing records to {out}")
    if df.empty:
        print("No parish/county crossings found. CSV has headers only; this can be valid if all tracks stay inside one boundary.")


if __name__ == "__main__":
    main()
