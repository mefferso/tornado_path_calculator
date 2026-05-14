[README.md](https://github.com/user-attachments/files/27776611/README.md)
# Tornado Path Tools

Calculate parish/county crossing times from QC'd tornado tracks.

This repo takes tornado path GIS data, such as DAT-exported GeoJSON/Shapefile/KMZ-converted tracks, intersects those tracks with parish/county boundaries, and estimates the time each tornado crossed a boundary using a constant-speed assumption.

## What it calculates

For each tornado track:

- total path length
- duration
- average forward speed
- distance into track at each parish/county crossing
- estimated crossing time
- from/to parish or county when possible

## Assumption

Crossing time is estimated by linear interpolation along the track:

```text
crossing_time = start_time + (distance_into_track / total_track_length) * duration
```

This is the same math normally done manually for Storm Data or survey summaries. It assumes constant forward speed along the finalized track.

## Repo structure

```text
tornado_path_tools/
├── config.example.json
├── requirements.txt
├── README.md
├── data/
│   ├── dat_tracks.geojson        # put your DAT tracks here
│   └── parishes.geojson          # put parish/county boundaries here
├── output/
│   └── tornado_crossing_times.csv
└── scripts/
    └── calculate_crossing_times.py
```

## Track input requirements

Your tornado track file should contain line geometries and these fields:

| Field | Example | Notes |
|---|---|---|
| tornado_id | `2026-05-14_EF1_001` | Any unique ID/name |
| start_time | `2026-05-14 20:29` | Local time or ISO timestamp |
| end_time | `2026-05-14 20:42` | Local time or ISO timestamp |

You can change the field names in `config.json`.

## Boundary input requirements

Boundary file should be polygons with a name field such as:

| Field | Example |
|---|---|
| NAME | `Tangipahoa` |

You can change the boundary name field in `config.json`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate   # Windows PowerShell

pip install -r requirements.txt
cp config.example.json config.json
```

Edit `config.json` to point to your actual input files and field names.

## Run

```bash
python scripts/calculate_crossing_times.py --config config.json
```

## Output columns

| Column | Meaning |
|---|---|
| tornado_id | ID/name of tornado track |
| start_time | tornado start time |
| end_time | tornado end time |
| duration_minutes | total duration |
| total_track_miles | measured GIS track length |
| avg_speed_mph | average forward speed |
| crossing_index | crossing number along path |
| crossing_distance_miles | distance into track |
| crossing_fraction | fraction of track completed |
| crossing_time | estimated boundary crossing time |
| boundary_from | polygon before crossing, if identified |
| boundary_to | polygon after crossing, if identified |
| crossing_lon | crossing longitude |
| crossing_lat | crossing latitude |

## Notes

- Use a projected CRS for distance calculations. The default is `EPSG:5070`, which is good for CONUS distance work.
- For Louisiana/Mississippi/Alabama work, `EPSG:5070` is fine.
- If the DAT path has multiple segments, this script merges line parts where possible.
- If a track starts exactly on a boundary, the first crossing may need human review.
