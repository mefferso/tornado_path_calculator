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
PAGE_SIZE = 1000


def normalize_args(argv):
    """Make argparse handle bbox values that begin with a minus sign."""
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
    """Convert YYYY-MM-DD to ArcGIS epoch milliseconds in UTC."""
    dt = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(milliseconds=1)
    return int(dt.timestamp() * 1000)


def normalize_event_ids(data):
    """Fill blank DAT event IDs from the stable ArcGIS object ID."""
    normalized = 0

    for feature in data.get("features", []):
        properties = feature.setdefault("properties", {})
        current = properties.get("event_id")

        if current is not None and str(current).strip():
            continue

        fallback = properties.get("objectid", properties.get("OBJECTID"))
        if fallback is None or not str(fallback).strip():
            continue

        if isinstance(fallback, float) and fallback.is_integer():
            fallback = int(fallback)

        properties["event_id"] = str(fallback).strip()
        normalized += 1

    return normalized


def feature_key(feature):
    """Return a stable key used to guard against duplicate paginated records."""
    properties = feature.get("properties", {})
    object_id = properties.get("objectid", properties.get("OBJECTID"))
    if object_id is not None and str(object_id).strip():
        return f"objectid:{object_id}"

    event_id = properties.get("event_id")
    start_time = properties.get("starttime")
    end_time = properties.get("endtime")
    return f"event:{event_id}|{start_time}|{end_time}"


def fetch_dat_lines(start_date, end_date, bbox, output):
    """Fetch all DAT tornado damage lines intersecting the bbox and date range."""
    if not bbox:
        bbox = DEFAULT_BBOX

    start_ms = date_to_epoch_ms(start_date, end_of_day=False)
    end_ms = date_to_epoch_ms(end_date, end_of_day=True)

    base_params = {
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
        "orderByFields": "objectid ASC",
        "resultRecordCount": PAGE_SIZE,
    }

    all_features = []
    seen = set()
    offset = 0
    page_number = 1

    while True:
        params = dict(base_params)
        params["resultOffset"] = offset

        response = requests.get(DAT_LINES_QUERY_URL, params=params, timeout=90)
        response.raise_for_status()
        page = response.json()

        if "error" in page:
            raise RuntimeError(f"DAT ArcGIS query failed: {page['error']}")

        features = page.get("features", [])
        print(f"DAT page {page_number}: {len(features)} feature(s) at offset {offset}")

        for feature in features:
            key = feature_key(feature)
            if key not in seen:
                seen.add(key)
                all_features.append(feature)

        exceeded = bool(page.get("exceededTransferLimit"))
        if not features or (len(features) < PAGE_SIZE and not exceeded):
            break

        offset += len(features)
        page_number += 1

        if page_number > 100:
            raise RuntimeError("DAT pagination exceeded 100 pages; aborting to avoid an infinite loop")

    data = {
        "type": "FeatureCollection",
        "features": all_features,
    }

    normalized_event_ids = normalize_event_ids(data)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    feature_count = len(all_features)
    print(f"Used bbox: {bbox}")
    print(f"Used date window: {start_date} through {end_date}")
    print(f"Used ArcGIS time: {start_ms},{end_ms}")
    print(f"Wrote {feature_count} DAT line features to {output}")

    if normalized_event_ids:
        print(f"Filled {normalized_event_ids} blank event_id value(s) from objectid.")

    if feature_count:
        props = all_features[0].get("properties", {})
        print("First feature property fields:")
        print(", ".join(sorted(props.keys())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--bbox",
        default=DEFAULT_BBOX,
        help="min_lon,min_lat,max_lon,max_lat",
    )
    parser.add_argument(
        "--output",
        default="data/dat_damage_lines.geojson",
        help="Output GeoJSON path",
    )
    args = parser.parse_args(normalize_args(sys.argv[1:]))

    fetch_dat_lines(args.start, args.end, args.bbox, args.output)


if __name__ == "__main__":
    main()
