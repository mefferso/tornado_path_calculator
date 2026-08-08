# Tornado Path Crossing Calculator

Interactive parish/county crossing-time map for QC'd NWS Damage Assessment Toolkit (DAT) tornado tracks in the New Orleans/Baton Rouge-area bbox.

The public map uses a **precomputed archive from January 1, 2015 through the present**. The archive refreshes automatically once per day with GitHub Actions, so choosing dates on the map is an instant browser-side filter; it does **not** launch a workflow or require Google Apps Script.

## Public map

`https://mefferso.github.io/tornado_path_calculator/`

## What it calculates

For each DAT tornado path, the processing pipeline derives:

- measured path length
- duration
- average forward speed
- parish/county boundary crossing locations
- distance into the track at each crossing
- estimated crossing time
- from/to parish or county when identifiable

Crossing time is estimated by linear interpolation along the finalized track:

```text
crossing_time = start_time + (distance_into_track / total_track_length) * duration
```

That assumes constant forward speed over the finalized path.

## Archive workflow

`.github/workflows/run-crossings.yml` runs:

- automatically once per day
- manually via `workflow_dispatch` if an immediate refresh is ever needed
- once when the workflow/scripts/map logic are changed on `main`

Each refresh:

1. downloads parish/county boundaries
2. queries DAT tornado line features from `2015-01-01` through the current UTC date for the configured bbox
3. recalculates every boundary crossing
4. copies the master GeoJSON and CSV into `docs/data/`
5. commits changed archive files back to `main`

The DAT fetcher paginates ArcGIS results so the archive is not limited to a single response page.

## Map behavior

`docs/index.html` loads the master archive once, then filters it locally by the selected start/end dates. The date controls never modify repository data and never call a backend.

## Main files

```text
.github/workflows/run-crossings.yml   # daily archive refresh
scripts/fetch_dat_tracks.py           # DAT ArcGIS query + pagination
scripts/fetch_boundaries.py           # parish/county polygons
scripts/calculate_crossing_times.py   # crossing calculations
scripts/build_map.py                  # copies generated data to docs/data
config.json                           # calculation field/config settings
data/dat_damage_lines.geojson         # master DAT archive
output/tornado_crossing_times.csv     # master crossing table
docs/index.html                       # GitHub Pages viewer/date filter
docs/data/                            # files served by the viewer
```

## Calculation notes

- Distances use projected CRS `EPSG:5070`.
- DAT multi-part paths are merged where possible.
- Split DAT segments that meet near a parish/county boundary are checked for a legitimate linked endpoint crossing.
- Isolated endpoint touches are excluded from ordinary crossing detection.
- Some crossings can still merit human review because the estimate assumes constant forward speed between the DAT start and end times.
