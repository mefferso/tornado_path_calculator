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


def extract_crossing_points(line: LineString, boundary_union) -> list[Point]:
    intersection = line.intersection(boundary_union.boundary)
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

    return points


def dedupe_crossings(crossings: list[tuple[float, Point]], min_separation_m: float = 50.0) -> list[tuple[float, Point]]:
    crossings = sorted(crossings, key=lambda x: x[0])
    deduped: list[tuple[float, Point]] = []
    for dist, pt in crossings:
        if not deduped or abs(dist - deduped[-1][0]) >= min_separation_m:
            deduped.append((dist, pt))
    return deduped


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
    boundary_union = boundaries_proj.geometry.union_all()

    rows = []

    for _, trk in tracks_proj.iterrows():
        tornado_id = str(trk[cfg.track_id_field])
        start = parse_time(trk[cfg.start_time_field], cfg.timezone)
        end = parse_time(trk[cfg.end_time_field], cfg.timezone)

        if end <= start:
            print(f"Skipping {tornado_id}: end time is not after start time")
            continue

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

        pts = extract_crossing_points(line, boundary_union)
        crossings = []
        for pt in pts:
            dist_m = line.project(pt)
            if dist_m < 10 or dist_m > line.length - 10:
                continue
            crossings.append((dist_m, pt))

        crossings = dedupe_crossings(crossings)

        for i, (dist_m, pt_proj) in enumerate(crossings, start=1):
            measured_fraction = dist_m / line.length if line.length else None
            if measured_fraction is None:
                continue

            crossing_distance_miles = measured_fraction * total_miles
            crossing_time = start + pd.Timedelta(seconds=measured_fraction * duration_seconds)

            before_name, after_name = from_to_names(boundaries_proj, line, dist_m, cfg.boundary_name_field)

            pt_wgs = gpd.GeoSeries([pt_proj], crs=cfg.projected_crs).to_crs("EPSG:4326").iloc[0]

            rows.append(
                {
                    "event_id": tornado_id,
                    "stormdate": trk.get("stormdate", ""),
                    "wfo": trk.get("wfo", ""),
                    "efscale": trk.get("efscale", ""),
                    "start_time": start.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
                    "end_time": end.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
                    "duration_minutes": round(duration_minutes, 2),
                    "measured_track_miles": round(measured_miles, 3),
                    "total_track_miles_used": round(total_miles, 3),
                    "avg_speed_mph": round(avg_speed_mph, 1) if avg_speed_mph is not None else None,
                    "crossing_index": i,
                    "crossing_distance_miles": round(crossing_distance_miles, 3),
                    "crossing_fraction": round(measured_fraction, 5),
                    "crossing_time": crossing_time.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
                    "boundary_from": before_name,
                    "boundary_to": after_name,
                    "crossing_lon": round(pt_wgs.x, 6),
                    "crossing_lat": round(pt_wgs.y, 6),
                    "review_flag": "CHECK" if before_name == after_name or before_name is None or after_name is None else "",
                }
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
