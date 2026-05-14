from pathlib import Path
import argparse
from datetime import datetime, timezone, timedelta
import json
import sys
import requests

DAT_LINES_QUERY_URL = (
    "https://services.dat.noaa.gov/arcgis/rest/services/"
    "nws_damageassessmenttoolkit/DamageViewer/MapServer/1/query"
)

DEFAULT_BBOX = "-91.8,28.5,-87.8,31.5"


def normalize_args(argv):
    """Make argparse handle bbox values that begin with a minus sign.

    A bbox like -91.8,28.5,-87.8,31.5 starts with '-', so argparse can
    mistake it for another option when passed as: --bbox -91.8,...
    This rewrites it to: --bbox=-91.8,... before argparse sees it.
    """
    fixed = []
    i = 0
    while i < len(argv):
        item = argv[i]
        if item == "--bbox":
            if i + 1 < len(argv) and "," in argv[i + 1]:
                fixed.append(f"--bbox={argv[i + 1]}")
                i += 2
                continue
            fixed.append(f"--bbox={DEFAULT_BBOX}")
            i += 1
            continue
        fixed.append(item)
        i += 1
    return fixed


def date_to_epoch_ms(date_text, end_of_day=False):
    """Convert YYYY-MM-DD to ArcGIS epoch milliseconds in UTC.

    If end_of_day=True, return the last millisecond of that calendar date.
    """
    dt = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(milliseconds=1)
    return int(dt.timestamp() * 1000)


def fetch_dat_lines(start_date, end_date, bbox, output):
    """
    bbox format:
    min_lon,min_lat,max_lon,max_lat
    Example for LIX-ish area:
    -91.8,28.5,-87.8,31.5
    """

    if not bbox:
        bbox = DEFAULT_BBOX

    start_ms = date_to_epoch_ms(start_date, end_of_day=False)
    end_ms = date_to_epoch_ms(end_date, end_of_day=True)

    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "geometry": bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
        "time": f"{start_ms},{end_ms}",
        "resultRecordCount": 2000,
    }

    r = requests.get(DAT_LINES_QUERY_URL, params=params, timeout=60)
    r.raise_for_status()

    data = r.json()

    output = Path(output)
    output.parent.mkdir(exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    feature_count = len(data.get("features", []))
    print(f"Used bbox: {bbox}")
    print(f"Used date window: {start_date} through {end_date}")
    print(f"Used ArcGIS time: {start_ms},{end_ms}")
    print(f"Wrote {feature_count} DAT line features to {output}")

    if feature_count:
        props = data["features"][0].get("properties", {})
        print("First feature property fields:")
        print(", ".join(sorted(props.keys())))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument(
        "--bbox",
        default=DEFAULT_BBOX,
        help="min_lon,min_lat,max_lon,max_lat",
    )
    p.add_argument(
        "--output",
        default="data/dat_damage_lines.geojson",
        help="Output GeoJSON path",
    )
    args = p.parse_args(normalize_args(sys.argv[1:]))

    fetch_dat_lines(args.start, args.end, args.bbox, args.output)


if __name__ == "__main__":
    main()
