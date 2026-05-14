from pathlib import Path
import argparse
import json
import requests

DAT_LINES_QUERY_URL = (
    "https://services.dat.noaa.gov/arcgis/rest/services/"
    "nws_damageassessmenttoolkit/DamageViewer/MapServer/1/query"
)

def fetch_dat_lines(start_date, end_date, bbox, output):
    """
    bbox format:
    min_lon,min_lat,max_lon,max_lat
    Example for LIX-ish area:
    -91.8,28.5,-87.8,31.5
    """

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
        "resultRecordCount": 2000,
    }

    # DAT layer is time-enabled, but field names can be squirrelly.
    # Keep bbox first. We can tighten date filtering after seeing real attributes.

    r = requests.get(DAT_LINES_QUERY_URL, params=params, timeout=60)
    r.raise_for_status()

    data = r.json()

    output = Path(output)
    output.parent.mkdir(exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {len(data.get('features', []))} DAT line features to {output}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument(
        "--bbox",
        default="-91.8,28.5,-87.8,31.5",
        help="min_lon,min_lat,max_lon,max_lat",
    )
    p.add_argument(
        "--output",
        default="data/dat_damage_lines.geojson",
        help="Output GeoJSON path",
    )
    args = p.parse_args()

    fetch_dat_lines(args.start, args.end, args.bbox, args.output)

if __name__ == "__main__":
    main()
