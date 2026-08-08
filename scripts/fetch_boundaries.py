from pathlib import Path
import geopandas as gpd

# Use the full-resolution TIGER/Line county polygons, not the generalized
# 1:500,000 cartographic boundary file.  The generalized CB file can move
# winding county lines by hundreds of meters and can create false/repeated
# intersections with a tornado track.
URL = "https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip"

OUT = Path("data/parish_county_boundaries.geojson")

# LA=22, MS=28, AL=01
STATEFP_KEEP = ["22", "28", "01"]


def main():
    Path("data").mkdir(exist_ok=True)

    gdf = gpd.read_file(URL)
    gdf = gdf[gdf["STATEFP"].isin(STATEFP_KEEP)].copy()

    gdf["boundary_name"] = gdf["NAME"]
    gdf["statefp"] = gdf["STATEFP"]
    gdf["geoid"] = gdf["GEOID"]

    gdf = gdf.to_crs("EPSG:4326")
    gdf.to_file(OUT, driver="GeoJSON")

    print(f"Wrote {len(gdf)} full-resolution TIGER boundaries to {OUT}")


if __name__ == "__main__":
    main()
