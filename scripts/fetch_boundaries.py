from pathlib import Path
import geopandas as gpd

URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"

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

    print(f"Wrote {len(gdf)} boundaries to {OUT}")

if __name__ == "__main__":
    main()
